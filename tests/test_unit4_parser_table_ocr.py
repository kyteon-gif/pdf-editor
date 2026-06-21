"""
tests/test_unit4_parser_table_ocr.py
Unit 4 修復 — 表格儲存格的 cid 亂碼偵測與 OCR 修正。

背景（重要修復）：表格擷取原本使用 pdfplumber 的 extract_tables()，
這個方法只回傳純文字內容、沒有每個儲存格的 bbox，導致表格完全
無法套用文字區塊已有的 cid 偵測／OCR fallback 機制。改用
find_tables() 後可取得逐格 bbox，讓 _correct_table_cells() 能對
每個儲存格個別檢查並修正。

執行：
    pytest tests/test_unit4_parser_table_ocr.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pdf_editor.services.parser import _correct_table_cells


def _make_fake_table(rows_cells):
    """建立一個假的 pdfplumber Table 物件，rows_cells 是每列的 cell bbox 清單。"""
    fake_table = MagicMock()
    fake_rows = []
    for cells in rows_cells:
        fake_row = MagicMock()
        fake_row.cells = cells
        fake_rows.append(fake_row)
    fake_table.rows = fake_rows
    return fake_table


class TestCorrectTableCells:

    def test_cid_cell_corrected_via_ocr(self):
        raw_rows = [
            ["正常表頭", "(cid:927)(cid:1283)(cid:2123)"],
            ["100", "200"],
        ]
        fake_table = _make_fake_table([
            [(0, 0, 50, 20), (50, 0, 100, 20)],
            [(0, 20, 50, 40), (50, 20, 100, 40)],
        ])

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr",
            return_value="正確內容",
        ):
            corrected, ocr_used, still_garbled = _correct_table_cells(
                fake_table, raw_rows, {1: MagicMock()}, 1
            )

        assert corrected[0][1] == "正確內容"
        assert corrected[0][0] == "正常表頭"
        assert ocr_used is True
        assert still_garbled is False

    def test_numeric_cells_untouched(self):
        raw_rows = [
            ["正常表頭", "(cid:927)"],
            ["100", "200"],
        ]
        fake_table = _make_fake_table([
            [(0, 0, 50, 20), (50, 0, 100, 20)],
            [(0, 20, 50, 40), (50, 20, 100, 40)],
        ])

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr",
            return_value="修正",
        ):
            corrected, _, _ = _correct_table_cells(
                fake_table, raw_rows, {1: MagicMock()}, 1
            )

        assert corrected[1] == ["100", "200"]

    def test_ocr_failure_keeps_original_and_flags_garbled(self):
        raw_rows = [["(cid:1)(cid:2)(cid:3)"]]
        fake_table = _make_fake_table([[(0, 0, 50, 20)]])

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr",
            return_value="",
        ):
            corrected, ocr_used, still_garbled = _correct_table_cells(
                fake_table, raw_rows, {1: MagicMock()}, 1
            )

        assert corrected[0][0] == raw_rows[0][0]
        assert ocr_used is False
        assert still_garbled is True

    def test_clean_table_never_calls_ocr(self):
        clean_rows = [["正常", "內容"], ["100", "200"]]
        fake_table = _make_fake_table([
            [(0, 0, 50, 20), (50, 0, 100, 20)],
            [(0, 20, 50, 40), (50, 20, 100, 40)],
        ])

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr"
        ) as mock_ocr:
            corrected, ocr_used, still_garbled = _correct_table_cells(
                fake_table, clean_rows, {1: MagicMock()}, 1
            )

        mock_ocr.assert_not_called()
        assert corrected == clean_rows
        assert ocr_used is False
        assert still_garbled is False

    def test_none_cell_bbox_skipped(self):
        """合併儲存格在 pdfplumber 中對應的 bbox 可能是 None，應跳過不處理。"""
        raw_rows = [["(cid:1)", "正常"]]
        fake_table = _make_fake_table([[None, (50, 0, 100, 20)]])

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr"
        ) as mock_ocr:
            corrected, _, _ = _correct_table_cells(
                fake_table, raw_rows, {1: MagicMock()}, 1
            )

        mock_ocr.assert_not_called()
        assert corrected[0][0] == "(cid:1)"

    def test_none_cell_text_skipped(self):
        """儲存格文字本身為 None（pdfplumber 常見於空白格）不應導致例外。"""
        raw_rows = [[None, "正常"]]
        fake_table = _make_fake_table([[(0, 0, 50, 20), (50, 0, 100, 20)]])

        corrected, ocr_used, still_garbled = _correct_table_cells(
            fake_table, raw_rows, {1: MagicMock()}, 1
        )

        assert corrected[0][0] is None
        assert ocr_used is False

    def test_mixed_garbled_and_clean_cells(self):
        raw_rows = [
            ["正常A", "(cid:1)", "正常B", "(cid:2)"],
        ]
        fake_table = _make_fake_table([[
            (0, 0, 25, 20), (25, 0, 50, 20), (50, 0, 75, 20), (75, 0, 100, 20),
        ]])

        call_count = {"n": 0}

        def mock_ocr_side_effect(*args, **kwargs):
            call_count["n"] += 1
            return f"修正{call_count['n']}"

        with patch(
            "pdf_editor.services.parser._extract_text_via_ocr",
            side_effect=mock_ocr_side_effect,
        ):
            corrected, ocr_used, still_garbled = _correct_table_cells(
                fake_table, raw_rows, {1: MagicMock()}, 1
            )

        assert corrected[0][0] == "正常A"
        assert corrected[0][1] == "修正1"
        assert corrected[0][2] == "正常B"
        assert corrected[0][3] == "修正2"
        assert ocr_used is True
        assert still_garbled is False
