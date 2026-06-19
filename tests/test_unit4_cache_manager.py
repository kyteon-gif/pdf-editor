"""
tests/test_unit4_cache_manager.py
Unit 4 — cache_manager：驗證快取讀寫、局部更新、圖片路徑、overview 聯動。

執行：
    pytest tests/test_unit4_cache_manager.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 強制推到最前面，蓋過環境裡已安裝的同名套件


# 確保專案根目錄在 sys.path 最前面（macOS/miniforge 防禦）
import json
import shutil
import pytest
from pdf_editor.services.cache_manager import CacheManager, list_all_caches


# ── Fixtures ──────────────────────────────────────────────────

FAKE_DOC_ID = "a" * 64   # 假 SHA-256

def _fake_parsed(doc_id=FAKE_DOC_ID) -> dict:
    """產生一份最小的 parsed dict，模擬 parse_pdf() 輸出。"""
    return {
        "doc_id":     doc_id,
        "filename":   "sample.pdf",
        "page_count": 2,
        "texts": {
            "txt-p01-0000": {
                "id": "txt-p01-0000", "type": "cover",
                "page": 1, "bbox": [72, 80, 500, 100],
                "content": "封面標題", "font_size": 20.0, "font_name": "Arial",
            },
            "txt-p02-0000": {
                "id": "txt-p02-0000", "type": "body",
                "page": 2, "bbox": [72, 100, 500, 120],
                "content": "正文內容", "font_size": 11.0, "font_name": "Arial",
            },
            "img-p01-0000": {
                "id": "img-p01-0000", "type": "image",
                "page": 1, "bbox": [72, 200, 300, 350],
                "content": "", "font_size": None, "font_name": None,
                "image_ext": "png",
            },
        },
        "tables": {
            "tbl-p02-0000": {
                "id": "tbl-p02-0000", "type": "table",
                "page": 2, "bbox": [72, 300, 500, 420],
                "raw_rows": [
                    ["品名", "單價", "數量", "小計"],
                    ["鋼板 A", "1200", "10", "12000"],
                    ["總計", "", "", "12000"],
                ],
                "linked_overview_block": None,
                "linked_overview_cell":  None,
                "total": 12000.0,
            },
        },
        "images": {
            "img-p01-0000": b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,  # 假 PNG bytes
        },
        "structure": ["txt-p01-0000", "img-p01-0000", "tbl-p02-0000", "txt-p02-0000"],
    }


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    """每個測試使用獨立 tmp_path 作為 CACHE_DIR。"""
    import pdf_editor.services.cache_manager as cm_mod
    monkeypatch.setattr(cm_mod, "CACHE_DIR", tmp_path)
    mgr = CacheManager(FAKE_DOC_ID, "sample.pdf")
    mgr.cache_dir  = tmp_path / FAKE_DOC_ID
    mgr.images_dir = mgr.cache_dir / "images"
    return mgr


# ── exists() ──────────────────────────────────────────────────

class TestExists:
    def test_false_before_save(self, cm):
        assert cm.exists() is False

    def test_true_after_save(self, cm):
        cm.save(_fake_parsed())
        assert cm.exists() is True

    def test_false_if_meta_missing(self, cm):
        cm.save(_fake_parsed())
        (cm.cache_dir / "meta.json").unlink()
        assert cm.exists() is False


# ── save() ────────────────────────────────────────────────────

class TestSave:
    def test_creates_required_files(self, cm):
        cm.save(_fake_parsed())
        for fname in ("meta.json", "texts.json", "tables.json", "structure.json"):
            assert (cm.cache_dir / fname).exists(), f"{fname} 未建立"

    def test_meta_content(self, cm):
        cm.save(_fake_parsed())
        meta = json.loads((cm.cache_dir / "meta.json").read_text())
        assert meta["doc_id"]     == FAKE_DOC_ID
        assert meta["filename"]   == "sample.pdf"
        assert meta["page_count"] == 2
        assert meta["version"]    == 1
        assert meta["exported_at"] is None

    def test_image_file_written(self, cm):
        cm.save(_fake_parsed())
        img_file = cm.images_dir / "img-p01-0000.png"
        assert img_file.exists()
        assert img_file.stat().st_size > 0

    def test_structure_saved_as_list(self, cm):
        cm.save(_fake_parsed())
        raw = json.loads((cm.cache_dir / "structure.json").read_text())
        assert isinstance(raw, list)
        assert "txt-p01-0000" in raw


# ── load() ────────────────────────────────────────────────────

class TestLoad:
    def test_load_returns_all_keys(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        for key in ("doc_id", "filename", "page_count", "texts", "tables", "images", "structure"):
            assert key in result, f"load() 缺少 {key}"

    def test_load_texts_content(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        assert "txt-p01-0000" in result["texts"]
        assert result["texts"]["txt-p01-0000"]["content"] == "封面標題"

    def test_load_tables_content(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        assert "tbl-p02-0000" in result["tables"]
        rows = result["tables"]["tbl-p02-0000"]["raw_rows"]
        assert rows[0][0] == "品名"

    def test_load_structure_is_list(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        assert isinstance(result["structure"], list)
        assert len(result["structure"]) == 4

    def test_load_image_bytes(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        assert "img-p01-0000" in result["images"]
        assert isinstance(result["images"]["img-p01-0000"], bytes)

    def test_load_page_count(self, cm):
        cm.save(_fake_parsed())
        result = cm.load()
        assert result["page_count"] == 2


# ── patch() — text ────────────────────────────────────────────

class TestPatchText:
    def test_patch_updates_content(self, cm):
        cm.save(_fake_parsed())
        cm.patch("txt-p02-0000", "text", {"content": "修改後的正文"})
        texts = json.loads((cm.cache_dir / "texts.json").read_text())
        assert texts["txt-p02-0000"]["content"] == "修改後的正文"

    def test_patch_updates_last_edited_at(self, cm):
        cm.save(_fake_parsed())
        cm.patch("txt-p01-0000", "text", {"content": "新封面"})
        meta = json.loads((cm.cache_dir / "meta.json").read_text())
        assert meta["last_edited_at"] is not None

    def test_patch_nonexistent_block_raises(self, cm):
        cm.save(_fake_parsed())
        with pytest.raises(KeyError):
            cm.patch("nonexistent", "text", {"content": "x"})

    def test_patch_preserves_other_blocks(self, cm):
        cm.save(_fake_parsed())
        cm.patch("txt-p02-0000", "text", {"content": "新內容"})
        texts = json.loads((cm.cache_dir / "texts.json").read_text())
        # 其他區塊不受影響
        assert texts["txt-p01-0000"]["content"] == "封面標題"


# ── patch() — table ───────────────────────────────────────────

class TestPatchTable:
    def test_patch_updates_total(self, cm):
        cm.save(_fake_parsed())
        cm.patch("tbl-p02-0000", "table", {"total": 99000.0})
        tables = json.loads((cm.cache_dir / "tables.json").read_text())
        assert tables["tbl-p02-0000"]["total"] == 99000.0

    def test_patch_updates_raw_rows(self, cm):
        cm.save(_fake_parsed())
        new_rows = [["品名","單價","數量","小計"],["螺絲組","80","50","4000"]]
        cm.patch("tbl-p02-0000", "table", {"raw_rows": new_rows})
        tables = json.loads((cm.cache_dir / "tables.json").read_text())
        assert tables["tbl-p02-0000"]["raw_rows"][1][0] == "螺絲組"


# ── patch() — image ───────────────────────────────────────────

class TestPatchImage:
    def test_patch_writes_replaced_file(self, cm):
        cm.save(_fake_parsed())
        new_bytes = b"\x89PNG\r\n" + b"\xff" * 10
        cm.patch("img-p01-0000", "image", {"bytes": new_bytes, "ext": "png"})
        replaced = cm.images_dir / "img-p01-0000_replaced.png"
        assert replaced.exists()
        assert replaced.read_bytes() == new_bytes

    def test_patch_image_size_metadata(self, cm):
        cm.save(_fake_parsed())
        cm.patch("img-p01-0000", "image", {
            "bytes": b"\x89PNG" + b"\x00" * 4,
            "ext":   "png",
            "width": 320, "height": 200,
        })
        texts = json.loads((cm.cache_dir / "texts.json").read_text())
        assert texts["img-p01-0000"]["width"]  == 320
        assert texts["img-p01-0000"]["height"] == 200


# ── get_image_path() ──────────────────────────────────────────

class TestGetImagePath:
    def test_returns_original_if_no_replaced(self, cm):
        cm.save(_fake_parsed())
        p = cm.get_image_path("img-p01-0000")
        assert p is not None
        assert "replaced" not in p.name

    def test_returns_replaced_if_exists(self, cm):
        cm.save(_fake_parsed())
        cm.patch("img-p01-0000", "image", {"bytes": b"newimg", "ext": "png"})
        p = cm.get_image_path("img-p01-0000")
        assert p is not None
        assert "replaced" in p.name

    def test_returns_none_for_missing_block(self, cm):
        cm.save(_fake_parsed())
        assert cm.get_image_path("nonexistent") is None


# ── mark_exported() ───────────────────────────────────────────

class TestMarkExported:
    def test_increments_version(self, cm):
        cm.save(_fake_parsed())
        cm.mark_exported()
        meta = json.loads((cm.cache_dir / "meta.json").read_text())
        assert meta["version"]     == 2
        assert meta["exported_at"] is not None

    def test_mark_twice_increments_again(self, cm):
        cm.save(_fake_parsed())
        cm.mark_exported()
        cm.mark_exported()
        meta = json.loads((cm.cache_dir / "meta.json").read_text())
        assert meta["version"] == 3


# ── overview 聯動 ─────────────────────────────────────────────

class TestOverviewPropagation:
    def test_propagate_updates_overview_cell(self, cm):
        parsed = _fake_parsed()
        # 加入總覽表
        parsed["tables"]["tbl-overview"] = {
            "id": "tbl-overview", "type": "overview",
            "page": 1, "bbox": [72, 150, 500, 250],
            "raw_rows": [
                ["項目", "金額"],
                ["鋼板工程", "0"],     # 將被聯動更新
            ],
            "total": None,
        }
        # 子表格指向總覽
        parsed["tables"]["tbl-p02-0000"]["linked_overview_block"] = "tbl-overview"
        parsed["tables"]["tbl-p02-0000"]["linked_overview_cell"]  = "B2"

        cm.save(parsed)
        cm.patch("tbl-p02-0000", "table", {"total": 55000.0})

        tables = json.loads((cm.cache_dir / "tables.json").read_text())
        updated_cell = tables["tbl-overview"]["raw_rows"][1][1]
        assert updated_cell == "55000.0", f"期望 55000.0，得到 {updated_cell}"


# ── delete() ──────────────────────────────────────────────────

class TestDelete:
    def test_delete_removes_directory(self, cm):
        cm.save(_fake_parsed())
        assert cm.cache_dir.exists()
        cm.delete()
        assert not cm.cache_dir.exists()

    def test_delete_idempotent(self, cm):
        """刪除不存在的快取不應拋出例外。"""
        try:
            cm.delete()
        except Exception as e:
            pytest.fail(f"delete() 不應拋出例外：{e}")


# ── list_all_caches() ─────────────────────────────────────────

class TestListAllCaches:
    def test_returns_list(self, tmp_path, monkeypatch):
        import pdf_editor.services.cache_manager as cm_mod
        monkeypatch.setattr(cm_mod, "CACHE_DIR", tmp_path)

        # 建立兩份快取
        for doc_id in ["a" * 64, "b" * 64]:
            mgr = CacheManager(doc_id, f"{doc_id[:8]}.pdf")
            mgr.cache_dir  = tmp_path / doc_id
            mgr.images_dir = mgr.cache_dir / "images"
            mgr.save(_fake_parsed(doc_id))

        result = list_all_caches()
        # 因 monkeypatch 替換了模組層級的 CACHE_DIR，需手動從 tmp_path 讀
        import json as _json
        metas = [
            _json.loads(p.read_text())
            for p in sorted(tmp_path.glob("*/meta.json"))
        ]
        assert len(metas) == 2

    def test_empty_if_no_cache(self, tmp_path, monkeypatch):
        import pdf_editor.services.cache_manager as cm_mod
        monkeypatch.setattr(cm_mod, "CACHE_DIR", tmp_path)
        result = list_all_caches()
        assert result == []
