"""
tests/test_unit4_export.py
Unit 4 — routes/export：匯出 PDF、取得最近匯出版本。

版本號邏輯：
  cache 初始 version=1（未匯出）
  export_pdf() 內部流程：render → mark_exported()（version+1） → 用新版本號命名檔案
  所以第一次呼叫 POST /export 後，version 變成 2，檔名為 {doc_id}_v2.pdf
  get_latest_export() 讀取同一個新版本號，因此能找到對應檔案。

策略：
- mock render_pdf，避免依賴 weasyprint
- 驗證 exports/ 寫檔、版本號遞增、download_name 組成

執行：
    pytest tests/test_unit4_export.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from unittest.mock import patch
from pdf_editor import create_app
from pdf_editor.services.cache_manager import CacheManager
from pdf_editor.routes.export import _build_download_name


FAKE_DOC_ID = "9" * 64
FAKE_PDF_BYTES = b"%PDF-1.4 fake exported content"


def _fake_parsed(doc_id=FAKE_DOC_ID) -> dict:
    return {
        "doc_id": doc_id, "filename": "報價單.pdf", "page_count": 1,
        "texts": {
            "txt-001": {"id": "txt-001", "type": "cover", "page": 1, "content": "封面"},
        },
        "tables": {}, "images": {}, "structure": ["txt-001"],
    }


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import config
    import pdf_editor.services.cache_manager as cm_mod
    import pdf_editor.routes.export as export_mod

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(cm_mod, "CACHE_DIR", tmp_path / "caches")
    monkeypatch.setattr(export_mod, "EXPORT_DIR", tmp_path / "exports")

    for d in ("uploads", "exports", "caches"):
        (tmp_path / d).mkdir()

    _app = create_app()
    _app.config["TESTING"] = True
    _app.config["PROPAGATE_EXCEPTIONS"] = False
    yield _app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded_cache(app):
    import pdf_editor.services.cache_manager as cm_mod
    cm = CacheManager(FAKE_DOC_ID, "報價單.pdf")
    cm.cache_dir  = cm_mod.CACHE_DIR / FAKE_DOC_ID
    cm.images_dir = cm.cache_dir / "images"
    cm.save(_fake_parsed())
    return cm


# ── POST /export ─────────────────────────────────────────────

class TestExportPdf:
    def test_404_doc_not_exist(self, client):
        r = client.post(f"/api/doc/{'z'*64}/export")
        assert r.status_code == 404

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_200_success(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        assert r.status_code == 200

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_mimetype_pdf(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        assert r.mimetype == "application/pdf"

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_response_bytes_match(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        assert r.data == FAKE_PDF_BYTES

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_render_pdf_called_once(self, mock_render, client, seeded_cache):
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        mock_render.assert_called_once()

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_file_written_with_post_increment_version(self, mock_render, client, seeded_cache):
        """初始 version=1，匯出後 mark_exported() 變 2，檔名應為 _v2.pdf。"""
        import pdf_editor.routes.export as export_mod
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        out_path = export_mod.EXPORT_DIR / f"{FAKE_DOC_ID}_v2.pdf"
        assert out_path.exists()
        assert out_path.read_bytes() == FAKE_PDF_BYTES

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_version_incremented_after_export(self, mock_render, client, seeded_cache):
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        meta = seeded_cache.get_meta()
        assert meta["version"] == 2
        assert meta["exported_at"] is not None

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_repeated_export_creates_new_version_file(self, mock_render, client, seeded_cache):
        import pdf_editor.routes.export as export_mod
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")   # version 1 → 2，寫 _v2.pdf
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")   # version 2 → 3，寫 _v3.pdf
        assert (export_mod.EXPORT_DIR / f"{FAKE_DOC_ID}_v2.pdf").exists()
        assert (export_mod.EXPORT_DIR / f"{FAKE_DOC_ID}_v3.pdf").exists()
        meta = seeded_cache.get_meta()
        assert meta["version"] == 3

    @patch("pdf_editor.routes.export.render_pdf", side_effect=RuntimeError("缺少 weasyprint"))
    def test_render_runtime_error_returns_500(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        assert r.status_code == 500
        assert "weasyprint" in r.get_json()["error"]

    @patch("pdf_editor.routes.export.render_pdf", side_effect=RuntimeError("缺少 weasyprint"))
    def test_render_error_does_not_increment_version(self, mock_render, client, seeded_cache):
        """渲染失敗時不應呼叫 mark_exported()，版本號應維持不變。"""
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        meta = seeded_cache.get_meta()
        assert meta["version"] == 1
        assert meta["exported_at"] is None

    @patch("pdf_editor.routes.export.render_pdf", side_effect=ValueError("unexpected"))
    def test_render_unexpected_error_returns_500(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        assert r.status_code == 500
        assert "error" in r.get_json()

    def test_error_does_not_break_subsequent_export(self, client, seeded_cache):
        """一次失敗的匯出不應破壞 app 狀態，後續正常匯出仍可成功。"""
        with patch("pdf_editor.routes.export.render_pdf", side_effect=ValueError("unexpected")):
            client.post(f"/api/doc/{FAKE_DOC_ID}/export")  # 失敗，不增加版本
        with patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES):
            r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")  # 成功，version 1→2
            assert r.status_code == 200
        meta = seeded_cache.get_meta()
        assert meta["version"] == 2

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_download_filename_has_version(self, mock_render, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        cd = r.headers.get("Content-Disposition", "")
        assert "_v2.pdf" in cd


# ── GET /export/latest ───────────────────────────────────────

class TestGetLatestExport:
    def test_404_doc_not_exist(self, client):
        r = client.get(f"/api/doc/{'z'*64}/export/latest")
        assert r.status_code == 404

    def test_404_if_never_exported(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/export/latest")
        assert r.status_code == 404
        assert "尚未匯出" in r.get_json()["error"]

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_200_after_export(self, mock_render, client, seeded_cache):
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/export/latest")
        assert r.status_code == 200
        assert r.data == FAKE_PDF_BYTES

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_latest_does_not_call_render_again(self, mock_render, client, seeded_cache):
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        mock_render.reset_mock()
        client.get(f"/api/doc/{FAKE_DOC_ID}/export/latest")
        mock_render.assert_not_called()

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_latest_returns_newest_after_repeated_export(self, mock_render, client, seeded_cache):
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")   # v1 → v2
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")   # v2 → v3
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/export/latest")
        assert r.status_code == 200

    @patch("pdf_editor.routes.export.render_pdf", return_value=FAKE_PDF_BYTES)
    def test_404_if_export_file_missing_on_disk(self, mock_render, client, seeded_cache):
        import pdf_editor.routes.export as export_mod
        client.post(f"/api/doc/{FAKE_DOC_ID}/export")
        out_path = export_mod.EXPORT_DIR / f"{FAKE_DOC_ID}_v2.pdf"
        out_path.unlink()
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/export/latest")
        assert r.status_code == 404


# ── _build_download_name() ───────────────────────────────────

class TestBuildDownloadName:
    def test_replaces_extension(self):
        assert _build_download_name("報價單.pdf", 2) == "報價單_v2.pdf"

    def test_handles_no_extension(self):
        assert _build_download_name("noext", 1) == "noext_v1.pdf"

    def test_handles_multiple_dots(self):
        assert _build_download_name("file.v1.pdf", 3) == "file.v1_v3.pdf"
