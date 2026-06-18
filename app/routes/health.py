"""
routes/health.py — 健康檢查端點
用途：確認 Flask 啟動正常、模型狀態可查詢。
"""

from flask import Blueprint, jsonify
from app.services.model_registry import ModelRegistry

health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health():
    """回傳服務狀態與各模型載入情況。"""
    return jsonify({
        "status": "ok",
        "models": ModelRegistry.status(),
    })
