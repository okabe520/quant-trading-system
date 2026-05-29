"""
量化因子策略系统 - 配置文件
"""

# ============ 股票池 ============
STOCK_POOL = [
    "000001",  # 平安银行
    "000002",  # 万科A
    "000858",  # 五粮液
    "002415",  # 海康威视
    "300750",  # 宁德时代
    "600000",  # 浦发银行
    "600036",  # 招商银行
    "600276",  # 恒瑞医药
    "600519",  # 贵州茅台
    "600585",  # 海螺水泥
    "600887",  # 伊利股份
    "601318",  # 中国平安
    "000333",  # 美的集团
    "000651",  # 格力电器
    "002594",  # 比亚迪
    "300059",  # 东方财富
    "600900",  # 长江电力
    "601166",  # 兴业银行
    "600809",  # 山西汾酒
    "603259",  # 药明康德
]

BENCHMARK = "000300"  # 沪深300

STOCK_NAMES = {
    "000001": "平安银行", "000002": "万科A", "000858": "五粮液",
    "002415": "海康威视", "300750": "宁德时代", "600000": "浦发银行",
    "600036": "招商银行", "600276": "恒瑞医药", "600519": "贵州茅台",
    "600585": "海螺水泥", "600887": "伊利股份", "601318": "中国平安",
    "000333": "美的集团", "000651": "格力电器", "002594": "比亚迪",
    "300059": "东方财富", "600900": "长江电力", "601166": "兴业银行",
    "600809": "山西汾酒", "603259": "药明康德",
}

# ============ 数据 ============
START_DATE = "2023-01-01"
END_DATE = "2026-05-28"
CACHE_DIR = "E:/quant_trading_system/cache"

# ============ 因子参数 ============
FACTOR_CONFIG = {
    "momentum_5": {"lookback": 5, "type": "momentum"},
    "momentum_10": {"lookback": 10, "type": "momentum"},
    "momentum_20": {"lookback": 20, "type": "momentum"},
    "volatility_10": {"lookback": 10, "type": "volatility"},
    "volatility_20": {"lookback": 20, "type": "volatility"},
    "volume_ratio_5": {"lookback": 5, "type": "volume"},
    "volume_ratio_20": {"lookback": 20, "type": "volume"},
    "rsi_14": {"lookback": 14, "type": "rsi"},
    "ma_deviation_20": {"lookback": 20, "type": "ma_deviation"},
    "bb_position": {"lookback": 20, "type": "bollinger"},
}

# 因子权重 (总和为1)
FACTOR_WEIGHTS = {
    "momentum_5": 0.10,
    "momentum_10": 0.10,
    "momentum_20": 0.15,
    "volatility_10": -0.10,  # 低波动溢价
    "volatility_20": -0.05,
    "volume_ratio_5": 0.10,
    "volume_ratio_20": 0.05,
    "rsi_14": 0.10,
    "ma_deviation_20": 0.10,
    "bb_position": 0.15,
}

# ============ 策略参数 ============
MAX_POSITIONS = 8  # 最大持仓数
MIN_SIGNAL_THRESHOLD = 0.0  # 最低信号阈值

# ============ 回测参数 ============
INITIAL_CAPITAL = 1_000_000  # 初始资金
COMMISSION_RATE = 0.0003  # 手续费 万三
SLIPPAGE = 0.0001  # 滑点
STAMP_TAX = 0.001  # 印花税 (仅卖出)

# ============ GUI ============
DASH_PORT = 8050
THEME = "darkly"  # dash-bootstrap-components 主题
