"""
可视化仪表盘 - Dash Web 应用
"""

import os, sys, json, time, traceback

# Windows GBK 环境下强制 stdout/stderr 使用 UTF-8
if sys.platform == 'win32':
    for _fh in (sys.stdout, sys.stderr):
        try:
            _fh.reconfigure(encoding='utf-8')
        except Exception:
            pass

import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

import config as cfg
from data import fetch_stock_pool, build_panel
from factors import compute_all_factors
from strategy import normalize_factors, generate_signals, get_target_weights
from backtest import BacktestEngine

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="量化因子策略系统",
    suppress_callback_exceptions=True,
)

_state = {
    "data": None, "factors": None, "composite": None,
    "signals": None, "weights": None, "engine": None,
    "close_panel": None, "loaded": False, "message": "",
}


def run_pipeline(stock_pool, start_date, end_date, max_pos, init_cap, use_cache_only=False):
    _state["message"] = "读取数据..."
    try:
        _state["data"] = fetch_stock_pool(stock_pool, start_date, end_date,
                                          use_cache_only=use_cache_only)
    except Exception as e:
        _state["message"] = f"数据获取失败: {e}"
        return False

    if not _state["data"]:
        _state["message"] = "无数据，请先「联网回测」拉取"
        return False

    _state["close_panel"] = build_panel(_state["data"], "close")
    if _state["close_panel"].empty:
        _state["message"] = "close 面板为空"
        return False

    _state["message"] = "计算因子..."
    _state["factors"] = compute_all_factors(_state["data"])

    _state["message"] = "合成因子..."
    _state["composite"] = normalize_factors(_state["factors"])

    _state["message"] = "生成信号..."
    _state["signals"] = generate_signals(_state["composite"], max_positions=max_pos)
    _state["weights"] = get_target_weights(_state["signals"])

    _state["message"] = "执行回测..."
    engine = BacktestEngine(
        close_panel=_state["close_panel"],
        target_weights=_state["weights"],
        initial_capital=init_cap,
    )
    engine.run()
    _state["engine"] = engine
    _state["loaded"] = True
    _state["message"] = "完成"
    return True


# ======== Chart Helpers ========

def _kpi_card(title, value, color="#45df7e"):
    return html.Div([
        html.Div(title, style={"color": "#999", "fontSize": "0.72rem", "marginBottom": "4px"}),
        html.Div(value, style={
            "color": color, "fontWeight": "bold", "fontSize": "1.25rem",
            "fontFamily": "monospace",
        }),
    ], style={
        "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33",
        "borderRadius": "6px", "padding": "10px 12px", "textAlign": "center",
    })


def _empty_fig(msg="暂无数据", height=None):
    fig = go.Figure()
    fig.add_annotation(
        text=msg, x=0.5, y=0.5, showarrow=False,
        font=dict(color="#555", size=15),
    )
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#14161a",
        paper_bgcolor="#14161a",
        font=dict(color="#aaa", size=11),
        margin=dict(l=30, r=30, t=35, b=25),
        xaxis=dict(showgrid=True, gridcolor="#1e1e24", zeroline=False,
                   showticklabels=False),
        yaxis=dict(showgrid=True, gridcolor="#1e1e24", zeroline=False,
                   showticklabels=False),
    )
    if height:
        fig.update_layout(height=height)
    return fig


def _base_layout(fig, title="", height=None):
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#14161a",
        paper_bgcolor="#14161a",
        font=dict(color="#aaa", size=11),
        margin=dict(l=40, r=25, t=65, b=35),
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color="#aaa", size=10)),
        title=dict(text=title, font=dict(color="#ccc", size=13), x=0.01,
                   y=0.97, yanchor="top") if title else None,
    )
    fig.update_xaxes(gridcolor="#1e1e24", zeroline=False, showgrid=True, automargin=True)
    fig.update_yaxes(gridcolor="#1e1e24", zeroline=False, showgrid=True, automargin=True)
    if height:
        fig.update_layout(height=height)
    return fig


