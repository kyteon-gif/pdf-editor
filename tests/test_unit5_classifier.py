"""
tests/test_unit5_classifier.py
Unit 5：驗證 Classifier 的分類邏輯。

測試策略：
- 不依賴實際模型（rule-based path 不需要模型）
- 直接構造 texts dict 驗證 _rule_based_type 邏輯
- 驗證 classify_blocks() 的輸出結構正確性
- 若模型存在，額外驗證 model path 的輸出合法性

執行：
    pytest tests/test_unit5_classifier.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 強制推到最前面，蓋過環境裡已安裝的同名套件


# 確保專案根目錄在 sys.path 最前面（macOS/miniforge 防禦）
import pytest
from pdf_editor.models.document import BlockType
from pdf_editor.services.classifier import Classifier


# ── 輔助工具 ──────────────────────────────────────────────────

def _make_blk(content="", font_size=12.0, page=1, y0=300.0, blk_type="unknown"):
    return {
        "id":        "blk-test",
        "type":      blk_type,
        "page":      page,
        "bbox":      [72.0, y0, 500.0, y0 + 20],
        "content":   content,
        "font_size": font_size,
        "font_name": "Arial",
    }


def _make_parsed(text_blocks: list[dict], table_blocks: list[dict] = None) -> dict:
    texts  = {blk["id"]: blk for blk in text_blocks}
    tables = {blk["id"]: blk for blk in (table_blocks or [])}
    return {
        "doc_id":     "test-hash",
        "filename":   "test.pdf",
        "page_count": 1,
        "texts":      texts,
        "tables":     tables,
        "images":     {},
        "structure":  list(texts.keys()) + list(tables.keys()),
    }


# ── Rule-based 分類邏輯測試 ────────────────────────────────────

class TestRuleBasedType:

    def test_cover_large_font_page1_top(self):
        blk = _make_blk(content="公司名稱 報價單", font_size=20, page=1, y0=80)
        assert Classifier._rule_based_type(blk) == BlockType.COVER

    def test_heading1_large_font(self):
        blk = _make_blk(content="第一章 工程範圍", font_size=18, page=2)
        assert Classifier._rule_based_type(blk) == BlockType.HEADING1

    def test_heading2_medium_font(self):
        blk = _make_blk(content="1.1 施工方法", font_size=14, page=2)
        assert Classifier._rule_based_type(blk) == BlockType.HEADING2

    def test_body_small_font(self):
        blk = _make_blk(content="本次工程範圍包含廠區東側結構補強作業", font_size=11)
        assert Classifier._rule_based_type(blk) == BlockType.BODY

    def test_appendix_keyword(self):
        blk = _make_blk(content="附錄一 材料規格表", font_size=12)
        assert Classifier._rule_based_type(blk) == BlockType.APPENDIX

    def test_appendix_english_keyword(self):
        blk = _make_blk(content="Appendix A: Specifications", font_size=12)
        assert Classifier._rule_based_type(blk) == BlockType.APPENDIX

    def test_overview_keyword(self):
        blk = _make_blk(content="工程費用總覽", font_size=14, page=2)
        # overview 優先於 heading2（font_size=14）
        assert Classifier._rule_based_type(blk) == BlockType.OVERVIEW

    def test_numbered_heading(self):
        blk = _make_blk(content="一、工程說明", font_size=12)
        assert Classifier._rule_based_type(blk) == BlockType.HEADING1

    def test_dot_numbered_heading(self):
        blk = _make_blk(content="1. 施工概要", font_size=12)
        assert Classifier._rule_based_type(blk) == BlockType.HEADING1

    def test_image_type_not_reclassified(self):
        """image type 的 placeholder 不應被 rule-based 覆蓋。"""
        blk = _make_blk(content="", blk_type=BlockType.IMAGE)
        # _classify_rule_based 會跳過 image，此測試確認邏輯不變
        parsed = _make_parsed([blk])
        Classifier._classify_rule_based(parsed["texts"])
        assert parsed["texts"]["blk-test"]["type"] == BlockType.IMAGE


# ── classify_blocks() 輸出結構測試 ────────────────────────────

class TestClassifyBlocks:

    def test_returns_texts_dict(self):
        parsed = _make_parsed([
            _make_blk(content="封面標題", font_size=20, page=1, y0=80),
            _make_blk(content="內文段落", font_size=11),
        ])
        # 給各 block 唯一 id
        ids = ["blk-001", "blk-002"]
        for i, (k, v) in enumerate(parsed["texts"].items()):
            v["id"] = ids[i]
        parsed["texts"] = {v["id"]: v for v in parsed["texts"].values()}

        result = Classifier.classify_blocks(parsed)
        assert isinstance(result, dict)

    def test_all_blocks_have_valid_type(self):
        blocks = [
            {**_make_blk(content="標題", font_size=18, page=1, y0=80), "id": "blk-001"},
            {**_make_blk(content="內文", font_size=11), "id": "blk-002"},
            {**_make_blk(content="附錄", font_size=12), "id": "blk-003"},
        ]
        parsed = _make_parsed(blocks)
        result = Classifier.classify_blocks(parsed)
        for blk_id, blk in result.items():
            assert blk["type"] in BlockType.ALL, (
                f"{blk_id} 的 type={blk['type']} 不在合法清單中"
            )

    def test_table_blocks_marked_as_table(self):
        """表格區塊應被標記為 table。"""
        tbl_blk = {
            "id":        "tbl-001",
            "type":      "unknown",
            "page":      1,
            "bbox":      [72, 300, 500, 420],
            "raw_rows":  [["品名", "單價"], ["鋼板", "1200"]],
        }
        parsed = _make_parsed([], [tbl_blk])
        Classifier.classify_blocks(parsed)
        assert parsed["tables"]["tbl-001"]["type"] == BlockType.TABLE

    def test_image_placeholder_preserved(self):
        """圖片 placeholder 的 type 應保持 image。"""
        img_blk = {**_make_blk(content="", blk_type=BlockType.IMAGE), "id": "img-001"}
        parsed = _make_parsed([img_blk])
        result = Classifier.classify_blocks(parsed)
        assert result["img-001"]["type"] == BlockType.IMAGE

    def test_empty_parsed_no_error(self):
        """空白文件不應拋出例外。"""
        parsed = _make_parsed([])
        try:
            Classifier.classify_blocks(parsed)
        except Exception as e:
            pytest.fail(f"空白文件不應拋出例外：{e}")


# ── _build_prompt 測試 ────────────────────────────────────────

class TestBuildPrompt:

    def test_prompt_contains_content(self):
        blk = _make_blk(content="施工說明", font_size=12)
        prompt = Classifier._build_prompt(blk)
        assert "施工說明" in prompt

    def test_large_font_hint_in_prompt(self):
        blk = _make_blk(content="大標題", font_size=20)
        prompt = Classifier._build_prompt(blk)
        assert "大字體" in prompt or "標題" in prompt

    def test_page1_hint_in_prompt(self):
        blk = _make_blk(content="封面", font_size=18, page=1, y0=50)
        prompt = Classifier._build_prompt(blk)
        assert "首頁" in prompt or "頂部" in prompt

    def test_long_content_truncated(self):
        long_content = "x" * 200
        blk = _make_blk(content=long_content)
        prompt = Classifier._build_prompt(blk)
        # 確認 prompt 長度受控
        assert len(prompt) < 300
