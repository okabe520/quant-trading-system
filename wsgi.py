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
print("=== Ready ===", flush=True)