def _init_display():
    kpi = [dbc.Col(_kpi_card(t, "--"), width=2) for t in
           ["累计收益率", "年化收益率", "夏普比率", "最大回撤", "胜率", "最终权益"]]
    eq = _empty_fig("暂无数据")
    dd = _empty_fig("")
    heat = _empty_fig("")
    factor = _empty_fig("")
    trade = html.P("暂无交易记录", style={"color": "#666", "textAlign": "center", "marginTop": "40px"})
    plan = _build_today_plan_placeholder()
    return plan, kpi, eq, dd, heat, factor, trade


def _build_today_plan_placeholder():
    return dbc.Card([
        dbc.CardHeader(html.Span("今日操作建议", style={"color": "#999", "fontSize": "0.9rem"})),
        dbc.CardBody(
            html.P("点击上方按钮加载数据后显示", style={"color": "#555", "textAlign": "center", "margin": "0"}),
            style={"padding": "14px"},
        ),
    ], style={"backgroundColor": "#16191f", "border": "1px solid #2a2d33", "borderRadius": "6px", "marginBottom": "8px"})


def _build_today_plan(composite, close_panel, max_pos, prev_pnl):
    """构建当日操作建议 UI"""
    if composite is None or composite.empty:
        return _build_today_plan_placeholder()

    last_date = composite.index[-1]
    row = composite.loc[last_date].dropna()
    top = row[row > 0].nlargest(max_pos)
    if top.empty:
        return _build_today_plan_placeholder()

    n = len(top)
    rows = []
    for stock in top.index:
        score = top[stock]
        weight = 1.0 / n
        price = close_panel.loc[last_date, stock] if stock in close_panel.columns else float("nan")
        stock_code = f"{int(stock):06d}"
        name = cfg.STOCK_NAMES.get(stock_code, stock_code)
        score_color = "#45df7e" if score > 0 else "#dc3545"
        rows.append(html.Tr([
            html.Td(stock_code, style={"fontFamily": "monospace", "fontWeight": "bold", "color": "#ccc"}),
            html.Td(name, style={"color": "#aaa"}),
            html.Td(f"{score:+.2f}", style={"color": score_color, "fontFamily": "monospace"}),
            html.Td(f"{weight:.1%}", style={"color": "#ffc107", "fontFamily": "monospace"}),
            html.Td(f"{price:.2f}", style={"fontFamily": "monospace", "color": "#ccc"}),
        ]))

    table_header = html.Thead(html.Tr([
        html.Th("代码", style={"color": "#777", "fontSize": "0.72rem"}),
        html.Th("名称", style={"color": "#777", "fontSize": "0.72rem"}),
        html.Th("得分", style={"color": "#777", "fontSize": "0.72rem"}),
        html.Th("权重", style={"color": "#777", "fontSize": "0.72rem"}),
        html.Th("现价", style={"color": "#777", "fontSize": "0.72rem"}),
    ]))

    table = dbc.Table(
        [table_header, html.Tbody(rows)],
        striped=False, bordered=False, hover=True, size="sm",
        style={"fontSize": "0.78rem", "marginBottom": "0"},
    )

    # P&L 跟踪行
    pnl_row = None
    if prev_pnl is not None:
        pnl_val = prev_pnl["pnl"]
        pnl_color = "#45df7e" if pnl_val >= 0 else "#dc3545"
        pnl_sign = "+" if pnl_val >= 0 else ""
        details = prev_pnl.get("details", [])
        detail_str = ", ".join(
            f'{d["name"]}({d["return"]:+.1%})' for d in sorted(details, key=lambda x: x["return"], reverse=True)
        )
        pnl_row = html.Div([
            html.Span(f"上期推荐跟踪: ", style={"color": "#888", "fontSize": "0.75rem"}),
            html.Span(f"{pnl_sign}{pnl_val:.2%}", style={"color": pnl_color, "fontWeight": "bold", "fontSize": "0.82rem", "fontFamily": "monospace"}),
            html.Span(f" ({detail_str})", style={"color": "#666", "fontSize": "0.7rem"}),
        ], style={"marginTop": "8px"})

    header_right = html.Span(
        f"数据日期: {last_date.strftime('%Y-%m-%d')} | 建议持仓: {n}只",
        style={"color": "#888", "fontSize": "0.72rem", "float": "right"},
    )

    return dbc.Card([
        dbc.CardHeader(html.Div([
            html.Span("今日操作建议", style={"color": "#45df7e", "fontSize": "0.9rem", "fontWeight": "bold"}),
            header_right,
        ])),
        dbc.CardBody([
            table,
            pnl_row if pnl_row else html.Div(style={"height": "4px"}),
        ], style={"padding": "10px 14px"}),
    ], style={"backgroundColor": "#16191f", "border": "1px solid #2a2d33", "borderRadius": "6px", "marginBottom": "8px"})


