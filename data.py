"""
数据获取模块 - BaoStock 批量查询 + AKShare 备用，CSV 缓存加速
"""

import os
import time
import pandas as pd
import numpy as np

import config as cfg

try:
    import yfinance as yf
except ImportError:
    yf = None


def _ensure_cache_dir():
    os.makedirs(cfg.CACHE_DIR, exist_ok=True)


def _to_bs_code(symbol: str) -> str:
    if symbol.startswith("6") or symbol.startswith("68"):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def _to_yf_code(symbol: str) -> str:
    """6 开头→上海 .SS，其余→深圳 .SZ"""
    if symbol.startswith("6") or symbol.startswith("68"):
        return f"{symbol}.SS"
    return f"{symbol}.SZ"


def _cache_hit(cache_path: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """缓存与请求区间有重叠即返回可用的交叉区间"""
    if not os.path.exists(cache_path):
        return None
    df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
    if df.empty:
        return None
    req_start = pd.Timestamp(start_date)
    req_end = pd.Timestamp(end_date)
    cache_start = df.index.min()
    cache_end = df.index.max()

    # 缓存与请求区间无交集
    if cache_end < req_start or cache_start > req_end:
        return None
    # 返回可用的重叠区间
    actual_start = max(cache_start, req_start)
    actual_end = min(cache_end, req_end)
    return df.loc[actual_start:actual_end]


# ---------------------------------------------------------------------------
# 快速加载：仅用缓存，不联网
# ---------------------------------------------------------------------------
def load_from_cache(pool: list, start_date: str, end_date: str) -> dict:
    """只读缓存，毫秒级加载"""
    _ensure_cache_dir()
    result = {}
    for sym in pool:
        df = _cache_hit(os.path.join(cfg.CACHE_DIR, f"{sym}.csv"), start_date, end_date)
        if df is not None:
            result[sym] = df
    return result


# ---------------------------------------------------------------------------
# 全量加载：缓存命中跳过，缺失的批量从 BaoStock 拉取
# ---------------------------------------------------------------------------
def fetch_stock_pool(pool: list = None, start_date: str = None, end_date: str = None,
                     use_cache_only: bool = False) -> dict:
    """
    获取股票池数据。
    use_cache_only=True: 仅读缓存，不联网（毫秒级）
    use_cache_only=False: 缓存命中跳过，缺失的批量联网拉取
    """
    if pool is None:
        pool = cfg.STOCK_POOL
    if start_date is None:
        start_date = cfg.START_DATE
    if end_date is None:
        end_date = cfg.END_DATE

    _ensure_cache_dir()

    # 1) 先扫一遍缓存
    result = {}
    need_fetch = []
    for sym in pool:
        cp = os.path.join(cfg.CACHE_DIR, f"{sym}.csv")
        df = _cache_hit(cp, start_date, end_date)
        if df is not None:
            result[sym] = df
        else:
            need_fetch.append(sym)

    if not need_fetch:
        print(f"  [缓存] {len(result)} 只股票全部命中，秒级加载完成")
        return result

    if use_cache_only:
        print(f"  [仅缓存] {len(result)}/{len(pool)} 只命中")
        return result

    print(f"  缓存命中 {len(result)}, 需联网拉取 {len(need_fetch)}")

    # ── 海外数据源：直接走 yfinance ──
    if cfg.DATA_SOURCE == "overseas":
        _fetch_via_yfinance(need_fetch, start_date, end_date, result)
        print(f"  最终: {len(result)}/{len(pool)} 只可用\n")
        return result

    # 2) 一次 login，批量拉取所有缺失股票
    import baostock as bs
    bs.login()

    fields = "date,open,high,low,close,volume,amount,turn,pctChg"
    for sym in need_fetch:
        cp = os.path.join(cfg.CACHE_DIR, f"{sym}.csv")
        bs_code = _to_bs_code(sym)

        rs = bs.query_history_k_data_plus(
            bs_code, fields, start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2",
        )
        if rs is not None and rs.error_code == "0":
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if rows:
                df = pd.DataFrame(rows, columns=fields.split(","))
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                for c in ["open","high","low","close","volume","amount","turn","pctChg"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df.rename(columns={"pctChg": "pct_change", "turn": "turnover"}, inplace=True)
                df["turnover"] /= 100.0
                df.sort_index(inplace=True)
                df.to_csv(cp)
                result[sym] = df
                print(f"    [OK] {sym}: {len(df)} 条")
            else:
                print(f"    [空] {sym}")
        else:
            msg = rs.error_msg if rs else "返回 None"
            print(f"    [失败] {sym}: {msg}")

    bs.logout()

    # 3) 对仍然缺失的，尝试 AKShare
    still_missing = [s for s in need_fetch if s not in result]
    if still_missing:
        _fetch_via_akshare(still_missing, start_date, end_date, result)

    print(f"  最终: {len(result)}/{len(pool)} 只可用\n")
    return result


def _fetch_via_akshare(symbols: list, start_date: str, end_date: str, result: dict):
    """AKShare 备用源"""
    try:
        import akshare as ak
        for sym in symbols:
            try:
                raw = ak.stock_zh_a_hist(
                    symbol=sym, period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )
                if raw is not None and not raw.empty:
                    df = pd.DataFrame()
                    df["open"] = raw["开盘"].astype(float)
                    df["high"] = raw["最高"].astype(float)
                    df["low"] = raw["最低"].astype(float)
                    df["close"] = raw["收盘"].astype(float)
                    df["volume"] = raw["成交量"].astype(float)
                    df["amount"] = raw["成交额"].astype(float)
                    df["pct_change"] = raw["涨跌幅"].astype(float)
                    df["turnover"] = raw["换手率"].astype(float)
                    df.index = pd.to_datetime(raw["日期"])
                    df.sort_index(inplace=True)
                    cp = os.path.join(cfg.CACHE_DIR, f"{sym}.csv")
                    df.to_csv(cp)
                    result[sym] = df
                    print(f"    [AK OK] {sym}: {len(df)} 条")
                time.sleep(0.5)
            except Exception:
                pass
    except Exception:
        pass


def _fetch_via_yfinance(symbols: list, start_date: str, end_date: str, result: dict):
    """yfinance 海外数据源 — 批量下载，字段映射到统一格式"""
    if yf is None:
        print("    [yfinance] not installed")
        return

    yf_codes = [_to_yf_code(s) for s in symbols]
    tickers = yf.download(yf_codes, start=start_date, end=end_date, progress=False, auto_adjust=False)

    if tickers.empty:
        print("    [yfinance] 返回空数据")
        return

    for sym, yf_code in zip(symbols, yf_codes):
        try:
            if len(yf_codes) == 1:
                df_raw = tickers.copy()
            else:
                df_raw = tickers.xs(yf_code, axis=1, level=1).copy()

            if df_raw.empty:
                print(f"    [yf] {sym}: 无数据")
                continue

            df = pd.DataFrame()
            df["open"] = df_raw["Open"]
            df["high"] = df_raw["High"]
            df["low"] = df_raw["Low"]
            df["close"] = df_raw["Close"]
            df["volume"] = df_raw["Volume"]
            df["amount"] = df["close"] * df["volume"]
            df["pct_change"] = df["close"].pct_change() * 100
            df["turnover"] = np.nan
            df.index = pd.to_datetime(df_raw.index)
            df.sort_index(inplace=True)

            cp = os.path.join(cfg.CACHE_DIR, f"{sym}.csv")
            df.to_csv(cp)
            result[sym] = df
            print(f"    [yf OK] {sym}: {len(df)} 条")
        except Exception as e:
            print(f"    [yf] {sym}: {e}")


def get_trading_dates(data_dict: dict) -> pd.DatetimeIndex:
    if not data_dict:
        return pd.DatetimeIndex([])
    dates = list(data_dict.values())[0].index
    for df in data_dict.values():
        dates = dates.intersection(df.index)
    return dates.sort_values()


def build_panel(data_dict: dict, field: str = "close") -> pd.DataFrame:
    series = {s: df[field] for s, df in data_dict.items() if field in df.columns}
    panel = pd.DataFrame(series)
    return panel.dropna(how="all")
