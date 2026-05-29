"""
回测引擎 - 日频模拟交易，含手续费、滑点、印花税
"""

import pandas as pd
import numpy as np

import config as cfg


class BacktestEngine:
    """日频回测引擎"""

    def __init__(
        self,
        close_panel: pd.DataFrame,
        target_weights: pd.DataFrame,
        initial_capital: float = None,
        commission: float = None,
        slippage: float = None,
        stamp_tax: float = None,
    ):
        self.close = close_panel
        self.target_weights = target_weights
        self.initial_capital = initial_capital or cfg.INITIAL_CAPITAL
        self.commission = commission or cfg.COMMISSION_RATE
        self.slippage = slippage or cfg.SLIPPAGE
        self.stamp_tax = stamp_tax or cfg.STAMP_TAX

        self.dates = sorted(
            set(close_panel.index) & set(target_weights.index)
        )
        self.stocks = sorted(
            set(close_panel.columns) & set(target_weights.columns)
        )

        # 结果存储
        self.positions = None  # 每日持仓 (股数)
        self.cash = None
        self.portfolio_value = None
        self.daily_returns = None
        self.trade_log = []
        self.metrics = {}

    def run(self) -> dict:
        """执行回测"""
        if len(self.dates) < 2:
            print("回测日期不足")
            return {}

        n_dates = len(self.dates)
        n_stocks = len(self.stocks)

        positions = pd.DataFrame(0.0, index=self.dates, columns=self.stocks)
        cash_series = pd.Series(self.initial_capital, index=self.dates, dtype=float)
        portfolio = pd.Series(self.initial_capital, index=self.dates, dtype=float)

        current_positions = {s: 0.0 for s in self.stocks}
        current_cash = self.initial_capital

        prev_date = self.dates[0]
        prices_init = self.close.loc[prev_date]
        portfolio.iloc[0] = self.initial_capital

        for i, stock in enumerate(self.stocks):
            positions.iloc[0, i] = 0.0

        # 逐日模拟
        for t in range(1, n_dates):
            date = self.dates[t]
            prev = self.dates[t - 1]

            prices_today = self.close.loc[date]
            prices_prev = self.close.loc[prev]

            # 先按今日价格估值昨日持仓
            equity_value = 0.0
            for stock in self.stocks:
                if current_positions[stock] > 0:
                    price = prices_today.get(stock, prices_prev.get(stock, 0))
                    if pd.notna(price) and price > 0:
                        equity_value += current_positions[stock] * price

            portfolio_value_before = current_cash + equity_value

            # 获取今日目标权重
            tw = self.target_weights.loc[date] if date in self.target_weights.index else None
            if tw is not None:
                target_w = {s: tw.get(s, 0) for s in self.stocks if pd.notna(tw.get(s, 0)) and tw[s] > 0}
            else:
                target_w = {}

            # 调仓
            if target_w:
                total_value = portfolio_value_before
                target_value = {}
                for stock, w in target_w.items():
                    price = prices_today.get(stock)
                    if pd.notna(price) and price > 0:
                        target_value[stock] = total_value * w

                # 先卖后买
                for stock in self.stocks:
                    price = prices_today.get(stock)
                    if pd.isna(price) or price <= 0:
                        continue
                    target_v = target_value.get(stock, 0)
                    current_v = current_positions[stock] * price
                    diff_v = target_v - current_v

                    if diff_v < -1:  # 卖出
                        sell_shares = abs(diff_v) / price
                        sell_shares = int(sell_shares / 100) * 100  # 整手
                        if sell_shares > 0:
                            sell_amount = sell_shares * price * (1 - self.slippage)
                            cost = sell_amount * (self.commission + self.stamp_tax)
                            current_cash += sell_amount - cost
                            current_positions[stock] -= sell_shares
                            self.trade_log.append({
                                "date": date, "stock": stock, "action": "SELL",
                                "shares": sell_shares, "price": price,
                                "amount": sell_amount, "cost": cost,
                            })

                # 买入
                for stock, target_v in target_value.items():
                    price = prices_today.get(stock)
                    if pd.isna(price) or price <= 0:
                        continue
                    current_v = current_positions[stock] * price
                    diff_v = target_v - current_v

                    if diff_v > 1:  # 买入
                        buy_amount = min(diff_v, current_cash * 0.99)
                        buy_shares = buy_amount / (price * (1 + self.slippage))
                        buy_shares = int(buy_shares / 100) * 100
                        if buy_shares > 0:
                            buy_cost = buy_shares * price * (1 + self.slippage)
                            commission_cost = buy_cost * self.commission
                            total_cost = buy_cost + commission_cost
                            if total_cost <= current_cash:
                                current_cash -= total_cost
                                current_positions[stock] += buy_shares
                                self.trade_log.append({
                                    "date": date, "stock": stock, "action": "BUY",
                                    "shares": buy_shares, "price": price,
                                    "amount": buy_cost, "cost": commission_cost,
                                })

            # 记录持仓
            for stock in self.stocks:
                positions.loc[date, stock] = current_positions[stock]

            # 市值
            equity_value = 0.0
            for stock in self.stocks:
                if current_positions[stock] > 0:
                    price = prices_today.get(stock)
                    if pd.notna(price) and price > 0:
                        equity_value += current_positions[stock] * price

            cash_series.iloc[t] = current_cash
            portfolio.iloc[t] = current_cash + equity_value

        # 保存结果
        self.positions = positions
        self.cash = cash_series
        self.portfolio_value = portfolio
        self.daily_returns = portfolio.pct_change().fillna(0)
        self.metrics = self._calculate_metrics()

        return self.metrics

    def _calculate_metrics(self) -> dict:
        """计算绩效指标"""
        pv = self.portfolio_value
        rets = self.daily_returns

        if pv is None or len(pv) < 2:
            return {}

        total_return = (pv.iloc[-1] / pv.iloc[0] - 1)
        n_years = (pv.index[-1] - pv.index[0]).days / 365.25
        cagr = (1 + total_return) ** (1 / max(n_years, 0.08)) - 1

        # 年化波动率 (假设252交易日)
        ann_vol = rets.std() * np.sqrt(252)

        # 夏普比率 (无风险利率设为2%)
        sharpe = (cagr - 0.02) / ann_vol if ann_vol > 0 else 0

        # 最大回撤
        cumulative = (1 + rets).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min()

        # 胜率
        win_rate = (rets > 0).sum() / max(len(rets[rets != 0]), 1)

        # 盈亏比
        avg_win = rets[rets > 0].mean() if (rets > 0).any() else 0
        avg_loss = abs(rets[rets < 0].mean()) if (rets < 0).any() else 0.001
        profit_loss_ratio = avg_win / avg_loss

        # 卡尔玛比率
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0

        # 换手率统计
        trades = pd.DataFrame(self.trade_log) if self.trade_log else pd.DataFrame()
        if not trades.empty:
            buy_trades = trades[trades["action"] == "BUY"]
            daily_turnover = buy_trades.groupby("date")["amount"].sum()
            avg_daily_turnover = daily_turnover.mean() if len(daily_turnover) > 0 else 0
            total_trade_count = len(trades)
        else:
            avg_daily_turnover = 0
            total_trade_count = 0

        return {
            "累计收益率": f"{total_return:.2%}",
            "年化收益率 (CAGR)": f"{cagr:.2%}",
            "年化波动率": f"{ann_vol:.2%}",
            "夏普比率": f"{sharpe:.2f}",
            "最大回撤": f"{max_dd:.2%}",
            "胜率": f"{win_rate:.2%}",
            "盈亏比": f"{profit_loss_ratio:.2f}",
            "卡尔玛比率": f"{calmar:.2f}",
            "总交易笔数": total_trade_count,
            "日均换手额": f"¥{avg_daily_turnover:,.0f}",
            "回测天数": len(pv),
            "初始资金": f"¥{self.initial_capital:,.0f}",
            "最终权益": f"¥{pv.iloc[-1]:,.2f}",
        }

    def get_equity_curve(self) -> pd.Series:
        return self.portfolio_value

    def get_drawdown_series(self) -> pd.Series:
        if self.portfolio_value is None:
            return pd.Series()
        cumulative = (1 + self.daily_returns).cumprod()
        running_max = cumulative.cummax()
        return (cumulative - running_max) / running_max

    def get_positions_df(self) -> pd.DataFrame:
        return self.positions

    def get_trade_log(self) -> pd.DataFrame:
        return pd.DataFrame(self.trade_log)