def _error_display(msg):
    kpi = [dbc.Col(_kpi_card(t, "--"), width=2) for t in
           ["累计收益率", "年化收益率", "夏普比率", "最大回撤", "胜率", "最终权益"]]
    err_fig = _empty_fig(f"⚠ {msg}")
    return kpi, err_fig, err_fig, err_fig, err_fig, \
        html.P(msg, style={"color": "#dc3545", "textAlign": "center", "marginTop": "20px"})


# ======== 今日操作建议 ========

RECS_FILE = os.path.join(cfg.CACHE_DIR, "recommendations.csv")


def _save_recommendation(composite, close_panel, max_pos):
    """保存最新日期的推荐到 CSV，用于次日收益对比"""
    if composite is None or composite.empty:
        return
    last_date = composite.index[-1]
    row = composite.loc[last_date].dropna()
    top = row[row > 0].nlargest(max_pos)
    if top.empty:
        return

    n = len(top)
    records = []
    for stock, score in top.items():
        price = close_panel.loc[last_date, stock] if stock in close_panel.columns else float("nan")
        records.append({
            "date": last_date.strftime("%Y-%m-%d"),
            "stock": f"{int(stock):06d}",
            "score": round(float(score), 4),
            "weight": round(1.0 / n, 4),
            "close_price": round(float(price), 2),
        })

    df_new = pd.DataFrame(records)
    df_new.to_csv(RECS_FILE, index=False)
    print(f"[REC] Saved {len(records)} recommendations for {last_date.date()}")


def _load_prev_recommendation():
    """读取上一条推荐记录（所有同日的股票）"""
    if not os.path.exists(RECS_FILE):
        return None
    df = pd.read_csv(RECS_FILE, parse_dates=["date"], dtype={"stock": str})
    if df.empty:
        return None
    last_date = df["date"].max()
    return df[df["date"] == last_date]


def _calc_recommendation_pnl(prev_recs, data_dict):
    """计算上一期推荐在最新交易日的加权收益率"""
    if prev_recs is None or prev_recs.empty or not data_dict:
        return None

    # 上一期推荐的日期
    prev_date = pd.Timestamp(prev_recs["date"].iloc[0])
    total_return = 0.0
    total_weight = 0.0
    details = []

    for _, r in prev_recs.iterrows():
        stock = f"{int(r['stock']):06d}"
        prev_price = r["close_price"]
        weight = r["weight"]

        if stock not in data_dict:
            continue
        df = data_dict[stock]
        # 找上一个推荐日期之后的第一个交易日
        future = df[df.index > prev_date]
        if future.empty:
            continue
        next_date = future.index[0]
        curr_price = float(future.iloc[0]["close"])
        if pd.isna(curr_price) or curr_price <= 0 or pd.isna(prev_price) or prev_price <= 0:
            continue

        stock_return = (curr_price / prev_price - 1)
        total_return += stock_return * weight
        total_weight += weight
        details.append({
            "stock": stock,
            "name": cfg.STOCK_NAMES.get(stock, stock),
            "prev_date": prev_date.strftime("%m-%d"),
            "next_date": next_date.strftime("%m-%d"),
            "prev_price": prev_price,
            "curr_price": curr_price,
            "return": stock_return,
            "weight": weight,
        })

    if total_weight == 0:
        return None

    pnl = total_return / total_weight  # 归一化
    return {"pnl": pnl, "prev_date": prev_date, "details": details}


