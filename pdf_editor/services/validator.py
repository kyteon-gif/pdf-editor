"""
services/validator.py — 數值一致性驗證（純 rule-based，不需模型）

職責：
1. 表格列級驗證：小計 = 單價 × 數量
2. 表格列總和驗證：總計 = Σ 小計
3. 總覽頁聯動驗證：子表格 total 是否等於總覽頁對應欄位數值
4. 回傳結構化的驗證結果（issues 清單），不擅自修正數值

欄位辨識策略：
- 透過表頭關鍵字（中英文皆支援）定位「單價」「數量」「小計」欄位索引
- 找不到對應欄位時跳過該項檢查，不視為錯誤（可能是非報價類表格）

容許誤差：
- 浮點數比較使用相對誤差 1e-6 加上絕對誤差 0.01（避免四捨五入造成誤判）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── 欄位關鍵字（依優先順序比對，第一個命中即採用）────────────
_COL_KEYWORDS = {
    "unit_price": ["單價", "price", "unit price"],
    "quantity":   ["數量", "qty", "quantity"],
    "subtotal":   ["小計", "subtotal", "sub-total"],
    "item_name":  ["品名", "項目", "name", "item"],
}

_TOTAL_ROW_KEYWORDS = ("總計", "合計", "total", "grand total")

_FLOAT_REL_TOL = 1e-6
_FLOAT_ABS_TOL = 0.01


@dataclass
class ValidationIssue:
    """單一驗證問題。"""
    block_id: str
    severity: str           # "error" | "warning"
    code: str                # 機器可讀代碼，e.g. "SUBTOTAL_MISMATCH"
    message: str              # 人類可讀說明
    row_index: Optional[int] = None
    expected: Optional[float] = None
    actual: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """整份文件的驗證結果。"""
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> dict:
        return {
            "is_valid":      self.is_valid,
            "error_count":   self.error_count,
            "warning_count": self.warning_count,
            "issues":        [i.to_dict() for i in self.issues],
        }


class Validator:

    # ── 公開入口 ──────────────────────────────────────────────

    @classmethod
    def validate_document(cls, doc: dict) -> ValidationResult:
        """
        驗證整份文件（CacheManager.load() 的回傳格式）。
        檢查所有表格的列級小計、表格總計、總覽頁聯動。
        """
        result = ValidationResult()
        tables = doc.get("tables", {})

        for blk_id, blk in tables.items():
            if blk.get("type") not in ("table", "overview"):
                continue
            cls._validate_table_rows(blk_id, blk, result)

        cls._validate_overview_links(tables, result)

        return result

    @classmethod
    def validate_table(cls, block_id: str, table_blk: dict) -> ValidationResult:
        """只驗證單一表格（供 PATCH 後即時檢查使用）。"""
        result = ValidationResult()
        cls._validate_table_rows(block_id, table_blk, result)
        return result

    # ── 列級驗證：小計 = 單價 × 數量 ──────────────────────────

    @classmethod
    def _validate_table_rows(cls, block_id: str, blk: dict, result: ValidationResult) -> None:
        rows = blk.get("raw_rows", [])
        if len(rows) < 2:
            return   # 只有表頭或空表格，無需驗證

        header, *body_rows = rows
        col_map = cls._map_columns(header)

        price_idx = col_map.get("unit_price")
        qty_idx   = col_map.get("quantity")
        sub_idx   = col_map.get("subtotal")

        subtotal_sum = 0.0
        has_valid_subtotal = False

        for i, row in enumerate(body_rows):
            if cls._is_total_row(row):
                cls._validate_grand_total(block_id, row, sub_idx, subtotal_sum, has_valid_subtotal, result)
                continue

            if price_idx is None or qty_idx is None or sub_idx is None:
                continue   # 欄位辨識失敗，跳過列級檢查

            price = cls._parse_number(row, price_idx)
            qty   = cls._parse_number(row, qty_idx)
            sub   = cls._parse_number(row, sub_idx)

            if price is None or qty is None or sub is None:
                continue   # 該列數值無法解析（可能是空白列），跳過

            expected = price * qty
            if not cls._is_close(expected, sub):
                result.issues.append(ValidationIssue(
                    block_id   = block_id,
                    severity   = "error",
                    code       = "SUBTOTAL_MISMATCH",
                    message    = f"第 {i+1} 列小計不符：單價 {price} × 數量 {qty} = {expected}，但實際為 {sub}",
                    row_index  = i,
                    expected   = expected,
                    actual     = sub,
                ))
            else:
                subtotal_sum += sub
                has_valid_subtotal = True

    @classmethod
    def _validate_grand_total(
        cls, block_id: str, total_row: list,
        sub_idx: Optional[int], subtotal_sum: float,
        has_valid_subtotal: bool, result: ValidationResult,
    ) -> None:
        """驗證「總計」列數值是否等於各列小計之和。"""
        if sub_idx is None or not has_valid_subtotal:
            return

        actual_total = cls._parse_number(total_row, sub_idx)
        if actual_total is None:
            return

        if not cls._is_close(subtotal_sum, actual_total):
            result.issues.append(ValidationIssue(
                block_id = block_id,
                severity = "error",
                code     = "GRAND_TOTAL_MISMATCH",
                message  = f"總計不符：各列小計合計為 {subtotal_sum}，但總計列顯示 {actual_total}",
                expected = subtotal_sum,
                actual   = actual_total,
            ))

    # ── 總覽頁聯動驗證 ────────────────────────────────────────

    @classmethod
    def _validate_overview_links(cls, tables: dict, result: ValidationResult) -> None:
        for blk_id, blk in tables.items():
            overview_id   = blk.get("linked_overview_block")
            overview_cell = blk.get("linked_overview_cell")
            sub_total     = blk.get("total")

            if not overview_id or not overview_cell:
                continue

            overview = tables.get(overview_id)
            if overview is None:
                result.issues.append(ValidationIssue(
                    block_id = blk_id,
                    severity = "warning",
                    code     = "OVERVIEW_BLOCK_MISSING",
                    message  = f"找不到聯動的總覽表 {overview_id}",
                ))
                continue

            cell_value = cls._read_cell(overview.get("raw_rows", []), overview_cell)
            if cell_value is None:
                result.issues.append(ValidationIssue(
                    block_id = blk_id,
                    severity = "warning",
                    code     = "OVERVIEW_CELL_MISSING",
                    message  = f"總覽表 {overview_id} 找不到儲存格 {overview_cell}",
                ))
                continue

            if sub_total is not None and not cls._is_close(sub_total, cell_value):
                result.issues.append(ValidationIssue(
                    block_id = blk_id,
                    severity = "error",
                    code     = "OVERVIEW_LINK_MISMATCH",
                    message  = (
                        f"總覽聯動不符：子表格總計為 {sub_total}，"
                        f"但總覽表 {overview_id}[{overview_cell}] 顯示 {cell_value}"
                    ),
                    expected = sub_total,
                    actual   = cell_value,
                ))

    # ── 欄位辨識 ──────────────────────────────────────────────

    @classmethod
    def _map_columns(cls, header: list[str]) -> dict[str, int]:
        """依表頭文字比對 _COL_KEYWORDS，回傳 {role: column_index}。"""
        col_map: dict[str, int] = {}
        for idx, cell in enumerate(header):
            cell_norm = str(cell).strip().lower()
            for role, keywords in _COL_KEYWORDS.items():
                if role in col_map:
                    continue
                if any(kw.lower() in cell_norm for kw in keywords):
                    col_map[role] = idx
        return col_map

    @classmethod
    def _is_total_row(cls, row: list) -> bool:
        if not row:
            return False
        first_cell = str(row[0]).strip().lower()
        return any(kw.lower() in first_cell for kw in _TOTAL_ROW_KEYWORDS)

    # ── 數值解析工具 ──────────────────────────────────────────

    @classmethod
    def _parse_number(cls, row: list, idx: int) -> Optional[float]:
        if idx >= len(row):
            return None
        raw = str(row[idx]).strip()
        if raw == "":
            return None
        # 移除千分位逗號與貨幣符號
        cleaned = re.sub(r"[,$NT＄\s]", "", raw)
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _read_cell(cls, sheet: list[list], cell_ref: str) -> Optional[float]:
        """cell_ref 格式如 'B3'：欄位字母 + 列號（1-indexed）。"""
        m = re.match(r"^([A-Za-z]+)(\d+)$", cell_ref.strip())
        if not m:
            return None
        col_letters, row_num = m.groups()
        col = 0
        for ch in col_letters.upper():
            col = col * 26 + (ord(ch) - ord("A") + 1)
        col -= 1
        row = int(row_num) - 1

        if row < 0 or row >= len(sheet):
            return None
        if col < 0 or col >= len(sheet[row]):
            return None

        raw = str(sheet[row][col]).strip()
        cleaned = re.sub(r"[,$NT＄\s]", "", raw)
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _is_close(cls, a: float, b: float) -> bool:
        return abs(a - b) <= max(_FLOAT_ABS_TOL, _FLOAT_REL_TOL * max(abs(a), abs(b)))
