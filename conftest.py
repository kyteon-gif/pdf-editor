"""
conftest.py

解決 macOS/miniforge 環境下 'app' 被已安裝套件遮蔽的問題。
--import-mode=importlib 搭配此檔可完全避開衝突。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# 強制把專案根目錄推到 sys.path 第一位
# 並移除任何指向已安裝 'app' 套件的路徑
sys.path = [str(ROOT)] + [
    p for p in sys.path
    if p != str(ROOT) and "app" not in Path(p).parts
]
