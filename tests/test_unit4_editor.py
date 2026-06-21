"""
tests/test_unit4_editor.py
Unit 4 — routes/editor：GET/PATCH 區塊、總覽頁查詢。

執行：
    pytest tests/test_unit4_editor.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import pytest
from pdf_editor import create_app
from pdf_editor.services.cache_manager import CacheManager


FAKE_DOC_ID = "e" * 64


def _fake_parsed(doc_id=FAKE_DOC_ID) -> dict:
    return {
        "doc_id":     doc_id,
        "filename":   "sample.pdf",
        "page_count": 1,
        "texts": {
            "txt-001": {
                "id": "txt-001", "type": "body", "page": 1,
                "bbox": [72, 100, 500, 120],
                "content": "原始內文", "font_size": 11.0, "font_name": "Arial",
            },
        },
        "tables": {
            "tbl-001": {
                "id": "tbl-001", "type": "table", "page": 1,
                "bbox": [72, 200, 500, 300],
                "raw_rows": [["品名", "單價"], ["鋼板", "1200"]],
                "linked_overview_block": "tbl-overview",
                "linked_overview_cell":  "B2",
                "total": 1200.0,
            },
            "tbl-overview": {
                "id": "tbl-overview", "type": "overview", "page": 1,
                "bbox": [72, 50, 500, 90],
                "raw_rows": [["項目", "金額"], ["鋼板工程", "0"]],
                "total": None,
            },
        },
        "images": {},
        "structure": ["tbl-overview", "txt-001", "tbl-001"],
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
    """預先寫入一份快取，回傳 CacheManager。"""
    import pdf_editor.services.cache_manager as cm_mod
    cm = CacheManager(FAKE_DOC_ID, "sample.pdf")
    cm.cache_dir  = cm_mod.CACHE_DIR / FAKE_DOC_ID
    cm.images_dir = cm.cache_dir / "images"
    cm.save(_fake_parsed())
    return cm


# ── GET /api/doc/<doc_id> ───────────────────────────────────

class TestGetDocument:
    def test_404_if_not_exists(self, client):
        r = client.get(f"/api/doc/{'z'*64}")
        assert r.status_code == 404

    def test_200_after_seed(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}")
        assert r.status_code == 200

    def test_response_schema(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}").get_json()
        for key in ("doc_id", "filename", "page_count", "structure", "texts", "tables", "meta"):
            assert key in data, f"缺少 {key}"

    def test_texts_content(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}").get_json()
        assert data["texts"]["txt-001"]["content"] == "原始內文"

    def test_meta_has_version(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}").get_json()
        assert data["meta"]["version"] == 1


# ── GET /api/doc/<doc_id>/block/<block_id> ──────────────────

class TestGetBlock:
    def test_404_if_doc_not_exists(self, client):
        r = client.get(f"/api/doc/{'z'*64}/block/txt-001")
        assert r.status_code == 404

    def test_404_if_block_not_exists(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/block/nonexistent")
        assert r.status_code == 404

    def test_200_for_text_block(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/block/txt-001")
        assert r.status_code == 200
        assert r.get_json()["block"]["content"] == "原始內文"

    def test_200_for_table_block(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/block/tbl-001")
        assert r.status_code == 200
        assert r.get_json()["block"]["type"] == "table"


# ── PATCH /api/doc/<doc_id>/block/<block_id> ────────────────

class TestPatchBlock:
    def test_404_if_doc_not_exists(self, client):
        r = client.patch(
            f"/api/doc/{'z'*64}/block/txt-001",
            json={"type": "text", "data": {"content": "x"}},
        )
        assert r.status_code == 404

    def test_400_no_body(self, client, seeded_cache):
        r = client.patch(f"/api/doc/{FAKE_DOC_ID}/block/txt-001")
        assert r.status_code == 400

    def test_400_invalid_type(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "bogus", "data": {}},
        )
        assert r.status_code == 400

    def test_400_data_not_dict(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "text", "data": "not a dict"},
        )
        assert r.status_code == 400

    def test_404_block_not_found(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/nonexistent",
            json={"type": "text", "data": {"content": "x"}},
        )
        assert r.status_code == 404

    def test_text_patch_updates_content(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "text", "data": {"content": "修改後內文"}},
        )
        assert r.status_code == 200
        assert r.get_json()["block"]["content"] == "修改後內文"

    def test_text_patch_persisted(self, client, seeded_cache):
        client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "text", "data": {"content": "持久化測試"}},
        )
        r2 = client.get(f"/api/doc/{FAKE_DOC_ID}/block/txt-001")
        assert r2.get_json()["block"]["content"] == "持久化測試"

    def test_table_patch_updates_total(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {"total": 9999.0}},
        )
        assert r.status_code == 200
        assert r.get_json()["block"]["total"] == 9999.0

    def test_table_patch_propagates_overview(self, client, seeded_cache):
        client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/tbl-001",
            json={"type": "table", "data": {"total": 8888.0}},
        )
        r2 = client.get(f"/api/doc/{FAKE_DOC_ID}/block/tbl-overview")
        rows = r2.get_json()["block"]["raw_rows"]
        assert rows[1][1] == "8888.0"

    def test_ok_field_true(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/block/txt-001",
            json={"type": "text", "data": {"content": "x"}},
        )
        assert r.get_json()["ok"] is True


# ── GET /api/doc/<doc_id>/overview ──────────────────────────

class TestGetOverview:
    def test_404_if_not_exists(self, client):
        r = client.get(f"/api/doc/{'z'*64}/overview")
        assert r.status_code == 404

    def test_200_after_seed(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/overview")
        assert r.status_code == 200

    def test_overview_tables_found(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}/overview").get_json()
        assert "tbl-overview" in data["overview_tables"]

    def test_linked_tables_found(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}/overview").get_json()
        assert "tbl-001" in data["linked_tables"]
        assert data["linked_tables"]["tbl-001"]["linked_overview_cell"] == "B2"

    def test_linked_total_matches(self, client, seeded_cache):
        data = client.get(f"/api/doc/{FAKE_DOC_ID}/overview").get_json()
        assert data["linked_tables"]["tbl-001"]["total"] == 1200.0
