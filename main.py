"""
量化多因子策略系统 - 入口
启动方式: python main.py
然后在浏览器打开 http://localhost:8050
"""

import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════╗
    ║       量化多因子策略回测系统 v1.0            ║
    ║                                              ║
    ║  数据源: AKShare (东方财富)                  ║
    ║  频率: 日频                                 ║
    ║  因子: 动量/波动/量价/RSI/布林               ║
    ║                                              ║
    ║  启动地址: http://localhost:8050             ║
    ║  按 Ctrl+C 停止                              ║
    ╚══════════════════════════════════════════════╝
    """)

    from dashboard import app
    app.run(debug=False, port=8050, host="0.0.0.0")
