"""
tests/test_unit1_startup.py
Unit 1：確認 Flask 可以啟動，/api/health 回傳正確結構。

執行（在專案根目錄）：
    pytest tests/test_unit1_startup.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 強制推到最前面，蓋過環境裡已安裝的同名套件


# 確保專案根目錄在 sys.path 最前面（macOS/miniforge 防禦）
import pytest
from pdf_editor import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_status_ok(client):
    """健康檢查回傳 HTTP 200 且 status == ok。"""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"


def test_health_has_models_key(client):
    """回應中包含 models 欄位。"""
    r = client.get("/api/health")
    data = r.get_json()
    assert "models" in data


def test_health_models_schema(client):
    """每個模型條目都有必要欄位且型別正確。"""
    r = client.get("/api/health")
    data = r.get_json()
    required_fields = {"ready", "path", "required", "license", "size_gb"}
    for name, info in data["models"].items():
        missing = required_fields - set(info.keys())
        assert not missing, f"{name} 缺少欄位: {missing}"
