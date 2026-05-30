"""
可视化仪表盘 - Dash Web 应用
"""

import os, sys, json, time, traceback
from datetime import datetime

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _today_label():
    now = datetime.now()
    wd = WEEKDAY_NAMES[now.weekday()]
    return f"今天是 {now.strftime('%Y-%m-%d')} {wd}"

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
from data import fetch_stock_pool, build_panel, load_from_cache
import supabase_client as db
from factors import compute_all_factors
from strategy import normalize_factors, generate_signals, get_target_weights
from backtest import BacktestEngine

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="量化因子策略系统",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1.0"}],
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
    kpi = [dbc.Col(_kpi_card(t, "--"), xs=6, sm=4, md=4, lg=2) for t in
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

    # 调仓周期提醒
    invest_df = _load_investment_history()
    rebalance_hint = ""
    if not invest_df.empty:
        holding = invest_df[invest_df["status"] == "holding"]
        if not holding.empty:
            exec_date = pd.Timestamp(holding["execute_date"].iloc[0])
            days_held = (last_date - exec_date).days
            freq = getattr(cfg, 'REBALANCE_FREQUENCY', 5)
            if days_held >= freq:
                rebalance_hint = f" | ⚡ 已持有{days_held}天(周期{freq}天)，建议执行调仓"
            else:
                rebalance_hint = f" | 持有{days_held}/{freq}天，距调仓还有{freq-days_held}天"

    header_right = html.Span(
        f"数据日期: {last_date.strftime('%Y-%m-%d')} | 建议持仓: {n}只{rebalance_hint}",
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
    kpi = [dbc.Col(_kpi_card(t, "--"), xs=6, sm=4, md=4, lg=2) for t in
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


# ---------------------------------------------------------------------------
# 模拟投资跟踪 — 一键执行 + 历史P&L
# ---------------------------------------------------------------------------
INVEST_HISTORY_FILE = os.path.join(cfg.CACHE_DIR, "investment_history.csv")
AUTO_STATE_FILE = os.path.join(cfg.CACHE_DIR, "auto_trade_state.json")


def _execute_investment(composite, close_panel, max_pos, force=False):
    """执行当前策略：卖出上一轮持仓（结算盈亏），买入新一轮推荐。
    force=True 时跳过同日期去重（手动/自动中断调用）。"""
    if composite is None or composite.empty:
        return False, "无策略数据"

    last_date = composite.index[-1]
    row = composite.loc[last_date].dropna()
    top = row[row > 0].nlargest(max_pos)
    if top.empty:
        return False, "当前无符合条件的股票"

    # 加载历史
    if os.path.exists(INVEST_HISTORY_FILE):
        df_all = pd.read_csv(INVEST_HISTORY_FILE, dtype={"stock": str})
    else:
        df_all = pd.DataFrame()

    # 同一日期去重（force=True 时跳过，用于手动中断重置）
    if not force and not df_all.empty:
        if str(last_date.date()) in df_all[df_all["status"] == "holding"]["execute_date"].values:
            return False, f"日期 {last_date.date()} 已有执行记录"

    # ── 1. 结算上一轮持仓（用最新收盘价卖出） ──
    closed_count = 0
    if not df_all.empty:
        holding_mask = df_all["status"] == "holding"
        if holding_mask.any():
            prev_date = df_all.loc[holding_mask, "execute_date"].iloc[0]
            for idx in df_all[holding_mask].index:
                stock = df_all.at[idx, "stock"]
                entry_price = df_all.at[idx, "entry_price"]
                if stock in close_panel.columns:
                    exit_price = float(close_panel.loc[last_date, stock])
                    if not pd.isna(exit_price) and exit_price > 0 and not pd.isna(entry_price) and entry_price > 0:
                        ret = round((exit_price / entry_price - 1) * 100, 2)
                        df_all.at[idx, "exit_price"] = round(exit_price, 2)
                        df_all.at[idx, "return_pct"] = ret
                        df_all.at[idx, "status"] = "closed"
                        df_all.at[idx, "exit_date"] = last_date.strftime("%Y-%m-%d")
                        closed_count += 1
            if closed_count > 0:
                # 计算上一轮加权收益
                prev_holding = df_all[df_all["execute_date"] == str(prev_date).split()[0][:10]]
                prev_holding = prev_holding.dropna(subset=["return_pct", "weight"])
                if not prev_holding.empty:
                    prev_weighted = round(
                        (prev_holding["return_pct"] * prev_holding["weight"]).sum() / prev_holding["weight"].sum(), 2
                    )
                else:
                    prev_weighted = 0.0
                print(f"[INVEST] Closed round {prev_date} ({closed_count} stocks), weighted return: {prev_weighted:+.2f}%")

    # ── 2. 建仓新推荐 ──
    n = len(top)
    records = []
    for stock, score in top.items():
        price = close_panel.loc[last_date, stock] if stock in close_panel.columns else float("nan")
        stock_code = f"{int(stock):06d}"
        records.append({
            "execute_date": last_date.strftime("%Y-%m-%d"),
            "stock": stock_code,
            "name": cfg.STOCK_NAMES.get(stock_code, stock_code),
            "score": round(float(score), 4),
            "weight": round(1.0 / n, 4),
            "entry_price": round(float(price), 2),
            "exit_price": None,
            "return_pct": None,
            "status": "holding",
        })

    df_new = pd.DataFrame(records)
    df_all = pd.concat([df_all, df_new], ignore_index=True)
    df_all.to_csv(INVEST_HISTORY_FILE, index=False)

    msg = f"已执行 {n} 只建仓"
    if closed_count > 0:
        msg += f"，上轮已结算({closed_count}只)"
    print(f"[INVEST] {msg}")
    return True, msg


# ---------------------------------------------------------------------------
# 自动交易状态
# ---------------------------------------------------------------------------

def _load_auto_state() -> dict:
    if not os.path.exists(AUTO_STATE_FILE):
        return {"last_trade_date": None, "auto_enabled": cfg.AUTO_TRADE}
    try:
        with open(AUTO_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_trade_date": None, "auto_enabled": cfg.AUTO_TRADE}


def _save_auto_state(state: dict):
    with open(AUTO_STATE_FILE, "w") as f:
        json.dump(state, f)


def _check_and_auto_trade():
    """页面加载后检查调仓周期，到期自动执行交易（仅交易日）"""
    if not cfg.AUTO_TRADE:
        return None
    if not _state.get("loaded"):
        return None

    # 周末不交易
    if datetime.now().weekday() >= 5:
        return None

    state = _load_auto_state()
    if not state.get("auto_enabled", True):
        return None

    close_panel = _state.get("close_panel")
    if close_panel is None or close_panel.empty:
        return None

    latest_data_date = close_panel.index.max()
    last_trade = state.get("last_trade_date")
    if last_trade:
        days_since = (latest_data_date - pd.Timestamp(last_trade)).days
        if days_since < cfg.REBALANCE_FREQUENCY:
            return state  # 未到调仓周期

    # 执行自动交易
    success, msg = _execute_investment(
        _state["composite"], close_panel,
        cfg.MAX_POSITIONS,
    )
    if success:
        state["last_trade_date"] = str(latest_data_date.date())
        _save_auto_state(state)
        print(f"[AUTO] 自动调仓完成: {msg}")
        return state
    return state


def _load_investment_history():
    """加载所有投资历史"""
    if not os.path.exists(INVEST_HISTORY_FILE):
        return pd.DataFrame()
    df = pd.read_csv(INVEST_HISTORY_FILE, parse_dates=["execute_date"], dtype={"stock": str})
    return df.sort_values("execute_date")


def _update_investment_pnl(history_df, data_dict):
    """用最新价格更新每笔投资的 P&L"""
    if history_df.empty or not data_dict:
        return history_df

    for idx, row in history_df.iterrows():
        if row.get("status") == "closed":
            continue  # 已结算的不动
        stock = row["stock"]
        entry_date = pd.Timestamp(row["execute_date"])
        entry_price = row["entry_price"]
        if stock not in data_dict:
            continue
        df = data_dict[stock]
        future = df[df.index > entry_date]
        if future.empty:
            continue
        latest_date = future.index[-1]
        latest_price = float(future.iloc[-1]["close"])
        if pd.isna(latest_price) or latest_price <= 0:
            continue
        ret = (latest_price / entry_price - 1) * 100
        days = (latest_date - entry_date).days
        history_df.at[idx, "exit_price"] = round(latest_price, 2)
        history_df.at[idx, "return_pct"] = round(ret, 2)
        history_df.at[idx, "latest_date"] = latest_date.strftime("%Y-%m-%d")
        history_df.at[idx, "hold_days"] = days
    return history_df


def _build_investment_history_card(history_df):
    """构建投资历史 UI"""
    if history_df.empty:
        return html.Div(
            "暂无模拟投资记录，点击「一键执行本周策略」开始",
            style={"color": "#666", "fontSize": "0.8rem", "textAlign": "center", "padding": "20px"},
        )

    # 按执行日期分组统计
    dates = history_df["execute_date"].unique()
    rounds = []
    for d in sorted(dates, reverse=True):
        subset = history_df[history_df["execute_date"] == d]
        n_stocks = len(subset)
        statuses = subset["status"].unique()
        is_closed = "closed" in statuses and "holding" not in statuses

        # 加权收益（closed的用数据里的return_pct，holding的用_update_investment_pnl算的）
        if subset["return_pct"].notna().any() and subset["weight"].notna().any():
            valid = subset.dropna(subset=["return_pct", "weight"])
            if not valid.empty:
                weighted_ret = round((valid["return_pct"] * valid["weight"]).sum() / valid["weight"].sum(), 2)
            else:
                weighted_ret = None
        else:
            weighted_ret = None

        exit_date = None
        if is_closed and "exit_date" in subset.columns:
            exit_vals = subset["exit_date"].dropna()
            if not exit_vals.empty:
                exit_date = str(exit_vals.iloc[0])[:10]

        rounds.append({
            "date": str(d)[:10],
            "n": n_stocks,
            "weighted_ret": weighted_ret,
            "is_closed": is_closed,
            "exit_date": exit_date,
            "stocks": subset["name"].tolist(),
        })

    # 汇总统计（仅已结算的计入累计）
    closed_rounds = [r for r in rounds if r["is_closed"] and r["weighted_ret"] is not None]
    total_rounds = len(rounds)
    win_rounds = sum(1 for r in closed_rounds if r["weighted_ret"] > 0)
    cum_ret = None
    if closed_rounds:
        cum = 1.0
        for r in closed_rounds:
            cum *= (1 + r["weighted_ret"] / 100)
        cum_ret = round((cum - 1) * 100, 2)

    # 汇总卡片
    stats_cards = dbc.Row([
        dbc.Col(html.Div([
            html.Div("累计模拟收益", style={"color": "#888", "fontSize": "0.7rem"}),
            html.Div(f"{cum_ret:+.2f}%" if cum_ret is not None else "--",
                     style={"fontWeight": "bold", "fontSize": "1.1rem",
                            "color": "#45df7e" if (cum_ret or 0) >= 0 else "#dc3545"}),
        ]), xs=6, sm=4, md=3),
        dbc.Col(html.Div([
            html.Div("已结算/总轮次", style={"color": "#888", "fontSize": "0.7rem"}),
            html.Div(f"{len(closed_rounds)}/{total_rounds}",
                     style={"fontWeight": "bold", "fontSize": "1.1rem", "color": "#ccc"}),
        ]), xs=6, sm=4, md=2),
        dbc.Col(html.Div([
            html.Div("胜率(已结算)", style={"color": "#888", "fontSize": "0.7rem"}),
            html.Div(f"{win_rounds}/{len(closed_rounds)}" if closed_rounds else "--",
                     style={"fontWeight": "bold", "fontSize": "1.1rem", "color": "#ffc107"}),
        ]), xs=6, sm=4, md=2),
        dbc.Col(html.Div([
            html.Div("最佳单轮", style={"color": "#888", "fontSize": "0.7rem"}),
            html.Div(f"{max(r['weighted_ret'] for r in closed_rounds):+.2f}%" if closed_rounds else "--",
                     style={"fontWeight": "bold", "fontSize": "1.1rem", "color": "#45df7e"}),
        ]), xs=6, sm=4, md=2),
        dbc.Col(html.Div([
            html.Div("最差单轮", style={"color": "#888", "fontSize": "0.7rem"}),
            html.Div(f"{min(r['weighted_ret'] for r in closed_rounds):+.2f}%" if closed_rounds else "--",
                     style={"fontWeight": "bold", "fontSize": "1.1rem", "color": "#dc3545"}),
        ]), xs=6, sm=4, md=3),
    ], className="mb-3", style={"gap": "0"})

    # 历史表格
    table_rows = []
    for r in rounds[:30]:
        if r["is_closed"]:
            ret_color = "#45df7e" if (r["weighted_ret"] or 0) > 0 else "#dc3545"
            ret_text = f"{r['weighted_ret']:+.2f}%"
            status_text = f"已结算({r['exit_date']})" if r["exit_date"] else "已结算"
            status_color = "#888"
        else:
            ret_color = "#888"
            ret_text = "持有中..."
            status_text = "持有中"
            status_color = "#ffc107"
        stock_tags = ", ".join(r["stocks"][:4])
        if len(r["stocks"]) > 4:
            stock_tags += f" +{len(r['stocks'])-4}"
        table_rows.append(html.Tr([
            html.Td(r["date"], style={"fontFamily": "monospace", "color": "#aaa", "fontSize": "0.75rem"}),
            html.Td(str(r["n"]), style={"color": "#ccc", "textAlign": "center", "fontSize": "0.75rem"}),
            html.Td(stock_tags, style={"color": "#999", "fontSize": "0.72rem", "maxWidth": "220px",
                                        "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Td(status_text, style={"color": status_color, "fontSize": "0.72rem"}),
            html.Td(ret_text, style={"color": ret_color, "fontWeight": "bold", "fontFamily": "monospace", "fontSize": "0.78rem"}),
        ]))

    table = dbc.Table(
        [html.Thead(html.Tr([
            html.Th("建仓日", style={"color": "#666", "fontSize": "0.7rem"}),
            html.Th("只", style={"color": "#666", "fontSize": "0.7rem", "textAlign": "center"}),
            html.Th("持仓", style={"color": "#666", "fontSize": "0.7rem"}),
            html.Th("状态", style={"color": "#666", "fontSize": "0.7rem"}),
            html.Th("收益", style={"color": "#666", "fontSize": "0.7rem"}),
        ])),
         html.Tbody(table_rows)],
        striped=False, bordered=False, hover=True, size="sm",
        style={"fontSize": "0.78rem", "marginBottom": "0"},
    )

    return html.Div([stats_cards, table])


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
_default_end = max(_cache_end or "", cfg.END_DATE)  # 始终显示最新日期

INPUT_STYLE = {
    "width": "140px", "display": "inline-block",
    "backgroundColor": "#1a1d23", "color": "#ccc",
    "border": "1px solid #2a2d33", "fontSize": "0.82rem",
    "height": "32px",
}

STOCK_OPTIONS = [{"label": s, "value": s} for s in cfg.STOCK_POOL]

app.layout = html.Div(style={"backgroundColor": "#111318", "minHeight": "100vh"}, children=[
    dcc.Location(id="url", refresh=False),
    dcc.Interval(id="auto-load", interval=500, max_intervals=1),

    html.Div(id="login-overlay", style={
        "position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "100%",
        "zIndex": 9999, "backgroundColor": "#111318",
        "display": "flex", "justifyContent": "center", "alignItems": "center", "flexDirection": "column",
    }, children=[
        html.H1("量化多因子策略系统", style={"color": "#45df7e", "fontSize": "1.5rem"}),
        html.P("登录或注册", style={"color": "#777", "fontSize": "0.9rem", "marginBottom": "16px"}),
        dcc.Input(id="login-user", type="text", placeholder="用户名",
                  style={"padding": "8px 14px", "backgroundColor": "#1a1d23", "color": "#ccc",
                         "border": "1px solid #2a2d33", "borderRadius": "4px",
                         "fontSize": "1rem", "width": "200px", "textAlign": "center", "marginBottom": "8px"}),
        dcc.Input(id="login-pw", type="text", placeholder="密码",
                  style={"padding": "8px 14px", "backgroundColor": "#1a1d23", "color": "#ccc",
                         "border": "1px solid #2a2d33", "borderRadius": "4px",
                         "fontSize": "1rem", "width": "200px", "textAlign": "center", "marginBottom": "10px"}),
        html.Div([
            dbc.Button("登录", id="btn-login", color="success", style={"width": "95px", "marginRight": "10px"}),
            dbc.Button("注册", id="btn-register", color="primary", style={"width": "95px"}),
        ]),
        html.Div(id="login-msg", style={"color": "#dc3545", "fontSize": "0.8rem", "marginTop": "8px"}),
    ]),

    # ---- 顶栏 ----
    html.Div([
        html.Div([
            html.Div([
                html.H2("量化多因子策略系统",
                        style={"color": "#45df7e", "margin": "0", "fontSize": "1.4rem"}),
                html.Span(" | 数据: BaoStock  |  日频  |  动量/波动/量价/RSI/布林",
                          style={"color": "#777", "fontSize": "0.8rem", "marginLeft": "8px"}),
            ], style={"display": "flex", "alignItems": "center"}),
        ]),
        html.Div(id="today-indicator", children=_today_label(), style={
            "color": "#ffc107", "fontSize": "0.75rem", "padding": "2px 10px",
            "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33",
            "borderRadius": "4px", "fontFamily": "monospace",
        }),
        html.Span(id="auto-status", style={
            "color": "#45df7e" if cfg.AUTO_TRADE else "#888",
            "fontSize": "0.7rem", "padding": "2px 10px",
            "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33",
            "borderRadius": "4px", "fontFamily": "monospace",
        }),
    ], style={"padding": "14px 16px", "display": "flex", "justifyContent": "space-between",
              "alignItems": "center", "flexWrap": "wrap", "gap": "8px",
              "backgroundColor": "#16191f", "borderBottom": "1px solid #2a2d33"}),

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
                ),
            ], xs=12, sm=12, md=6, lg=4),

            dbc.Col([
                html.Label("回测区间", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                html.Div([
                    dcc.Input(
                        id="start-date", type="text",
                        value=_default_start,
                        placeholder="YYYY-MM-DD",
                        style={**INPUT_STYLE, "width": "100%", "marginRight": "4px"},
                    ),
                    html.Span("~", style={"color": "#666", "margin": "0 4px", "fontSize": "0.85rem"}),
                    dcc.Input(
                        id="end-date", type="text",
                        value=_default_end,
                        placeholder="YYYY-MM-DD",
                        style={**INPUT_STYLE, "width": "100%"},
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(
                    f"缓存范围: {_default_start} ~ {_default_end}",
                    id="cache-range-hint",
                    style={"color": "#555", "fontSize": "0.7rem", "marginTop": "2px"},
                ),
            ], xs=12, sm=6, md=3, lg=3),

            dbc.Col([
                html.Label("最大持仓", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                dcc.Slider(id="max-positions", min=3, max=15, step=1, value=cfg.MAX_POSITIONS,
                           marks={3: "3", 6: "6", 9: "9", 12: "12", 15: "15"}),
            ], xs=6, sm=6, md=3, lg=2),

            dbc.Col([
                html.Label("初始资金(万)", style={"color": "#999", "fontSize": "0.75rem", "marginBottom": "2px"}),
                dcc.Input(id="initial-capital", type="number", value=100,
                          min=10, max=10000, step=10,
                          style={"width": "100%", "maxWidth": "90px", "color": "#ccc", "height": "32px",
                                 "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33"}),
                html.Div([
                    dbc.Button("缓存加载", id="btn-cache", color="info", size="sm", className="me-2 mt-2"),
                    dbc.Button("联网回测", id="btn-full", color="success", size="sm", className="mt-2"),
                ]),
                html.Div([
                    dbc.Button("一键模拟投资", id="btn-execute", color="warning", size="sm",
                               style={"fontWeight": "bold"}, className="mt-1"),
                ]),
            ], xs=6, sm=12, md=12, lg=3),
        ]),
        html.Div(id="status-msg", style={
            "color": "#ffc107", "fontSize": "0.8rem", "marginTop": "8px",
            "minHeight": "20px",
        }),
    ], style={"padding": "14px 16px", "backgroundColor": "#111318", "borderBottom": "1px solid #2a2d33"}),

    # ---- KPI 行 ----
    html.Div(id="kpi-container", children=[
        dbc.Row(id="kpi-row", className="g-2", children=[
            dbc.Col(_kpi_card("累计收益率", "--"), xs=6, sm=4, md=4, lg=2),
            dbc.Col(_kpi_card("年化收益率", "--"), xs=6, sm=4, md=4, lg=2),
            dbc.Col(_kpi_card("夏普比率", "--", "#17a2b8"), xs=6, sm=4, md=4, lg=2),
            dbc.Col(_kpi_card("最大回撤", "--", "#dc3545"), xs=6, sm=4, md=4, lg=2),
            dbc.Col(_kpi_card("胜率", "--", "#ffc107"), xs=6, sm=4, md=4, lg=2),
            dbc.Col(_kpi_card("最终权益", "--"), xs=6, sm=4, md=4, lg=2),
        ]),
    ], style={"padding": "14px 16px"}),

    # ---- 今日操作建议 ----
    html.Div(id="today-plan-container", style={"padding": "0 16px 10px 16px"}),

    # ---- 模拟投资历史 ----
    html.Div(id="invest-history-container", style={"padding": "0 16px 10px 16px"}),

    # ---- 图表区 ----
    dcc.Loading(id="loading-charts", type="default", color="#45df7e", children=[
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(id="equity-chart", style={"height": "380px"},
                    config={"responsive": True}), width=12),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col(dcc.Graph(id="drawdown-chart", style={"height": "260px"},
                    config={"responsive": True}), xs=12, sm=12, md=6),
                dbc.Col(dcc.Graph(id="factor-bar", style={"height": "260px"},
                    config={"responsive": True}), xs=12, sm=12, md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col(dcc.Graph(id="heatmap-chart", style={"height": "300px"},
                    config={"responsive": True}), xs=12, sm=12, md=8),
                dbc.Col(html.Div(id="trade-table", style={
                    "maxHeight": "300px", "overflowY": "auto",
                    "backgroundColor": "#16191f", "padding": "10px", "borderRadius": "6px",
                    "border": "1px solid #2a2d33",
                }), xs=12, sm=12, md=4),
            ]),
        ], style={"padding": "0 16px 28px 16px"}),
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
    [Input("auto-load", "n_intervals"),       # 页面启动自动触发
     Input("btn-cache", "n_clicks"),
     Input("btn-full", "n_clicks"),
     Input("btn-execute", "n_clicks")],
    [State("stock-selector", "value"),
     State("start-date", "value"),
     State("end-date", "value"),
     State("max-positions", "value"),
     State("initial-capital", "value")],
)
def handle_run(n_auto, n_cache, n_full, n_execute, stock_pool, start_date, end_date, max_pos, init_cap):
    """单一回调：运行流水线 + 直接返回所有图表"""
    triggered = callback_context.triggered_id
    print(f"[DEBUG] triggered={triggered}, n_cache={n_cache}, n_full={n_full}")
    print(f"[DEBUG] start={start_date!r}, end={end_date!r}")

    if triggered is None:
        hint_text = f"缓存范围: {_default_start} ~ {_default_end}"
        return f"加载中...", hint_text, *_init_display()

    # 执行投资按钮：需要先确保策略已加载
    if triggered == "btn-execute":
        if not _state.get("loaded") or not _state.get("composite") is not None:
            # 先跑一次流水线
            if not stock_pool:
                empty = _init_display()
                return "⚠ 请选择至少一只股票", dash.no_update, *empty
            init_cap_val = (init_cap or 100) * 10000
            ok = run_pipeline(stock_pool,
                             start_date or cfg.START_DATE,
                             end_date or cfg.END_DATE,
                             max_pos or cfg.MAX_POSITIONS,
                             init_cap_val,
                             use_cache_only=True)
            if not ok:
                empty = _init_display()
                return f"[ERR] {_state['message']}", dash.no_update, *empty
        success, exec_msg = _execute_investment(_state["composite"], _state["close_panel"],
                                                max_pos or cfg.MAX_POSITIONS, force=True)
        # 手动操作后重置自动调仓计时
        if success:
            cp = _state.get("close_panel")
            if cp is not None and not cp.empty:
                auto_state = _load_auto_state()
                auto_state["last_trade_date"] = str(cp.index.max().date())
                _save_auto_state(auto_state)
        return _rebuild_display(exec_msg, use_cache_only=True)

    # auto-load: 页面启动用缓存秒出（首次部署无缓存则空跑，用户点"联网回测"拉数据）
    if triggered == "auto-load":
        use_cache_only = True
    elif triggered == "btn-cache":
        use_cache_only = True
    else:
        use_cache_only = False

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

    # ── 自动交易检查（仅缓存模式，避免联网回测重复触发）──
    if use_cache_only:
        _check_and_auto_trade()

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


# ======== 投资历史 — 常驻回调（页面加载即显示，不依赖回测）========
@app.callback(
    Output("invest-history-container", "children"),
    [Input("url", "pathname"),        # 页面加载触发
     Input("btn-cache", "n_clicks"),  # 回测后也刷新
     Input("btn-full", "n_clicks"),
     Input("btn-execute", "n_clicks")],
)
def load_invest_history(pathname, n_cache, n_full, n_execute):
    """页面加载时自动从磁盘读取投资历史 + 缓存价格计算 P&L"""
    hist_df = _load_investment_history()
    if hist_df.empty:
        return _build_investment_history_card(hist_df)

    # 用缓存数据更新 P&L
    try:
        cache_data = load_from_cache(cfg.STOCK_POOL, cfg.START_DATE, cfg.END_DATE)
        if cache_data:
            hist_df = _update_investment_pnl(hist_df, cache_data)
        # 如果 _state 有更新的数据，用它
        if _state.get("data"):
            hist_df = _update_investment_pnl(hist_df, _state["data"])
    except Exception:
        pass

    return _build_investment_history_card(hist_df)


if __name__ == "__main__":
    app.run(debug=False, port=cfg.DASH_PORT, host="0.0.0.0")


def _rebuild_display(status_msg, use_cache_only=False):
    """仅重建图表（不重跑流水线），用于执行投资按钮"""
    engine = _state.get("engine")
    composite = _state.get("composite")
    close_panel = _state.get("close_panel")

    if engine is None or composite is None or close_panel is None:
        empty = _init_display()
        return "[ERR] 请先加载数据", dash.no_update, *empty

    m = engine.metrics

    # KPI
    kpi = [
        dbc.Col(_kpi_card("累计收益率", m.get("累计收益率", "--")), xs=6, sm=4, md=4, lg=2),
        dbc.Col(_kpi_card("年化收益率", m.get("年化收益率 (CAGR)", "--")), xs=6, sm=4, md=4, lg=2),
        dbc.Col(_kpi_card("夏普比率",   m.get("夏普比率", "--"), "#17a2b8"), xs=6, sm=4, md=4, lg=2),
        dbc.Col(_kpi_card("最大回撤",   m.get("最大回撤", "--"), "#dc3545"), xs=6, sm=4, md=4, lg=2),
        dbc.Col(_kpi_card("胜率",       m.get("胜率", "--"), "#ffc107"), xs=6, sm=4, md=4, lg=2),
        dbc.Col(_kpi_card("最终权益",   m.get("最终权益", "--")), xs=6, sm=4, md=4, lg=2),
    ]

    mode = "缓存" if use_cache_only else "联网"
    msg = (f"[OK] [{mode}] {len(_state['data'])}只 | "
           f"累计收益 {m.get('累计收益率','?')} | {status_msg}")
    hint = f"数据区间: {close_panel.index.min().strftime('%Y-%m-%d')} ~ {close_panel.index.max().strftime('%Y-%m-%d')}"

    _save_recommendation(composite, close_panel, cfg.MAX_POSITIONS)
    prev_recs = _load_prev_recommendation()
    prev_pnl = _calc_recommendation_pnl(prev_recs, _state["data"])
    today_plan = _build_today_plan(composite, close_panel, cfg.MAX_POSITIONS, prev_pnl)

    # 重用现有图表
    pv = engine.portfolio_value.sort_index()
    baseline = pv.values[0] if len(pv) > 0 else 1.0
    norm = pv.values / baseline if baseline != 0 else pv.values
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(x=pv.index, y=norm, mode="lines",
        line=dict(color="#45df7e", width=2), fill="tozeroy",
        fillcolor="rgba(69,223,126,0.08)", name="策略权益", hovertemplate="%{y:.3f}<extra></extra>"))
    fig_eq.add_hline(y=1.0, line_dash="dash", line_color="#555", line_width=1)
    last_val = norm[-1]
    return_pct = (last_val - 1) * 100
    fig_eq.add_annotation(x=pv.index[-1], y=last_val, text=f"{return_pct:+.1f}%  ",
                          showarrow=False, xanchor="right",
                          font=dict(color="#45df7e" if return_pct>=0 else "#dc3545", size=11))
    fig_eq.update_layout(template="plotly_dark", paper_bgcolor="#16191f", plot_bgcolor="#16191f",
                         margin=dict(l=40, r=30, t=30, b=30), xaxis=dict(color="#555"), yaxis=dict(color="#555"),
                         showlegend=False, hovermode="x unified")

    dd_series = engine.get_drawdown_series()
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(x=dd_series.index, y=dd_series.values*100, mode="lines",
        line=dict(color="#dc3545", width=1.5), fill="tozeroy",
        fillcolor="rgba(220,53,69,0.12)", hovertemplate="%{y:.1f}%<extra></extra>"))
    fig_dd.update_layout(template="plotly_dark", paper_bgcolor="#16191f", plot_bgcolor="#16191f",
                         margin=dict(l=40, r=30, t=30, b=30), xaxis=dict(color="#555"), yaxis=dict(color="#555", ticksuffix="%"),
                         showlegend=False, hovermode="x unified")

    pos_df = engine.get_positions_df()
    heatmap_data = (pos_df > 0).astype(int)
    fig_heat = go.Figure(data=go.Heatmap(
        z=heatmap_data.T.values, x=heatmap_data.index, y=heatmap_data.columns,
        colorscale=[[0, "#16191f"], [1, "#45df7e"]], showscale=False,
        hovertemplate="%{x|%Y-%m-%d}<br>%{y}: %{z}<extra></extra>"))
    fig_heat.update_layout(template="plotly_dark", paper_bgcolor="#16191f", plot_bgcolor="#16191f",
                           margin=dict(l=100, r=20, t=30, b=30), xaxis=dict(color="#555"), yaxis=dict(color="#555"))

    latest = composite.iloc[-1].dropna().sort_values()
    colors = ["#45df7e" if v > 0 else "#dc3545" for v in latest.values]
    fig_factor = go.Figure(data=go.Bar(
        x=latest.values, y=latest.index, orientation="h",
        marker_color=colors, text=[f"{v:+.2f}" for v in latest.values],
        textposition="outside", textfont=dict(size=10, color="#ccc")))
    fig_factor.update_layout(template="plotly_dark", paper_bgcolor="#16191f", plot_bgcolor="#16191f",
                             margin=dict(l=100, r=60, t=30, b=30), xaxis=dict(color="#555"), yaxis=dict(color="#555"),
                             showlegend=False)

    trade_log = engine.get_trade_log()
    if not trade_log.empty:
        display_log = trade_log.tail(50).iloc[::-1]
        table = dbc.Table.from_dataframe(display_log, striped=False, bordered=False, hover=True, size="sm",
            style={"fontSize": "0.72rem", "color": "#aaa"})
    else:
        table = html.P("暂无交易记录", style={"color": "#666", "textAlign": "center"})

    return msg, hint, today_plan, kpi, fig_eq, fig_dd, fig_heat, fig_factor, table


# ======== 自动交易状态指示 ========
@app.callback(
    Output("auto-status", "children"),
    Output("auto-status", "style"),
    [Input("url", "pathname"),
     Input("btn-cache", "n_clicks"),
     Input("btn-execute", "n_clicks")],
)
def update_auto_status(pathname, n_cache, n_execute):
    if not cfg.AUTO_TRADE:
        return "自动策略: 仅限本地", {"display": "none", "fontSize": "0.7rem"}
    state = _load_auto_state()
    last = state.get("last_trade_date")
    if last:
        from datetime import date
        days_since = (date.today() - pd.Timestamp(last).date()).days
        next_in = max(0, cfg.REBALANCE_FREQUENCY - days_since)
        return (
            f"自动调仓 | 上次:{last[5:]} | {'今日到期' if next_in==0 else f'{next_in}天后'}",
            {"color": "#45df7e" if next_in == 0 else "#ffc107", "fontSize": "0.7rem",
             "padding": "2px 10px", "backgroundColor": "#1a1d23",
             "border": "1px solid #2a2d33", "borderRadius": "4px", "fontFamily": "monospace"},
        )
    return (
        "自动调仓 | 待首次执行",
        {"color": "#888", "fontSize": "0.7rem", "padding": "2px 10px",
         "backgroundColor": "#1a1d23", "border": "1px solid #2a2d33",
         "borderRadius": "4px", "fontFamily": "monospace"},
    )


# ======== 登录/退出 ========
@app.callback(
    [Output("login-overlay", "style"),
     Output("login-msg", "children")],
    [Input("btn-login", "n_clicks"),
     Input("btn-register", "n_clicks")],
    [State("login-user", "value"),
     State("login-pw", "value")],
)
def handle_auth(n_login, n_register, user, pw):
    ctx = callback_context
    t = ctx.triggered_id
    if t is None:
        return dash.no_update, ""
    if not user or not user.strip():
        return dash.no_update, "请输入用户名"
    if not pw or len(pw) < 4:
        return dash.no_update, "密码至少4位"
    u = user.strip()
    if t == "btn-register" and n_register:
        if db is not None:
            if hasattr(db, 'register_user'):
                if db.user_exists(u):
                    return dash.no_update, "用户已存在"
                db.register_user(u, pw)
                return {"display": "none"}, "注册成功"
            else:
                return dash.no_update, "注册功能不可用"
        return dash.no_update, "数据库不可用"
    if t == "btn-login" and n_login:
        if db is not None:
            if hasattr(db, 'user_exists'):
                if not db.user_exists(u):
                    return dash.no_update, "用户不存在，请先注册"
                if db.verify_login(u, pw):
                    return {"display": "none"}, ""
                return dash.no_update, "密码错误"
            else:
                if db.verify_login("admin", pw):
                    return {"display": "none"}, ""
                return dash.no_update, "密码错误"
        return dash.no_update, "数据库不可用"
    return dash.no_update, ""


@app.callback(
    Output("login-overlay", "style", allow_duplicate=True),
    [Input("btn-logout", "n_clicks")],
    prevent_initial_call=True,
)
def handle_logout(n):
    return {
        "position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "100%",
        "zIndex": 9999, "backgroundColor": "#111318",
        "display": "flex", "justifyContent": "center", "alignItems": "center", "flexDirection": "column",
    }