# ======== Layout ========

def _read_cache_date_range():
    """读取缓存文件中实际可用的日期范围"""
    cache_dir = cfg.CACHE_DIR
    if not os.path.isdir(cache_dir):
        return None, None
    min_d, max_d = None, None
    for f in os.listdir(cache_dir):
        if f.endswith(".csv"):
            try:
                fp = os.path.join(cache_dir, f)
                _df = pd.read_csv(fp, index_col=0, parse_dates=True)
                if not _df.empty:
                    s, e = _df.index.min(), _df.index.max()
                    if min_d is None or s < min_d:
                        min_d = s
                    if max_d is None or e > max_d:
                        max_d = e
            except Exception:
                pass
    if min_d is None:
        return None, None
    return min_d.strftime("%Y-%m-%d"), max_d.strftime("%Y-%m-%d")


_cache_start, _cache_end = _read_cache_date_range()
_default_start = _cache_start or cfg.START_DATE
_default_end = _cache_end or cfg.END_DATE

INPUT_STYLE = {
    "width": "140px", "display": "inline-block",
    "backgroundColor": "#1a1d23", "color": "#ccc",
    "border": "1px solid #2a2d33", "fontSize": "0.82rem",
    "height": "32px",
}

STOCK_OPTIONS = [{"label": s, "value": s} for s in cfg.STOCK_POOL]

app.layout = html.Div(style={"backgroundColor": "#111318", "minHeight": "100vh"}, children=[

    # ---- 顶栏 ----
    html.Div([
        html.Div([
            html.H2("量化多因子策略系统",
                    style={"color": "#45df7e", "margin": "0", "fontSize": "1.4rem"}),
            html.Span(" | 数据: BaoStock  |  日频  |  动量/波动/量价/RSI/布林",
                      style={"color": "#777", "fontSize": "0.8rem", "marginLeft": "8px"}),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={"padding": "14px 28px", "backgroundColor": "#16191f", "borderBottom": "1px solid #2a2d33"}),

    # ---- 控制栏 ----
    html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("股票池", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                dcc.Dropdown(
                    id="stock-selector",
                    options=STOCK_OPTIONS,
                    value=cfg.STOCK_POOL,
                    multi=True,
                    style={"minWidth": "280px"},
                ),
            ], width=4),

            dbc.Col([
                html.Label("回测区间", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                html.Div([
                    dcc.Input(
                        id="start-date", type="text",
                        value=_default_start,
                        placeholder="YYYY-MM-DD",
                        style={**INPUT_STYLE, "marginRight": "4px"},
                    ),
                    html.Span("~", style={"color": "#666", "margin": "0 4px", "fontSize": "0.85rem"}),
                    dcc.Input(
                        id="end-date", type="text",
                        value=_default_end,
                        placeholder="YYYY-MM-DD",
                        style=INPUT_STYLE,
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(
                    f"缓存范围: {_default_start} ~ {_default_end}",
                    id="cache-range-hint",
                    style={"color": "#555", "fontSize": "0.7rem", "marginTop": "2px"},
                ),
            ], width=3),

            dbc.Col([
                html.Label(f"最大持仓", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                dcc.Slider(id="max-positions", min=3, max=15, step=1, value=cfg.MAX_POSITIONS,
                           marks={3: "3", 6: "6", 9: "9", 12: "12", 15: "15"}),
            ], width=2),

            dbc.Col([
                html.Label("初始资金(万)", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                dcc.Input(id="initial-capital", type="number", value=100,
                          min=10, max=10000, step=10,
                          style={"width": "90px", "color": "#ccc", "height": "32px",
                                 "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33"}),
            ], width=1),

            dbc.Col([
                html.Label(" ", style={"fontSize": "0.75rem"}),
                html.Div([
                    dbc.Button("缓存加载", id="btn-cache", color="info", size="sm", className="me-1"),
                    dbc.Button("联网回测", id="btn-full", color="success", size="sm"),
                ]),
            ], width=2),
        ], align="end"),
        html.Div(id="status-msg", style={
            "color": "#ffc107", "fontSize": "0.8rem", "marginTop": "8px",
            "minHeight": "20px",
        }),
    ], style={"padding": "14px 28px", "backgroundColor": "#111318", "borderBottom": "1px solid #2a2d33"}),

    # ---- KPI 行 ----
    html.Div(id="kpi-container", children=[
        dbc.Row(id="kpi-row", children=[
            dbc.Col(_kpi_card("累计收益率", "--"), width=2),
            dbc.Col(_kpi_card("年化收益率", "--"), width=2),
            dbc.Col(_kpi_card("夏普比率", "--", "#17a2b8"), width=2),
            dbc.Col(_kpi_card("最大回撤", "--", "#dc3545"), width=2),
            dbc.Col(_kpi_card("胜率", "--", "#ffc107"), width=2),
            dbc.Col(_kpi_card("最终权益", "--"), width=2),
        ]),
    ], style={"padding": "14px 28px"}),

    # ---- 今日操作建议 ----
    html.Div(id="today-plan-container", style={"padding": "0 28px 10px 28px"}),

    # ---- 图表区 ----
    dcc.Loading(id="loading-charts", type="default", color="#45df7e", children=[
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(id="equity-chart", style={"height": "420px"}), width=12),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col(dcc.Graph(id="drawdown-chart", style={"height": "280px"}), width=6),
                dbc.Col(dcc.Graph(id="factor-bar", style={"height": "280px"}), width=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col(dcc.Graph(id="heatmap-chart", style={"height": "320px"}), width=8),
                dbc.Col(html.Div(id="trade-table", style={
                    "maxHeight": "320px", "overflowY": "auto",
                    "backgroundColor": "#16191f", "padding": "10px", "borderRadius": "6px",
                    "border": "1px solid #2a2d33",
                }), width=4),
            ]),
        ], style={"padding": "0 28px 28px 28px"}),
    ]),
])


