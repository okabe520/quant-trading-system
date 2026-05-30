"""Render 部署入口 — gunicorn 通过 wsgi:server 启动"""
import sys
import os
import traceback

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=== Starting quant-trading-system ===", flush=True)

# 诊断导入
for mod in ["pandas", "numpy", "plotly", "dash", "dash_bootstrap_components", "baostock", "akshare"]:
    try:
        __import__(mod)
        print(f"  [OK] {mod}", flush=True)
    except Exception as e:
        print(f"  [MISS] {mod}: {e}", flush=True)

try:
    from dashboard import app
    print("  [OK] dashboard imported", flush=True)
except Exception as e:
    traceback.print_exc()
    print(f"  [FAIL] dashboard import: {e}", flush=True)
    raise

server = app.server

# 诊断端点 — 检查数据源状态（before_request 避免 Dash catchall 拦截）
@server.before_request
def diag_check():
    from flask import request
    if request.path == "/diag":
        import config as cfg
        import json as _json
        result = {"data_source": cfg.DATA_SOURCE}
        try:
            import yfinance as yf
            result["yfinance_version"] = yf.__version__
            tickers = yf.download("000001.SZ 600519.SS", period="5d", progress=False, auto_adjust=False)
            result["yf_test"] = f"{len(tickers)} rows" if not tickers.empty else "EMPTY"
        except Exception as e:
            result["yf_error"] = str(e)
        return _json.dumps(result, indent=2, ensure_ascii=False), 200, {"Content-Type": "application/json"}

print("=== Ready ===", flush=True)
