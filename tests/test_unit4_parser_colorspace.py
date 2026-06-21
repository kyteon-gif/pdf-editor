"""
tests/test_unit4_parser_colorspace.py
Unit 4 補強 — parser.py 的圖片色彩空間正規化。

背景：部分 PDF（常見於印刷流程產出）內嵌 CMYK 色彩模式圖片，
PNG 格式不支援 CMYK，匯出階段 Pillow 存檔會直接拋出
"cannot write mode CMYK as PNG" 導致整個匯出失敗。
_normalize_image_colorspace() 在解析階段就先轉換為 RGB，
避免問題延遲到匯出階段才發生。

執行：
    pytest tests/test_unit4_parser_colorspace.py -v
"""

import sys
import io
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pdf_editor.services.parser import _normalize_image_colorspace


def _make_image_bytes(mode: str, fmt: str, size=(10, 10)):
    """產生指定色彩模式的測試圖片 bytes。"""
    from PIL import Image

    if mode == "CMYK":
        img = Image.new("CMYK", size, (50, 50, 50, 0))
    elif mode == "P":
        img = Image.new("P", size)
        img.putpalette([i for i in range(256)] * 3)
    else:
        img = Image.new(mode, size, (255, 0, 0) if mode in ("RGB", "RGBA") else 128)

    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestNormalizeImageColorspace:

    def test_cmyk_converted_to_rgb(self):
        """CMYK 圖片應被轉換為 RGB，副檔名改為 png。"""
        from PIL import Image

        cmyk_bytes = _make_image_bytes("CMYK", "TIFF")
        result_bytes, result_ext = _normalize_image_colorspace(cmyk_bytes, "tiff")

        assert result_ext == "png"
        converted = Image.open(io.BytesIO(result_bytes))
        assert converted.mode == "RGB"

    def test_cmyk_result_savable_as_png(self):
        """轉換後的圖片必須能正常存成 PNG（重現原始失敗場景）。"""
        from PIL import Image

        cmyk_bytes = _make_image_bytes("CMYK", "TIFF")
        result_bytes, _ = _normalize_image_colorspace(cmyk_bytes, "tiff")

        img = Image.open(io.BytesIO(result_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")  # 不應拋出例外
        assert buf.getvalue()

    def test_rgb_image_unchanged(self):
        """已經是 RGB 的圖片不應被修改。"""
        rgb_bytes = _make_image_bytes("RGB", "PNG")
        result_bytes, result_ext = _normalize_image_colorspace(rgb_bytes, "png")

        assert result_bytes == rgb_bytes
        assert result_ext == "png"

    def test_rgba_image_unchanged(self):
        rgba_bytes = _make_image_bytes("RGBA", "PNG")
        result_bytes, result_ext = _normalize_image_colorspace(rgba_bytes, "png")

        assert result_bytes == rgba_bytes
        assert result_ext == "png"

    def test_palette_mode_converted(self):
        """調色盤模式（P）也應轉換為 RGB，避免邊緣案例。"""
        from PIL import Image

        p_bytes = _make_image_bytes("P", "PNG")
        result_bytes, result_ext = _normalize_image_colorspace(p_bytes, "png")

        converted = Image.open(io.BytesIO(result_bytes))
        assert converted.mode == "RGB"
        assert result_ext == "png"

    def test_invalid_bytes_returns_original_gracefully(self):
        """無法解析的 bytes 不應拋出例外，應靜默回傳原始內容。"""
        garbage = b"not a real image"
        result_bytes, result_ext = _normalize_image_colorspace(garbage, "png")

        assert result_bytes == garbage
        assert result_ext == "png"

    def test_grayscale_mode_unchanged(self):
        """灰階圖片原生相容 PNG，不需轉換。"""
        gray_bytes = _make_image_bytes("L", "PNG")
        result_bytes, result_ext = _normalize_image_colorspace(gray_bytes, "png")

        assert result_bytes == gray_bytes
        assert result_ext == "png"
