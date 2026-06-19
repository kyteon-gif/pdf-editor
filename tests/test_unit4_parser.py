"""
tests/test_unit4_parser.py
Unit 4：驗證 parser.parse_pdf() 的解析結果。

測試策略：
- 用 reportlab 動態產生一個含「封面標題、段落、簡單表格」的最小 PDF，
  不依賴外部檔案，確保 CI 環境可獨立執行。
- 若 reportlab 不可用，改用 PyMuPDF 產生測試 PDF。
- 驗證 doc_id、page_count、texts/tables/structure 的結構正確性。

執行：
    pytest tests/test_unit4_parser.py -v
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 強制推到最前面，蓋過環境裡已安裝的同名套件


# 確保專案根目錄在 sys.path 最前面（macOS/miniforge 防禦）
import pytest
import hashlib


# ── 測試 PDF 產生 ──────────────────────────────────────────────

def _make_test_pdf_bytes() -> bytes:
    """產生一個含標題、段落、表格的最小測試 PDF。優先用 reportlab，fallback 用 fitz。"""
    try:
        return _make_pdf_reportlab()
    except ImportError:
        pass
    try:
        return _make_pdf_fitz()
    except ImportError:
        pytest.skip("需要 reportlab 或 pymupdf 才能建立測試 PDF")


def _make_pdf_reportlab() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("測試文件封面標題", styles["Title"]),
        Spacer(1, 12),
        Paragraph("這是第一段內文，用來測試文字區塊擷取功能是否正常運作。", styles["Normal"]),
        Spacer(1, 8),
        Table(
            [["品名", "單價", "數量", "小計"],
             ["鋼板 A", "1200", "10", "12000"],
             ["螺絲組", "80",   "50",  "4000"],
             ["總計",   "",     "",   "16000"]],
            colWidths=[100, 80, 60, 80],
        ),
    ]
    doc.build(story)
    return buf.getvalue()


def _make_pdf_fitz() -> bytes:
    """fitz fallback 使用英文，避免預設字型不支援中文導致輸出為點。"""
    import fitz, io
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100),  "TEST DOCUMENT TITLE", fontsize=20)
    page.insert_text((72, 160),  "This is the first paragraph for testing text extraction.", fontsize=12)
    rows = [
        ("Item",    "Price", "Qty", "Subtotal"),
        ("Steel A", "1200",  "10",  "12000"),
        ("Bolts",   "80",    "50",  "4000"),
        ("Total",   "",      "",    "16000"),
    ]
    y = 220
    for row in rows:
        x = 72
        for cell in row:
            page.insert_text((x, y), cell, fontsize=11)
            x += 110
        y += 20
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pdf_bytes():
    return _make_test_pdf_bytes()


@pytest.fixture(scope="module")
def parsed(pdf_bytes):
    from pdf_editor.services.parser import parse_pdf
    return parse_pdf(pdf_bytes, filename="test.pdf")


# ── Tests ──────────────────────────────────────────────────────

class TestParsedDocId:
    def test_doc_id_is_sha256(self, parsed, pdf_bytes):
        expected = hashlib.sha256(pdf_bytes).hexdigest()
        assert parsed["doc_id"] == expected

    def test_filename_preserved(self, parsed):
        assert parsed["filename"] == "test.pdf"

    def test_page_count_positive(self, parsed):
        assert parsed["page_count"] >= 1


class TestParsedTexts:
    def test_texts_is_dict(self, parsed):
        assert isinstance(parsed["texts"], dict)

    def test_at_least_one_text_block(self, parsed):
        # 排除 image type
        real_texts = {k: v for k, v in parsed["texts"].items()
                      if v.get("type") != "image"}
        assert len(real_texts) >= 1, "應至少解析出一個文字區塊"

    def test_text_block_schema(self, parsed):
        """每個文字區塊都有必要欄位。"""
        required = {"id", "type", "page", "bbox", "content"}
        for blk_id, blk in parsed["texts"].items():
            missing = required - set(blk.keys())
            assert not missing, f"{blk_id} 缺少欄位: {missing}"

    def test_text_block_bbox_has_4_values(self, parsed):
        for blk_id, blk in parsed["texts"].items():
            bbox = blk.get("bbox", [])
            assert len(bbox) == 4, f"{blk_id}.bbox 應有 4 個值，得到 {bbox}"

    def test_text_block_page_positive(self, parsed):
        for blk_id, blk in parsed["texts"].items():
            assert blk["page"] >= 1, f"{blk_id}.page 應 >= 1"

    def test_title_text_found(self, parsed):
        """解析結果中應能找到封面標題的文字內容。"""
        all_content = " ".join(
            blk["content"] for blk in parsed["texts"].values()
        )
        # reportlab 產生中文，fitz fallback 產生英文
        found = (
            "測試" in all_content or "標題" in all_content or
            "TEST" in all_content or "TITLE" in all_content or
            "Document" in all_content or "paragraph" in all_content
        )
        assert found, f"找不到標題文字，全部內容：{all_content[:200]}"


class TestParsedTables:
    def test_tables_is_dict(self, parsed):
        assert isinstance(parsed["tables"], dict)

    def test_table_block_schema(self, parsed):
        """若有表格，每個都有必要欄位。"""
        required = {"id", "type", "page", "bbox", "raw_rows"}
        for blk_id, tbl in parsed["tables"].items():
            missing = required - set(tbl.keys())
            assert not missing, f"{blk_id} 缺少欄位: {missing}"

    def test_table_rows_are_list_of_list(self, parsed):
        for blk_id, tbl in parsed["tables"].items():
            assert isinstance(tbl["raw_rows"], list), f"{blk_id}.raw_rows 應為 list"
            for row in tbl["raw_rows"]:
                assert isinstance(row, list), f"{blk_id} row 應為 list，得到 {type(row)}"


class TestParsedImages:
    def test_images_is_dict(self, parsed):
        assert isinstance(parsed["images"], dict)

    def test_image_values_are_bytes(self, parsed):
        for blk_id, img_bytes in parsed["images"].items():
            assert isinstance(img_bytes, bytes), f"{blk_id} image 應為 bytes"
            assert len(img_bytes) > 0, f"{blk_id} image bytes 不應為空"


class TestParsedStructure:
    def test_structure_is_list(self, parsed):
        assert isinstance(parsed["structure"], list)

    def test_structure_no_duplicates(self, parsed):
        s = parsed["structure"]
        assert len(s) == len(set(s)), "structure 中有重複的 block_id"

    def test_structure_ids_exist_in_texts_or_tables(self, parsed):
        all_ids = set(parsed["texts"].keys()) | set(parsed["tables"].keys())
        for blk_id in parsed["structure"]:
            assert blk_id in all_ids, f"{blk_id} 在 structure 中但不在 texts/tables"

    def test_structure_sorted_by_page(self, parsed):
        """structure 中的 block 應依 page 遞增排列（同頁內依 y0）。"""
        texts  = parsed["texts"]
        tables = parsed["tables"]
        pages  = []
        for blk_id in parsed["structure"]:
            meta = texts.get(blk_id) or tables.get(blk_id) or {}
            pages.append(meta.get("page", 0))
        assert pages == sorted(pages), f"structure 未依頁碼排序：{pages}"


class TestDocIdConsistency:
    def test_same_bytes_same_doc_id(self, pdf_bytes):
        """相同 PDF bytes 應得到相同 doc_id（SHA-256 deterministic）。"""
        from pdf_editor.services.parser import parse_pdf
        r1 = parse_pdf(pdf_bytes, "a.pdf")
        r2 = parse_pdf(pdf_bytes, "b.pdf")
        assert r1["doc_id"] == r2["doc_id"]

    def test_different_bytes_different_doc_id(self, pdf_bytes):
        """不同 bytes 應得到不同 doc_id。"""
        from pdf_editor.services.parser import parse_pdf
        modified = pdf_bytes[:-10] + b"\x00" * 10
        r1 = parse_pdf(pdf_bytes,  "a.pdf")
        r2 = parse_pdf(modified,   "b.pdf")
        assert r1["doc_id"] != r2["doc_id"]
