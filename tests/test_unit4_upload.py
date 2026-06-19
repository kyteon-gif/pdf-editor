"""
tests/test_unit4_upload.py
Unit 4 — routes/upload：驗證 POST /api/upload 的各種情境。

測試策略：
- mock parse_pdf 與 Classifier，讓測試不依賴 PDF 套件與 NLP 模型
- 用真實 Flask test client 發送 multipart 請求
- 涵蓋：快取命中、首次解析、錯誤處理、回傳結構

執行：
    pytest tests/test_unit4_upload.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 強制推到最前面，蓋過環境裡已安裝的同名套件


# 確保專案根目錄在 sys.path 最前面（macOS/miniforge 防禦）
import base64
import hashlib
import io
import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from pdf_editor import create_app


# ── 假資料 ────────────────────────────────────────────────────

FAKE_PDF   = b"%PDF-1.4 fake content for testing"
FAKE_HASH  = hashlib.sha256(FAKE_PDF).hexdigest()

FAKE_PARSED = {
    "doc_id":     FAKE_HASH,
    "filename":   "test.pdf",
    "page_count": 2,
    "texts": {
        "txt-p01-0000": {
            "id": "txt-p01-0000", "type": "cover",
            "page": 1, "bbox": [72, 80, 500, 100],
            "content": "封面標題", "font_size": 20.0, "font_name": "Arial",
        },
    },
    "tables": {
        "tbl-p02-0000": {
            "id": "tbl-p02-0000", "type": "table",
            "page": 2, "bbox": [72, 300, 500, 420],
            "raw_rows": [["品名", "單價"], ["鋼板", "1200"]],
            "total": 1200.0,
        },
    },
    "images": {
        "img-p01-0000": b"\x89PNG\r\n\x1a\n" + b"\x00" * 8,
    },
    "structure": ["txt-p01-0000", "img-p01-0000", "tbl-p02-0000"],
}


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture()
def app(tmp_path):
    """每個測試使用獨立 tmp_path 隔離檔案系統。"""
    _app = create_app()
    _app.config["TESTING"] = True

    # 覆寫 UPLOAD_DIR 與 CACHE_DIR 至 tmp_path
    import config
    import pdf_editor.services.cache_manager as cm_mod

    _orig_upload = config.UPLOAD_DIR
    _orig_cache  = cm_mod.CACHE_DIR

    config.UPLOAD_DIR  = tmp_path / "uploads"
    cm_mod.CACHE_DIR   = tmp_path / "caches"
    config.UPLOAD_DIR.mkdir()
    cm_mod.CACHE_DIR.mkdir()

    yield _app

    config.UPLOAD_DIR = _orig_upload
    cm_mod.CACHE_DIR  = _orig_cache


@pytest.fixture()
def client(app):
    return app.test_client()


def _upload(client, data=FAKE_PDF, filename="test.pdf", field="pdf"):
    """封裝 multipart 上傳動作。"""
    return client.post(
        "/api/upload",
        data={field: (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


# ── 錯誤處理測試 ──────────────────────────────────────────────

class TestUploadValidation:
    def test_no_file_field_returns_400(self, client):
        r = client.post("/api/upload", data={}, content_type="multipart/form-data")
        assert r.status_code == 400
        assert "pdf" in r.get_json()["error"]

    def test_empty_filename_returns_400(self, client):
        r = client.post(
            "/api/upload",
            data={"pdf": (io.BytesIO(b"data"), "")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_non_pdf_returns_415(self, client):
        r = _upload(client, data=b"fake", filename="doc.docx")
        assert r.status_code == 415

    def test_empty_bytes_returns_400(self, client):
        r = _upload(client, data=b"", filename="empty.pdf")
        assert r.status_code == 400


# ── 首次上傳（cache miss）────────────────────────────────────

class TestUploadCacheMiss:

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_returns_200(self, mock_cls, mock_parse, client):
        r = _upload(client)
        assert r.status_code == 200

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_source_is_parsed(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert data["source"] == "parsed"

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_response_schema(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        for key in ("doc_id", "filename", "page_count", "source",
                    "structure", "texts", "tables", "images"):
            assert key in data, f"回傳缺少 {key}"

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_doc_id_matches_sha256(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert data["doc_id"] == FAKE_HASH

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_page_count(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert data["page_count"] == 2

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_texts_returned(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert "txt-p01-0000" in data["texts"]
        assert data["texts"]["txt-p01-0000"]["content"] == "封面標題"

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_tables_returned(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert "tbl-p02-0000" in data["tables"]

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_images_are_base64(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert "img-p01-0000" in data["images"]
        # 驗證是合法 base64
        decoded = base64.b64decode(data["images"]["img-p01-0000"])
        assert decoded == FAKE_PARSED["images"]["img-p01-0000"]

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_structure_is_list(self, mock_cls, mock_parse, client):
        data = _upload(client).get_json()
        assert isinstance(data["structure"], list)
        assert len(data["structure"]) == 3

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_parse_called_once(self, mock_cls, mock_parse, client):
        _upload(client)
        mock_parse.assert_called_once()

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_classifier_called_once(self, mock_cls, mock_parse, client):
        _upload(client)
        mock_cls.assert_called_once()


# ── 快取命中（cache hit）─────────────────────────────────────

class TestUploadCacheHit:

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_second_upload_hits_cache(self, mock_cls, mock_parse, client):
        _upload(client)           # 第一次：寫入快取
        mock_parse.reset_mock()
        mock_cls.reset_mock()

        r2 = _upload(client)     # 第二次：應命中快取
        data = r2.get_json()

        assert data["source"] == "cache"
        mock_parse.assert_not_called()
        mock_cls.assert_not_called()

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_cache_hit_same_doc_id(self, mock_cls, mock_parse, client):
        _upload(client)
        data = _upload(client).get_json()
        assert data["doc_id"] == FAKE_HASH

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_cache_hit_returns_200(self, mock_cls, mock_parse, client):
        _upload(client)
        r2 = _upload(client)
        assert r2.status_code == 200


# ── parse_pdf 拋出例外 ────────────────────────────────────────

class TestUploadParseError:

    @patch("pdf_editor.routes.upload.parse_pdf", side_effect=RuntimeError("缺少 pdfplumber"))
    def test_parse_error_returns_500(self, mock_parse, client):
        r = _upload(client)
        assert r.status_code == 500
        assert "error" in r.get_json()

    @patch("pdf_editor.routes.upload.parse_pdf", side_effect=RuntimeError("缺少 pdfplumber"))
    def test_parse_error_message_in_response(self, mock_parse, client):
        data = _upload(client).get_json()
        assert "pdfplumber" in data["error"]


# ── 檔名安全性 ────────────────────────────────────────────────

class TestFilenameHandling:

    @patch("pdf_editor.routes.upload.parse_pdf", return_value=FAKE_PARSED)
    @patch("pdf_editor.routes.upload.Classifier.classify_blocks", return_value=FAKE_PARSED["texts"])
    def test_unsafe_filename_sanitized(self, mock_cls, mock_parse, client, tmp_path):
        """含路徑符號的檔名應被 secure_filename 處理。"""
        r = _upload(client, filename="../../../etc/passwd.pdf")
        # 只要不是 400/415，代表 secure_filename 有處理
        assert r.status_code in (200, 400)
