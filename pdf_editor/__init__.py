"""
app/__init__.py — Flask application factory

修正：
- config 改用 sys.path 安全的方式 import，相容 Windows pytest
- Blueprint 與 ModelRegistry 改在 create_app() 內部 import，
  避免模組循環與路徑問題
"""

import sys
from pathlib import Path

# 確保專案根目錄在 sys.path（Windows pytest 有時不會自動加入）
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask


def create_app() -> Flask:
    # 延遲 import config，確保 sys.path 已修正
    from config import SECRET_KEY, MAX_CONTENT_LENGTH, UPLOAD_DIR

    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── 基本設定 ──────────────────────────────────────────────
    app.config["SECRET_KEY"]          = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"]  = MAX_CONTENT_LENGTH
    app.config["UPLOAD_FOLDER"]       = str(UPLOAD_DIR)

    # ── 註冊藍圖 ──────────────────────────────────────────────
    from pdf_editor.routes.health import health_bp
    from pdf_editor.routes.upload import upload_bp
    from pdf_editor.routes.editor import editor_bp
    from pdf_editor.routes.image import image_bp
    from pdf_editor.routes.export import export_bp
    app.register_blueprint(health_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(export_bp)

    # ── 啟動時初始化模型 Registry ─────────────────────────────
    from pdf_editor.services.model_registry import ModelRegistry
    ModelRegistry.ensure_all()

    return app
