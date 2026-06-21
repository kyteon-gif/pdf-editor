"""
tests/test_unit5_editor_validation.py
Unit 5 — routes/editor 與 validator 整合：
PATCH 表格區塊後，回應應附帶 validation 結果。

執行：
    pytest tests/test_unit5_editor_validation.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from pdf_editor import create_app
from pdf_editor.services.cache_manager import CacheManager


FAKE_DOC_ID = "5" * 64


def _fake_parsed(doc_id=FAKE_DOC_ID) -> dict:
    return {
        "doc_id": doc_id, "filename": "sample.pdf", "page_count": 1,
        "texts": {
            "txt-001": {
                "id": "txt-001", "type": "body", "page": 1,
                "bbox": [72, 100, 500, 120], "content": "內文",
                "font_size": 11.0, "font_name": "Arial",
            },
        },
        "tables": {
            "tbl-001": {
                "id": "tbl-001", "type": "table", "page": 1,
                "bbox": [72, 200, 500, 300],
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板", "1200", "10", "12000"],
                ],
                "linked_overview_block": "tbl-overview",
                "linked_overview_cell":  "B2",
                "total": 12000.0,
            },
            "tbl-overview": {
                "id": "tbl-overview", "type": "overview", "page": 1,
                "bbox": [72, 50, 500, 90],
                "raw_rows": [["項目", "金額"], ["鋼板工程", "12000"]],
                "total": None,
            },
        },
        "images": {}, "structure": ["tbl-overview", "txt-001", "tbl-001"],
    }


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import config
    import pdf_editor.services.cache_manager as cm_mod
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(cm_mod, "CACHE_DIR", tmp_path / "caches")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "caches").mkdir()
    _app = create_app()
    _app.config["TESTING"] = True
    yield _app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded_cache(app):
    import pdf_editor.services.cache_manager as cm_mod
    cm = CacheManager(FAKE_DOC_ID, "sample.pdf")
    cm.cache_dir  = cm_mod.CACHE_DIR / FAKE_DOC_ID
    cm.images_dir = cm.cache_dir / "images"
    cm.save(_fake_parsed())
    return cm


# ── 表格 PATCH 帶有 validation ────────────────────────────────

class TestPatchTableIncludesValidation:
    def test_text_patch_has_no_validation_key(self, client, seeded_cache):
        """文字區塊更新不應觸發驗證邏輯。"""
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "text", "data": {"content": "修改"}},
        )
        assert r.status_code == 200
        assert "validation" not in r.get_json()

    def test_valid_table_patch_reports_valid(self, client, seeded_cache):
        """整列正確（單價×數量=小計）時，validation.is_valid 應為 True。"""
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板", "1200", "10", "12000"],
                ],
            }},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "validation" in data
        assert data["validation"]["is_valid"] is True
        assert data["validation"]["error_count"] == 0

    def test_invalid_subtotal_reported(self, client, seeded_cache):
        """修改數量後若小計沒同步更新，應回報 SUBTOTAL_MISMATCH。"""
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板", "1200", "20", "12000"],
                ],
            }},
        )
        data = r.get_json()
        assert data["validation"]["is_valid"] is False
        codes = [i["code"] for i in data["validation"]["issues"]]
        assert "SUBTOTAL_MISMATCH" in codes

    def test_patch_still_succeeds_despite_invalid_validation(self, client, seeded_cache):
        """驗證失敗不應阻擋存檔——資料仍要寫入快取，只是附帶警示。"""
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板", "1200", "20", "12000"],
                ],
            }},
        )
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        r2 = client.get(f"/api/doc/{FAKE_DOC_ID}/block/tbl-001")
        assert r2.get_json()["block"]["raw_rows"][1][2] == "20"

    def test_overview_mismatch_included_in_validation(self, client, seeded_cache):
        """
        模擬總覽表被獨立竄改（未經由子表格 patch 的自動聯動），
        驗證應偵測到子表格 total 與總覽頁儲存格不一致。
        """
        cm = seeded_cache
        tables = cm._read_json("tables.json")
        # 直接改總覽頁儲存格，繞過 propagate 邏輯，製造不同步狀態
        tables["tbl-overview"]["raw_rows"][1][1] = "1"
        cm._write_json("tables.json", tables)

        # 對子表格做一個不影響 total 數值的 patch，觸發 validation 重新檢查目前狀態
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板", "1200", "10", "12000"],
                ],
            }},
        )
        data = r.get_json()
        codes = [i["code"] for i in data["validation"]["issues"]]
        assert "OVERVIEW_LINK_MISMATCH" in codes
        assert data["validation"]["is_valid"] is False

    def test_overview_table_patch_also_has_validation(self, client, seeded_cache):
        """總覽表本身被 PATCH 時，也應觸發驗證（type 為 table）。"""
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-overview",
            json={"type": "table", "data": {
                "raw_rows": [["項目", "金額"], ["鋼板工程", "99999"]],
            }},
        )
        assert r.status_code == 200
        assert "validation" in r.get_json()

    def test_no_overview_link_skips_overview_check(self, client, seeded_cache):
        """沒有聯動總覽頁的表格，validation 不應包含 OVERVIEW 開頭的 issue。"""
        cm = seeded_cache
        tables = cm._read_json("tables.json")
        tables["tbl-standalone"] = {
            "id": "tbl-standalone", "type": "table", "page": 1,
            "raw_rows": [["品名", "單價", "數量", "小計"], ["螺絲", "10", "5", "50"]],
            "linked_overview_block": None,
            "linked_overview_cell":  None,
            "total": 50.0,
        }
        cm._write_json("tables.json", tables)

        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-standalone",
            json={"type": "table", "data": {"total": 50.0}},
        )
        data = r.get_json()
        overview_codes = [i["code"] for i in data["validation"]["issues"] if "OVERVIEW" in i["code"]]
        assert overview_codes == []

    def test_validation_schema_complete(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {"total": 12000.0}},
        )
        v = r.get_json()["validation"]
        for key in ("is_valid", "error_count", "warning_count", "issues"):
            assert key in v, f"validation 缺少 {key}"