# ======== Callback（单一体：运行流水线 + 直接返回图表）========

@app.callback(
    [Output("status-msg", "children"),
     Output("cache-range-hint", "children"),
     Output("today-plan-container", "children"),
     Output("kpi-row", "children"),
     Output("equity-chart", "figure"),
     Output("drawdown-chart", "figure"),
     Output("heatmap-chart", "figure"),
     Output("factor-bar", "figure"),
     Output("trade-table", "children")],
    [Input("btn-cache", "n_clicks"),
     Input("btn-full", "n_clicks")],
    [State("stock-selector", "value"),
     State("start-date", "value"),
     State("end-date", "value"),
     State("max-positions", "value"),
     State("initial-capital", "value")],
)
def handle_run(n_cache, n_full, stock_pool, start_date, end_date, max_pos, init_cap):
    """单一回调：运行流水线 + 直接返回所有图表"""
    triggered = callback_context.triggered_id
    print(f"[DEBUG] triggered={triggered}, n_cache={n_cache}, n_full={n_full}")
    print(f"[DEBUG] start={start_date!r}, end={end_date!r}")

    if triggered is None:
        hint_text = f"缓存范围: {_default_start} ~ {_default_end}"
        return "点击「缓存加载」秒开，或「联网回测」拉取最新数据", hint_text, *_init_display()

    use_cache_only = (triggered == "btn-cache")
    if not stock_pool:
        empty = _init_display()
        return "⚠ 请选择至少一只股票", dash.no_update, *empty

    init_cap_val = (init_cap or 100) * 10000
    t0 = time.time()

    try:
        ok = run_pipeline(stock_pool,
                          start_date or cfg.START_DATE,
                          end_date or cfg.END_DATE,
                          max_pos or cfg.MAX_POSITIONS,
                          init_cap_val,
                          use_cache_only=use_cache_only)
    except Exception as e:
        traceback.print_exc()
        empty = _init_display()
        return f"[ERR] 回测异常: {str(e)[:80]}", dash.no_update, *empty

    if not ok:
        print(f"[DEBUG] Pipeline failed: {_state['message']}")
        empty = _init_display()
        return f"[ERR] {_state['message']}", dash.no_update, *empty

    elapsed = time.time() - t0
    engine = _state["engine"]
    m = engine.metrics
    composite = _state["composite"]
    close_panel = _state["close_panel"]

    try:
        # ---- KPI ----
        kpi = [
            dbc.Col(_kpi_card("累计收益率", m.get("累计收益率", "--")), width=2),
            dbc.Col(_kpi_card("年化收益率", m.get("年化收益率 (CAGR)", "--")), width=2),
            dbc.Col(_kpi_card("夏普比率",   m.get("夏普比率", "--"), "#17a2b8"), width=2),
            dbc.Col(_kpi_card("最大回撤",   m.get("最大回撤", "--"), "#dc3545"), width=2),
            dbc.Col(_kpi_card("胜率",       m.get("胜率", "--"), "#ffc107"), width=2),
            dbc.Col(_kpi_card("最终权益",   m.get("最终权益", "--")), width=2),
        ]

        # ---- 权益曲线 ----
        pv = engine.portfolio_value
        eq = pv.sort_index()
        baseline = eq.values[0] if len(eq) > 0 else 1.0
        norm = eq.values / baseline if baseline != 0 else eq.values

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=eq.index, y=norm, mode="lines",
            line=dict(color="#45df7e", width=2),
            fill="tozeroy",
            fillcolor="rgba(69,223,126,0.08)",
            name="策略权益",
            hovertemplate="%{y:.3f}<extra></extra>",
        ))
        fig_eq.add_hline(y=1.0, line_dash="dash", line_color="#555", line_width=1)
        last_val = norm[-1]
        return_pct = (last_val - 1) * 100
        label_color = "#45df7e" if return_pct >= 0 else "#dc3545"
        fig_eq.add_annotation(
            x=eq.index[-1], y=last_val,
            text=f"{return_pct:+.1f}%  ",
            showarrow=False, xanchor="right",
            font=dict(color=label_color, size=11),
        )
        _base_layout(fig_eq, title="权益曲线")
        fig_eq.update_yaxes(title="归一化净值", tickformat=".2f", automargin=True)
        fig_eq.update_xaxes(automargin=True)

        # ---- 回撤图 ----
        dd = engine.get_drawdown_series().sort_index()
        dd_pct = dd.values * 100
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=dd.index, y=dd_pct, mode="lines",
            line=dict(color="#dc3545", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(220,53,69,0.25)",
            name="回撤",
            hovertemplate="%{y:.2f}%<extra></extra>",
        ))
        max_dd_pct = dd.min() * 100
        fig_dd.add_hline(y=max_dd_pct, line_dash="dash", line_color="#ffc107",
                         line_width=1,
                         annotation_text=f"最大: {max_dd_pct:.1f}%",
                         annotation_font=dict(color="#ffc107", size=10))
        fig_dd.add_hline(y=0, line_color="#444", line_width=1)
        _base_layout(fig_dd, title="回撤分析 (%)")
        fig_dd.update_yaxes(tickformat=".1f", automargin=True)
        fig_dd.update_xaxes(automargin=True)

        # ---- 持仓热力图 ----
        pos_df = engine.positions
        pos_sorted = pos_df.reindex(sorted(pos_df.columns), axis=1)
        step_h = max(1, len(pos_sorted) // 200)
        pos_sampled = pos_sorted.iloc[::step_h]
        bin_data = (pos_sampled > 0).astype(int)
        active_cols = bin_data.columns[bin_data.sum() > 0]
        if len(active_cols) == 0:
            fig_heat = _empty_fig("无持仓记录")
        else:
            bin_data = bin_data[active_cols]
            fig_heat = go.Figure(go.Heatmap(
                z=bin_data.T.values,
                x=[str(d).split("T")[0] for d in bin_data.index],
                y=bin_data.columns.tolist(),
                colorscale=[[0, "#1a1d23"], [0.5, "#1a3a1a"], [1, "#45df7e"]],
                showscale=False,
                hoverongaps=False,
            ))
            _base_layout(fig_heat, title="持仓热力图")
            fig_heat.update_xaxes(automargin=True)
            fig_heat.update_yaxes(automargin=True)

        # ---- 因子得分 ----
        if composite is not None and len(composite) > 0:
            last_row = composite.iloc[-1].dropna()
            s = pd.Series({str(k): float(v) for k, v in last_row.items()}).sort_values()
            colors = ["#45df7e" if v > 0 else "#dc3545" for v in s.values]
            fig_factor = go.Figure(go.Bar(
                x=s.values, y=s.index, orientation="h",
                marker=dict(color=colors, line=dict(width=0)),
                text=[f"  {v:+.2f}" for v in s.values],
                textposition="outside",
                textfont=dict(color="#aaa", size=10),
                hovertemplate="%{x:.3f}<extra>%{y}</extra>",
                cliponaxis=False,
            ))
            fig_factor.add_vline(x=0, line_dash="dash", line_color="#555", line_width=1)
            x_pad = max(abs(s.min()), abs(s.max())) * 0.35 + 0.3
            _base_layout(fig_factor, title="最新截面因子综合得分")
            fig_factor.update_xaxes(title="Z-Score", range=[s.min() - x_pad, s.max() + x_pad], automargin=True)
            fig_factor.update_yaxes(automargin=True)
        else:
            fig_factor = _empty_fig("无因子数据")

        # ---- 交易记录 ----
        trades = engine.trade_log[-50:] if engine.trade_log else []
        if trades:
            tdf = pd.DataFrame(trades)
            if "date" in tdf.columns:
                tdf = tdf.sort_values("date", ascending=False).head(30)
            disp = tdf.copy()
            for col in ["price", "amount", "cost"]:
                if col in disp.columns:
                    disp[col] = disp[col].apply(
                        lambda x, c=col: f"{x:.2f}" if c != "amount" else f"{x/10000:.1f}万")
            table = dbc.Table.from_dataframe(
                disp, striped=True, bordered=False, hover=True, size="sm",
                style={"fontSize": "0.7rem", "color": "#ccc"},
            )
        else:
            table = html.P("暂无交易记录", style={"color": "#666", "textAlign": "center", "marginTop": "40px"})

        mode = "缓存" if use_cache_only else "联网"
        msg = (f"[OK] [{mode}] {len(_state['data'])}只 | 耗时{elapsed:.1f}s | "
               f"累计收益 {m.get('累计收益率','?')}")
        hint = f"数据区间: {close_panel.index.min().strftime('%Y-%m-%d')} ~ {close_panel.index.max().strftime('%Y-%m-%d')}"
        print(f"[DASH] {msg}")

        # ---- 今日操作建议 ----
        _save_recommendation(composite, close_panel, max_pos or cfg.MAX_POSITIONS)
        prev_recs = _load_prev_recommendation()
        prev_pnl = _calc_recommendation_pnl(prev_recs, _state["data"])
        today_plan = _build_today_plan(composite, close_panel, max_pos or cfg.MAX_POSITIONS, prev_pnl)

        return msg, hint, today_plan, kpi, fig_eq, fig_dd, fig_heat, fig_factor, table

    except Exception as e:
        traceback.print_exc()
        print(f"[DASH ERROR] handle_run chart build: {e}")
        empty = _init_display()
        return f"[ERR] 图表生成失败: {str(e)[:80]}", dash.no_update, *empty


if __name__ == "__main__":
    app.run(debug=False, port=cfg.DASH_PORT, host="0.0.0.0")
