"""
tests/test_unit4_image.py
Unit 4 — routes/image：置換、調整尺寸位置、還原、取得圖片。

執行：
    pytest tests/test_unit4_image.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import io
import pytest
from pdf_editor import create_app
from pdf_editor.services.cache_manager import CacheManager


FAKE_DOC_ID = "f" * 64
ORIGINAL_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
NEW_PNG      = b"\x89PNG\r\n\x1a\n" + b"\xff" * 16


def _fake_parsed(doc_id=FAKE_DOC_ID) -> dict:
    return {
        "doc_id": doc_id, "filename": "sample.pdf", "page_count": 1,
        "texts": {
            "img-001": {
                "id": "img-001", "type": "image", "page": 1,
                "bbox": [72, 200, 300, 350], "content": "",
                "font_size": None, "font_name": None, "image_ext": "png",
            },
            "txt-001": {
                "id": "txt-001", "type": "body", "page": 1,
                "bbox": [72, 100, 500, 120], "content": "文字區塊",
                "font_size": 11.0, "font_name": "Arial",
            },
        },
        "tables": {}, "images": {"img-001": ORIGINAL_PNG},
        "structure": ["txt-001", "img-001"],
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


def _upload_replace(client, doc_id, block_id, data=NEW_PNG, filename="new.png", extra=None):
    form = {"image": (io.BytesIO(data), filename)}
    if extra:
        form.update(extra)
    return client.post(
        f"/api/doc/{doc_id}/image/{block_id}/replace",
        data=form, content_type="multipart/form-data",
    )


# ── replace ───────────────────────────────────────────────────

class TestReplaceImage:
    def test_404_doc_not_exist(self, client):
        r = _upload_replace(client, "z" * 64, "img-001")
        assert r.status_code == 404

    def test_404_block_not_exist(self, client, seeded_cache):
        r = _upload_replace(client, FAKE_DOC_ID, "nonexistent")
        assert r.status_code == 404

    def test_400_no_image_field(self, client, seeded_cache):
        r = client.post(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/replace",
            data={}, content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_400_empty_filename(self, client, seeded_cache):
        r = client.post(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/replace",
            data={"image": (io.BytesIO(b"x"), "")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_400_empty_bytes(self, client, seeded_cache):
        r = _upload_replace(client, FAKE_DOC_ID, "img-001", data=b"", filename="empty.png")
        assert r.status_code == 400

    def test_200_success(self, client, seeded_cache):
        r = _upload_replace(client, FAKE_DOC_ID, "img-001")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_replaced_file_written(self, client, seeded_cache):
        _upload_replace(client, FAKE_DOC_ID, "img-001")
        p = seeded_cache.get_image_path("img-001")
        assert "replaced" in p.name
        assert p.read_bytes() == NEW_PNG

    def test_replace_with_size(self, client, seeded_cache):
        r = _upload_replace(
            client, FAKE_DOC_ID, "img-001",
            extra={"width": "320", "height": "200"},
        )
        block = r.get_json()["block"]
        assert block["width"]  == 320.0
        assert block["height"] == 200.0

    def test_replace_invalid_size_returns_400(self, client, seeded_cache):
        r = _upload_replace(
            client, FAKE_DOC_ID, "img-001",
            extra={"width": "abc"},
        )
        assert r.status_code == 400

    def test_replace_jpg_extension(self, client, seeded_cache):
        r = _upload_replace(client, FAKE_DOC_ID, "img-001", filename="photo.jpg")
        assert r.status_code == 200
        p = seeded_cache.get_image_path("img-001")
        assert p.suffix == ".jpg"

    def test_replace_unsupported_ext_falls_back_png(self, client, seeded_cache):
        r = _upload_replace(client, FAKE_DOC_ID, "img-001", filename="file.exe")
        assert r.status_code == 200
        p = seeded_cache.get_image_path("img-001")
        assert p.suffix == ".png"


# ── transform ─────────────────────────────────────────────────

class TestTransformImage:
    def test_404_doc_not_exist(self, client):
        r = client.patch(f"/api/doc/{'z'*64}/image/img-001/transform", json={"width": 100})
        assert r.status_code == 404

    def test_404_block_not_exist(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/nonexistent/transform", json={"width": 100}
        )
        assert r.status_code == 404

    def test_400_no_body(self, client, seeded_cache):
        r = client.patch(f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform")
        assert r.status_code == 400

    def test_400_empty_allowed_keys(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform",
            json={"unrelated_field": "x"},
        )
        assert r.status_code == 400

    def test_400_non_numeric(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform",
            json={"width": "not_a_number"},
        )
        assert r.status_code == 400

    def test_400_negative_value(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform",
            json={"x": -10},
        )
        assert r.status_code == 400

    def test_200_updates_dimensions(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform",
            json={"width": 400, "height": 250, "x": 50, "y": 60},
        )
        assert r.status_code == 200
        block = r.get_json()["block"]
        assert block["width"]  == 400
        assert block["height"] == 250
        assert block["x"]      == 50
        assert block["y"]      == 60

    def test_partial_update_only_width(self, client, seeded_cache):
        r = client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform", json={"width": 500}
        )
        assert r.status_code == 200
        assert r.get_json()["block"]["width"] == 500

    def test_transform_does_not_touch_image_bytes(self, client, seeded_cache):
        client.patch(
            f"/api/doc/{FAKE_DOC_ID}/image/img-001/transform", json={"width": 500}
        )
        p = seeded_cache.get_image_path("img-001")
        # transform 不應建立 _replaced 檔案（沒有上傳新圖片 bytes）
        assert "replaced" not in p.name


# ── restore ───────────────────────────────────────────────────

class TestRestoreImage:
    def test_404_doc_not_exist(self, client):
        r = client.post(f"/api/doc/{'z'*64}/image/img-001/restore")
        assert r.status_code == 404

    def test_404_block_not_exist(self, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/image/nonexistent/restore")
        assert r.status_code == 404

    def test_restored_false_if_no_replaced(self, client, seeded_cache):
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/image/img-001/restore")
        assert r.status_code == 200
        assert r.get_json()["restored"] is False

    def test_restored_true_after_replace(self, client, seeded_cache):
        _upload_replace(client, FAKE_DOC_ID, "img-001")
        r = client.post(f"/api/doc/{FAKE_DOC_ID}/image/img-001/restore")
        assert r.get_json()["restored"] is True

    def test_get_image_returns_original_after_restore(self, client, seeded_cache):
        _upload_replace(client, FAKE_DOC_ID, "img-001")
        client.post(f"/api/doc/{FAKE_DOC_ID}/image/img-001/restore")
        p = seeded_cache.get_image_path("img-001")
        assert "replaced" not in p.name
        assert p.read_bytes() == ORIGINAL_PNG


# ── get image ────────────────────────────────────────────────

class TestGetImage:
    def test_404_doc_not_exist(self, client):
        r = client.get(f"/api/doc/{'z'*64}/image/img-001")
        assert r.status_code == 404

    def test_404_no_image(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/image/nonexistent")
        assert r.status_code == 404

    def test_200_returns_original(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/image/img-001")
        assert r.status_code == 200
        assert r.data == ORIGINAL_PNG

    def test_200_returns_replaced_after_upload(self, client, seeded_cache):
        _upload_replace(client, FAKE_DOC_ID, "img-001")
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/image/img-001")
        assert r.data == NEW_PNG

    def test_mimetype_png(self, client, seeded_cache):
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/image/img-001")
        assert r.mimetype == "image/png"

    def test_mimetype_jpg_normalized(self, client, seeded_cache):
        _upload_replace(client, FAKE_DOC_ID, "img-001", filename="photo.jpg")
        r = client.get(f"/api/doc/{FAKE_DOC_ID}/image/img-001")
        assert r.mimetype == "image/jpeg"
