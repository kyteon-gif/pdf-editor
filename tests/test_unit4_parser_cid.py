"""
tests/test_unit4_parser_cid.py
Unit 4 補強 — parser.py 的 cid 亂碼偵測邏輯。

背景：部分 PDF（常見於 DOCX 轉檔但嵌入子集字型缺少完整 ToUnicode
CMap）會讓 pdfplumber 抓出 "(cid:927)" 這類原始字型內部編碼而非
可讀文字。_is_cid_garbled() 用來偵測這種情況，texts block 會帶上
encoding_warning 欄位供前端標示「需人工確認」。

執行：
    pytest tests/test_unit4_parser_cid.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pdf_editor.services.parser import _is_cid_garbled


class TestIsCidGarbled:
    def test_pure_cid_text_is_garbled(self):
        assert _is_cid_garbled("(cid:927)(cid:1283)(cid:2123)") is True

    def test_normal_chinese_text_not_garbled(self):
        assert _is_cid_garbled("這是正常的中文內文") is False

    def test_normal_english_text_not_garbled(self):
        assert _is_cid_garbled("This is normal text") is False

    def test_low_ratio_cid_not_garbled(self):
        """單一 cid 片段混在長正常文字中，比例低於門檻不算亂碼。"""
        text = "(cid:1)" + "正常文字" * 10
        assert _is_cid_garbled(text) is False

    def test_high_ratio_cid_is_garbled(self):
        """cid 片段佔比超過 30% 視為亂碼。"""
        text = "正常文字(cid:99)正常文字正常文字"
        assert _is_cid_garbled(text) is True

    def test_empty_string_not_garbled(self):
        assert _is_cid_garbled("") is False

    def test_numbers_and_percent_not_garbled(self):
        assert _is_cid_garbled("123.45%") is False

    def test_multiple_cid_tokens_garbled(self):
        text = "(cid:1)(cid:2)(cid:3)(cid:4)(cid:5)"
        assert _is_cid_garbled(text) is True

    def test_cid_like_but_not_matching_pattern(self):
        """字串含 'cid' 字樣但不符合 (cid:N) 格式不應誤判。"""
        assert _is_cid_garbled("this is a valid cid string") is False

    def test_boundary_threshold(self):
        """剛好在門檻邊緣的案例：30% 為判定標準。"""
        text = "(cid:1)" + "x" * 16
        assert len(text) == 23
        assert _is_cid_garbled(text) is True
