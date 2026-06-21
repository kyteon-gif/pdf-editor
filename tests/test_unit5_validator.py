"""
tests/test_unit5_validator.py
Unit 5 — services/validator：列級小計、總計、總覽聯動驗證。

執行：
    pytest tests/test_unit5_validator.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pdf_editor.services.validator import Validator, ValidationIssue, ValidationResult


# ── ValidationResult / ValidationIssue ──────────────────────

class TestValidationResult:
    def test_empty_is_valid(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_error_makes_invalid(self):
        r = ValidationResult()
        r.issues.append(ValidationIssue("blk-1", "error", "X", "msg"))
        assert r.is_valid is False
        assert r.error_count == 1

    def test_warning_does_not_invalidate(self):
        r = ValidationResult()
        r.issues.append(ValidationIssue("blk-1", "warning", "X", "msg"))
        assert r.is_valid is True
        assert r.warning_count == 1

    def test_to_dict_schema(self):
        r = ValidationResult()
        r.issues.append(ValidationIssue("blk-1", "error", "X", "msg", row_index=2, expected=10.0, actual=9.0))
        d = r.to_dict()
        assert d["is_valid"] is False
        assert d["error_count"] == 1
        assert d["issues"][0]["row_index"] == 2


# ── 列級小計驗證 ──────────────────────────────────────────────

def _table(rows, btype="table", linked_block=None, linked_cell=None, total=None):
    return {
        "id": "tbl-001", "type": btype, "page": 1,
        "raw_rows": rows,
        "linked_overview_block": linked_block,
        "linked_overview_cell":  linked_cell,
        "total": total,
    }


class TestRowSubtotal:
    def test_correct_subtotal_no_issue(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["鋼板", "1200", "10", "12000"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_wrong_subtotal_reports_error(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["鋼板", "1200", "10", "99999"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert not result.is_valid
        assert result.issues[0].code == "SUBTOTAL_MISMATCH"
        assert result.issues[0].expected == 12000.0
        assert result.issues[0].actual   == 99999.0

    def test_multiple_rows_multiple_errors(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["A", "100", "2", "999"],   # wrong
            ["B", "50",  "3", "150"],   # correct
            ["C", "10",  "5", "1"],     # wrong
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        errors = [i for i in result.issues if i.code == "SUBTOTAL_MISMATCH"]
        assert len(errors) == 2

    def test_english_headers_recognized(self):
        rows = [
            ["Item", "Unit Price", "Qty", "Subtotal"],
            ["Bolt", "10", "5", "50"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_currency_symbols_and_commas_parsed(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["鋼板", "$1,200", "10", "NT$12,000"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_missing_column_skips_check(self):
        """找不到單價/數量欄位時，不報錯（非報價類表格）。"""
        rows = [
            ["備註", "說明"],
            ["A", "測試內容"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_empty_cell_skipped_not_error(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["鋼板", "", "10", ""],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_only_header_no_rows(self):
        rows = [["品名", "單價", "數量", "小計"]]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_floating_point_tolerance(self):
        """浮點誤差在容許範圍內不應報錯。"""
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["鋼板", "33.33", "3", "99.99"],   # 33.33*3 = 99.99 exactly here
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid


# ── 總計列驗證 ────────────────────────────────────────────────

class TestGrandTotal:
    def test_correct_grand_total(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["A", "100", "2", "200"],
            ["B", "50",  "3", "150"],
            ["總計", "", "", "350"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        assert result.is_valid

    def test_wrong_grand_total_reports_error(self):
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["A", "100", "2", "200"],
            ["B", "50",  "3", "150"],
            ["總計", "", "", "999"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        codes = [i.code for i in result.issues]
        assert "GRAND_TOTAL_MISMATCH" in codes

    def test_total_keyword_variants(self):
        for kw in ("總計", "合計", "Total", "Grand Total"):
            rows = [
                ["品名", "單價", "數量", "小計"],
                ["A", "10", "2", "20"],
                [kw, "", "", "20"],
            ]
            result = Validator.validate_table("tbl-001", _table(rows))
            assert result.is_valid, f"{kw} 總計列未被正確驗證"

    def test_total_row_excluded_from_subtotal_check(self):
        """總計列本身不應被當成一般列做小計驗證（避免誤判）。"""
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["A", "10", "2", "20"],
            ["總計", "", "", "20"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        subtotal_errors = [i for i in result.issues if i.code == "SUBTOTAL_MISMATCH"]
        assert len(subtotal_errors) == 0

    def test_grand_total_skipped_if_no_valid_rows(self):
        """若所有列都有小計錯誤，不做總計加總比對（避免雙重報錯混淆）。"""
        rows = [
            ["品名", "單價", "數量", "小計"],
            ["A", "10", "2", "999"],   # wrong subtotal
            ["總計", "", "", "999"],
        ]
        result = Validator.validate_table("tbl-001", _table(rows))
        codes = [i.code for i in result.issues]
        assert "GRAND_TOTAL_MISMATCH" not in codes


# ── 總覽頁聯動驗證 ────────────────────────────────────────────

class TestOverviewLink:
    def _doc(self, sub_total, overview_rows, linked_cell="B2"):
        return {
            "tables": {
                "tbl-sub": _table(
                    [["品名", "單價", "數量", "小計"], ["A", "10", "2", "20"]],
                    linked_block="tbl-overview",
                    linked_cell=linked_cell,
                    total=sub_total,
                ),
                "tbl-overview": _table(overview_rows, btype="overview"),
            }
        }

    def test_matching_link_no_error(self):
        doc = self._doc(20.0, [["項目", "金額"], ["A工程", "20"]])
        result = Validator.validate_document(doc)
        link_errors = [i for i in result.issues if i.code == "OVERVIEW_LINK_MISMATCH"]
        assert len(link_errors) == 0

    def test_mismatched_link_reports_error(self):
        doc = self._doc(20.0, [["項目", "金額"], ["A工程", "999"]])
        result = Validator.validate_document(doc)
        link_errors = [i for i in result.issues if i.code == "OVERVIEW_LINK_MISMATCH"]
        assert len(link_errors) == 1
        assert link_errors[0].expected == 20.0
        assert link_errors[0].actual   == 999.0

    def test_missing_overview_block_warning(self):
        doc = {
            "tables": {
                "tbl-sub": _table(
                    [["品名"], ["A"]],
                    linked_block="tbl-nonexistent",
                    linked_cell="B2",
                    total=20.0,
                ),
            }
        }
        result = Validator.validate_document(doc)
        codes = [i.code for i in result.issues]
        assert "OVERVIEW_BLOCK_MISSING" in codes
        # warning 不影響 is_valid
        assert result.is_valid

    def test_missing_cell_warning(self):
        doc = self._doc(20.0, [["項目", "金額"]], linked_cell="B99")
        result = Validator.validate_document(doc)
        codes = [i.code for i in result.issues]
        assert "OVERVIEW_CELL_MISSING" in codes

    def test_no_link_no_validation(self):
        """沒有 linked_overview_block 的表格不應觸發任何聯動檢查。"""
        doc = {
            "tables": {
                "tbl-001": _table([["品名", "單價", "數量", "小計"], ["A", "10", "2", "20"]]),
            }
        }
        result = Validator.validate_document(doc)
        link_codes = [i.code for i in result.issues if "OVERVIEW" in i.code]
        assert link_codes == []


# ── validate_document() 整合測試 ──────────────────────────────

class TestValidateDocument:
    def test_empty_document_is_valid(self):
        result = Validator.validate_document({"tables": {}})
        assert result.is_valid

    def test_non_table_blocks_ignored(self):
        doc = {
            "tables": {
                "txt-001": {"id": "txt-001", "type": "body", "raw_rows": []},
            }
        }
        result = Validator.validate_document(doc)
        assert result.is_valid

    def test_multiple_tables_aggregated(self):
        doc = {
            "tables": {
                "tbl-A": _table([["品名","單價","數量","小計"], ["X","10","2","999"]]),
                "tbl-B": _table([["品名","單價","數量","小計"], ["Y","5","4","20"]]),
            }
        }
        result = Validator.validate_document(doc)
        assert result.error_count == 1
        assert result.issues[0].block_id == "tbl-A"


# ── 內部工具函式 ──────────────────────────────────────────────

class TestInternalHelpers:
    def test_map_columns_chinese(self):
        col_map = Validator._map_columns(["品名", "單價", "數量", "小計"])
        assert col_map["unit_price"] == 1
        assert col_map["quantity"]   == 2
        assert col_map["subtotal"]   == 3

    def test_map_columns_english(self):
        col_map = Validator._map_columns(["Item", "Unit Price", "Qty", "Subtotal"])
        assert col_map["unit_price"] == 1
        assert col_map["quantity"]   == 2

    def test_parse_number_with_comma(self):
        assert Validator._parse_number(["1,200"], 0) == 1200.0

    def test_parse_number_with_currency(self):
        assert Validator._parse_number(["NT$500"], 0) == 500.0

    def test_parse_number_empty_returns_none(self):
        assert Validator._parse_number([""], 0) is None

    def test_parse_number_invalid_returns_none(self):
        assert Validator._parse_number(["abc"], 0) is None

    def test_read_cell_basic(self):
        sheet = [["項目", "金額"], ["工程A", "1000"]]
        assert Validator._read_cell(sheet, "B2") == 1000.0

    def test_read_cell_out_of_range(self):
        sheet = [["項目", "金額"]]
        assert Validator._read_cell(sheet, "B99") is None

    def test_read_cell_invalid_format(self):
        sheet = [["項目", "金額"], ["A", "100"]]
        assert Validator._read_cell(sheet, "invalid") is None

    def test_is_close_within_tolerance(self):
        assert Validator._is_close(100.0, 100.005) is True

    def test_is_close_outside_tolerance(self):
        assert Validator._is_close(100.0, 105.0) is False

    def test_is_total_row_keywords(self):
        assert Validator._is_total_row(["總計", "", "100"]) is True
        assert Validator._is_total_row(["Total", "", "100"]) is True
        assert Validator._is_total_row(["一般項目", "10", "100"]) is False
