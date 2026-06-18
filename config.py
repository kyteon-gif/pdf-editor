"""
config.py — 全域設定
所有路徑、模型 ID、服務參數集中在此，其他模組從這裡 import。
"""

import os
import sys
from pathlib import Path

# ── 根目錄（以 config.py 所在位置為準，相容 Windows）────────
BASE_DIR = Path(__file__).parent.resolve()

# 確保根目錄在 sys.path
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── 資料目錄 ─────────────────────────────────────────────────
UPLOAD_DIR    = BASE_DIR / "uploads"
EXPORT_DIR    = BASE_DIR / "exports"
CACHE_DIR     = BASE_DIR / "file_caches"
SNAPSHOT_DIR  = BASE_DIR / "snapshots"
MODEL_DIR     = BASE_DIR / "models"

# 確保目錄存在
for _d in (UPLOAD_DIR, EXPORT_DIR, CACHE_DIR, SNAPSHOT_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Flask ─────────────────────────────────────────────────────
SECRET_KEY         = os.getenv("SECRET_KEY", "dev-secret-change-me")
MAX_CONTENT_MB     = int(os.getenv("MAX_CONTENT_MB", "50"))
MAX_CONTENT_LENGTH = MAX_CONTENT_MB * 1024 * 1024

# ── 模型清單（ModelRegistry 使用）────────────────────────────
MODEL_MANIFEST = {
    "multilingual-e5-large-instruct": {
        "hf_id":      "intfloat/multilingual-e5-large-instruct",
        "local_dir":  MODEL_DIR / "multilingual-e5-large-instruct",
        "size_gb":    1.12,
        "license":    "MIT",
        "required":   True,
        "validate_files": [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "model.safetensors",
        ],
    },
    "layoutlmv3-base": {
        "hf_id":      "microsoft/layoutlmv3-base",
        "local_dir":  MODEL_DIR / "layoutlmv3-base",
        "size_gb":    0.50,
        "license":    "CC-BY-NC-SA-4.0",
        "required":   False,
        "validate_files": [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "model.safetensors",
        ],
    },
}

# ── 解析參數 ──────────────────────────────────────────────────
CLASSIFIER_THRESHOLD = float(os.getenv("CLASSIFIER_THRESHOLD", "0.45"))

# 允許上傳的副檔名
ALLOWED_EXTENSIONS = {"pdf"}
