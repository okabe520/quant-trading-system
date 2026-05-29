"""
多因子策略模块 - 因子合成、信号生成、权重分配
"""

import pandas as pd
import numpy as np

import config as cfg


def zscore_cross_section(series: pd.Series) -> pd.Series:
    """截面 Z-Score 标准化"""
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def normalize_factors(factor_dict: dict, min_periods: int = 60) -> pd.DataFrame:
    """
    将所有因子截面标准化后合成
    返回: composite_score DataFrame (行=日期, 列=股票)
    """
    weights = cfg.FACTOR_WEIGHTS
    composite = None
    count = 0

    for name, factor_df in factor_dict.items():
        if name not in weights:
            continue
        w = weights[name]
        if w == 0:
            continue

        # 截面标准化
        normalized = factor_df.apply(zscore_cross_section, axis=1)
        normalized = normalized.clip(-3, 3)

        if composite is None:
            composite = normalized * w
        else:
            composite = composite.add(normalized * w, fill_value=0)
        count += 1

    if composite is None:
        raise ValueError("没有有效的因子用于合成")

    return composite


def generate_signals(
    composite_score: pd.DataFrame,
    max_positions: int = None,
    threshold: float = None,
) -> pd.DataFrame:
    """
    根据综合得分生成交易信号
    返回: signal_df (行=日期, 列=股票) — 1=买入/持有, 0=空仓, -1=卖出
    """
    if max_positions is None:
        max_positions = cfg.MAX_POSITIONS
    if threshold is None:
        threshold = cfg.MIN_SIGNAL_THRESHOLD

    signals = pd.DataFrame(0, index=composite_score.index, columns=composite_score.columns)

    for date in composite_score.index:
        row = composite_score.loc[date].dropna()
        if row.empty:
            continue

        # 选出得分最高的 N 只且得分 > threshold
        top_stocks = row[row > threshold].nlargest(max_positions)
        signals.loc[date, top_stocks.index] = 1

    return signals


def get_target_weights(signals: pd.DataFrame) -> pd.DataFrame:
    """
    从信号生成目标权重 (等权配置)
    返回: weights (日期 x 股票), 每行之和 <= 1
    """
    weights = pd.DataFrame(0.0, index=signals.index, columns=signals.columns)
    for date in signals.index:
        long_stocks = signals.loc[date][signals.loc[date] == 1].index.tolist()
        if long_stocks:
            w = 1.0 / len(long_stocks)
            weights.loc[date, long_stocks] = w
    return weights
