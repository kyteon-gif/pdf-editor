"""
tests/test_unit4_renderer_image_sizing.py
Unit 4 修復 — _render_image() 的圖片尺寸計算。

背景（重要修復）：parser.py 從未填入 texts[blk_id]["width"]/["height"]
欄位（永遠是 None），導致圖片渲染時依賴 CSS max-width:100% 自動撐開，
高解析度圖片會以原始像素尺寸顯示，經常遠超過一頁 A4 紙的可用高度，
逼得 WeasyPrint 自動分頁，讓本該是單頁的內容被拆成多頁。
修正後改用 bbox 算出圖片在原始 PDF 頁面上應呈現的實際尺寸。

執行：
    pytest tests/test_unit4_renderer_image_sizing.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pdf_editor.services.renderer import _render_image


def _fake_cache_manager(path="/tmp/fake.png"):
    cm = MagicMock()
    cm.get_image_path.return_value = path
    return cm


class TestRenderImageSizing:

    @patch("pathlib.Path.exists", return_value=True)
    def test_size_derived_from_bbox_when_width_height_missing(self, mock_exists):
        blk = {"bbox": [72.0, 201.7, 523.0, 480.0]}
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert "width:451" in html
        assert "height:278" in html

    @patch("pathlib.Path.exists", return_value=True)
    def test_uses_pt_unit(self, mock_exists):
        blk = {"bbox": [0, 0, 100, 50]}
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert "pt" in html
        assert "px" not in html

    @patch("pathlib.Path.exists", return_value=True)
    def test_explicit_width_height_takes_priority_over_bbox(self, mock_exists):
        blk = {"bbox": [0, 0, 1000, 1000], "width": 300, "height": 150}
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert "width:300pt" in html
        assert "height:150pt" in html

    @patch("pathlib.Path.exists", return_value=True)
    def test_no_bbox_no_width_height_falls_back_to_no_style(self, mock_exists):
        blk = {}
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert "<img" in html
        assert "style=" not in html

    @patch("pathlib.Path.exists", return_value=True)
    def test_invalid_bbox_zero_size_falls_back_to_no_style(self, mock_exists):
        """bbox 寬或高為 0（異常資料）不應產生無效的 0pt 樣式。"""
        blk = {"bbox": [10, 10, 10, 50]}  # width = 0
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert "style=" not in html

    def test_missing_file_returns_placeholder(self):
        blk = {"bbox": [0, 0, 100, 100]}
        cm = _fake_cache_manager(path="/nonexistent/path.png")
        html = _render_image(blk, "img-test", cm)

        assert "image-missing" in html

    @patch("pathlib.Path.exists", return_value=True)
    def test_file_url_format(self, mock_exists):
        blk = {"bbox": [0, 0, 100, 100]}
        html = _render_image(blk, "img-test", _fake_cache_manager())

        assert 'src="file://' in html
