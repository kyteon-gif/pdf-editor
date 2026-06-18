"""conftest.py — pytest 根設定，確保 Windows/Linux 路徑一致。"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# 插到最前面，確保根目錄的 config.py 優先被找到
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
