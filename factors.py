"""
因子计算引擎 - 多因子指标计算 (纯 pandas 实现)
"""

import pandas as pd
import numpy as np


def compute_momentum(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """动量因子: N日收益率"""
    return close.pct_change(lookback)


def compute_volatility(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """波动率因子: N日年化波动率"""
    returns = close.pct_change()
    return returns.rolling(lookback).std() * np.sqrt(252)


def compute_volume_ratio(volume: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """量比因子: 当日成交量 / N日均量"""
    ma_volume = volume.rolling(lookback).mean()
    return volume / ma_volume


def compute_rsi(close: pd.DataFrame, lookback: int = 14) -> pd.DataFrame:
    """RSI 指标"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(lookback).mean()
    avg_loss = loss.rolling(lookback).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ma_deviation(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """均线偏离: (收盘价 - MA) / MA"""
    ma = close.rolling(lookback).mean()
    return (close - ma) / ma


def compute_bollinger_position(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """布林带位置: (close - lower) / (upper - lower)"""
    ma = close.rolling(lookback).mean()
    std = close.rolling(lookback).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    band_range = upper - lower
    return (close - lower) / band_range.replace(0, np.nan)


def compute_macd(close: pd.DataFrame, fast=12, slow=26, signal=9) -> dict:
    """MACD 指标，返回 {dif, dea, histogram}"""
    ema_fast = close.apply(lambda x: x.ewm(span=fast, adjust=False).mean())
    ema_slow = close.apply(lambda x: x.ewm(span=slow, adjust=False).mean())
    dif = ema_fast - ema_slow
    dea = dif.apply(lambda x: x.ewm(span=signal, adjust=False).mean())
    histogram = 2 * (dif - dea)
    return {"dif": dif, "dea": dea, "macd_hist": histogram}


def compute_all_factors(data_dict: dict, factor_config: dict = None) -> dict:
    """批量计算全部因子，返回 {factor_name: DataFrame}"""
    import config as cfg

    if factor_config is None:
        factor_config = cfg.FACTOR_CONFIG

    close_panel = pd.DataFrame({s: df["close"] for s, df in data_dict.items()})
    volume_panel = pd.DataFrame({s: df["volume"] for s, df in data_dict.items()})

    factors = {}

    for name, params in factor_config.items():
        ftype = params["type"]
        lb = params.get("lookback", 20)

        if ftype == "momentum":
            factors[name] = compute_momentum(close_panel, lb)
        elif ftype == "volatility":
            factors[name] = compute_volatility(close_panel, lb)
        elif ftype == "volume":
            factors[name] = compute_volume_ratio(volume_panel, lb)
        elif ftype == "rsi":
            factors[name] = compute_rsi(close_panel, lb)
        elif ftype == "ma_deviation":
            factors[name] = compute_ma_deviation(close_panel, lb)
        elif ftype == "bollinger":
            factors[name] = compute_bollinger_position(close_panel, lb)

    return factors


def get_factor_names() -> list:
    import config as cfg

    return list(cfg.FACTOR_CONFIG.keys())
