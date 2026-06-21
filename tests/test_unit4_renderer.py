"""
tests/test_unit4_renderer.py
Unit 4 — services/renderer：驗證 build_html() 的結構正確性，
以及 render_pdf() 在缺少 weasyprint 時的錯誤處理。

策略：
- build_html() 純字串組裝，不依賴 weasyprint，可完整測試
- render_pdf() 用 mock 模擬 weasyprint.HTML，驗證呼叫鏈

執行：
    pytest tests/test_unit4_renderer.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from unittest.mock import MagicMock, patch
from pdf_editor.services.renderer import build_html, render_pdf, _render_table, _render_text


# ── 假資料 ────────────────────────────────────────────────────

def _fake_doc():
    return {
        "filename": "test.pdf",
        "texts": {
            "txt-001": {
                "id": "txt-001", "type": "cover", "page": 1,
                "content": "封面標題",
            },
            "txt-002": {
                "id": "txt-002", "type": "heading_1", "page": 2,
                "content": "第一章",
            },
            "txt-003": {
                "id": "txt-003", "type": "body", "page": 2,
                "content": "這是內文 <script>alert(1)</script>",
            },
            "img-001": {
                "id": "img-001", "type": "image", "page": 2,
                "width": 300, "height": 200,
            },
        },
        "tables": {
            "tbl-001": {
                "id": "tbl-001", "type": "table", "page": 2,
                "raw_rows": [
                    ["品名", "單價", "小計"],
                    ["鋼板", "1200", "12000"],
                    ["總計", "", "12000"],
                ],
            },
        },
        "structure": ["txt-001", "txt-002", "txt-003", "img-001", "tbl-001"],
    }


class FakeCacheManager:
    """模擬 CacheManager.get_image_path()。"""
    def __init__(self, image_path=None):
        self._image_path = image_path

    def get_image_path(self, block_id):
        return self._image_path


# ── build_html() ─────────────────────────────────────────────

class TestBuildHtmlStructure:
    def test_returns_valid_html_skeleton(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html and "</html>" in html
        assert "<body>" in html and "</body>" in html

    def test_contains_css(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert "<style>" in html

    def test_cover_rendered_as_h1(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert "block-cover" in html
        assert "封面標題" in html

    def test_heading1_rendered(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert "block-h1" in html
        assert "第一章" in html

    def test_body_text_escaped(self):
        """內文含 HTML 標籤應被跳脫，避免 injection。"""
        html = build_html(_fake_doc(), FakeCacheManager())
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_table_rendered(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert "<table" in html
        assert "品名" in html
        assert "12000" in html

    def test_table_total_row_marked(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert 'class="row-total"' in html

    def test_page_break_inserted_between_pages(self):
        html = build_html(_fake_doc(), FakeCacheManager())
        assert 'class="page-break"' in html

    def test_image_missing_fallback(self):
        """若 cache_manager 找不到圖片路徑，應顯示遺失提示而非崩潰。"""
        html = build_html(_fake_doc(), FakeCacheManager(image_path=None))
        assert "image-missing" in html

    def test_image_rendered_when_path_exists(self, tmp_path):
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        html = build_html(_fake_doc(), FakeCacheManager(image_path=img_file))
        assert "<img" in html
        assert "width:300pt" in html or "width: 300pt" in html

    def test_unknown_block_in_structure_skipped_gracefully(self):
        doc = _fake_doc()
        doc["structure"].append("nonexistent-block")
        try:
            html = build_html(doc, FakeCacheManager())
        except Exception as e:
            pytest.fail(f"不應拋出例外：{e}")
        assert "<!DOCTYPE html>" in html

    def test_empty_structure_returns_valid_skeleton(self):
        doc = {"filename": "empty.pdf", "texts": {}, "tables": {}, "structure": []}
        html = build_html(doc, FakeCacheManager())
        assert "<!DOCTYPE html>" in html


# ── _render_table() ──────────────────────────────────────────

class TestRenderTable:
    def test_empty_rows_returns_empty_string(self):
        assert _render_table({"raw_rows": []}) == ""

    def test_overview_uses_overview_class(self):
        blk = {"type": "overview", "raw_rows": [["項目", "金額"], ["A", "100"]]}
        html = _render_table(blk)
        assert "table-overview" in html

    def test_normal_table_uses_normal_class(self):
        blk = {"type": "table", "raw_rows": [["A", "B"], ["1", "2"]]}
        html = _render_table(blk)
        assert "table-normal" in html

    def test_cell_values_escaped(self):
        blk = {"type": "table", "raw_rows": [["A"], ["<b>x</b>"]]}
        html = _render_table(blk)
        assert "<b>x</b>" not in html
        assert "&lt;b&gt;" in html

    def test_total_keyword_variants(self):
        for keyword in ("總計", "合計", "Total"):
            blk = {"type": "table", "raw_rows": [["品名"], [keyword]]}
            html = _render_table(blk)
            assert 'class="row-total"' in html, f"{keyword} 未被標記為 total row"


# ── _render_text() ───────────────────────────────────────────

class TestRenderText:
    def test_heading2_uses_h2_tag(self):
        html = _render_text({"type": "heading_2", "content": "小節標題"})
        assert html.startswith("<h2")

    def test_appendix_uses_p_tag_with_class(self):
        html = _render_text({"type": "appendix", "content": "附錄內容"})
        assert html.startswith("<p")
        assert "block-appendix" in html

    def test_body_default_class(self):
        html = _render_text({"type": "body", "content": "一般內文"})
        assert "block-body" in html

    def test_small_font_heading_renders_compact(self):
        """
        重要修復：classifier 對圖表小標籤（圖例、座標軸文字等）
        有時誤判為 heading_1，若直接套用標題級大間距，多個誤判
        區塊疊加會把單頁內容撐爆成多頁。font_size < 9pt 時應改用
        緊湊樣式，不論分類結果為何。
        """
        html = _render_text({"type": "heading_1", "content": "什項設備", "font_size": 7.5})
        assert "block-body-compact" in html
        assert "<h1" not in html

    def test_normal_size_heading_unaffected(self):
        html = _render_text({"type": "heading_1", "content": "第一章", "font_size": 16.0})
        assert "<h1" in html
        assert "block-h1" in html

    def test_missing_font_size_keeps_heading_rendering(self):
        """font_size 為 None 時不應觸發降級（避免誤判沒有字級資訊的區塊）。"""
        html = _render_text({"type": "heading_1", "content": "標題", "font_size": None})
        assert "<h1" in html

    def test_boundary_font_size_9pt_not_compact(self):
        """剛好 9pt 不應觸發降級，門檻是嚴格小於 9。"""
        html = _render_text({"type": "heading_1", "content": "標題", "font_size": 9.0})
        assert "<h1" in html

    def test_boundary_font_size_just_under_9pt_is_compact(self):
        html = _render_text({"type": "heading_1", "content": "標籤", "font_size": 8.9})
        assert "block-body-compact" in html


# ── render_pdf() — mock weasyprint ──────────────────────────

class TestRenderPdf:
    def test_raises_if_weasyprint_missing(self):
        """模擬 weasyprint 未安裝時，應拋出帶有安裝指引的 RuntimeError。"""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "weasyprint":
                raise ImportError("No module named 'weasyprint'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(RuntimeError, match="weasyprint"):
                render_pdf(_fake_doc(), FakeCacheManager())

    def test_calls_weasyprint_html_write_pdf(self):
        """模擬 weasyprint 存在，驗證呼叫鏈正確。"""
        fake_html_instance = MagicMock()
        fake_html_instance.write_pdf.return_value = b"%PDF-fake-bytes"
        fake_html_class = MagicMock(return_value=fake_html_instance)

        fake_weasyprint = MagicMock()
        fake_weasyprint.HTML = fake_html_class

        with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
            result = render_pdf(_fake_doc(), FakeCacheManager())

        assert result == b"%PDF-fake-bytes"
        fake_html_class.assert_called_once()
        fake_html_instance.write_pdf.assert_called_once()

    def test_html_string_passed_to_weasyprint(self):
        """確認傳給 weasyprint.HTML() 的 string 參數包含正確內容。"""
        fake_html_instance = MagicMock()
        fake_html_instance.write_pdf.return_value = b"%PDF"
        fake_html_class = MagicMock(return_value=fake_html_instance)
        fake_weasyprint = MagicMock()
        fake_weasyprint.HTML = fake_html_class

        with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
            render_pdf(_fake_doc(), FakeCacheManager())

        call_kwargs = fake_html_class.call_args.kwargs
        assert "封面標題" in call_kwargs["string"]
