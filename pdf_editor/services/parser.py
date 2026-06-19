"""
services/parser.py — PDF 解析引擎

職責：
1. 用 pdfplumber 擷取每頁的文字區塊（含 bbox、字型大小）
2. 用 pdfplumber 擷取表格結構（行列原始字串）
3. 用 PyMuPDF (fitz) 擷取嵌入圖片的二進位資料
4. 組合成 Document 物件回傳，供 classifier 進一步分類

注意：此模組只負責「擷取原始資料」，不做語意分類。
      類型標記（heading/body/table/image）由 classifier 負責。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── 公開入口 ──────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes, filename: str = "document.pdf") -> dict:
    """
    解析 PDF 二進位內容，回傳包含所有原始資料的 dict。

    回傳格式：
    {
        "doc_id":   str,           # SHA-256 hash
        "filename": str,
        "page_count": int,
        "texts":    { block_id: TextBlock },
        "tables":   { block_id: TableBlock },
        "images":   { block_id: bytes },
        "structure": [ block_id, ... ],   # 保留頁面與位置的排列順序
    }
    """
    doc_id = hashlib.sha256(file_bytes).hexdigest()
    logger.info("[Parser] 開始解析 %s (hash=%s…)", filename, doc_id[:12])

    texts:    dict = {}
    tables:   dict = {}
    images:   dict = {}
    structure: list = []

    try:
        import pdfplumber
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            f"缺少必要套件：{e}。請執行 pip install pdfplumber pymupdf"
        ) from e

    # ── Step 1：pdfplumber 擷取文字與表格 ─────────────────────
    with pdfplumber.open(file_bytes if isinstance(file_bytes, (str, Path))
                         else __bytes_to_stream(file_bytes)) as pdf:

        page_count = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages, start=1):
            logger.debug("[Parser] 處理第 %d/%d 頁", page_num, page_count)

            # ── 1a. 擷取表格（先擷取，後續排除這些區域的文字）──
            page_tables = page.extract_tables(
                table_settings={
                    "vertical_strategy":   "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance":      3,
                    "join_tolerance":      3,
                    "edge_min_length":     3,
                    "min_words_vertical":  1,
                    "min_words_horizontal": 1,
                }
            )

            table_bboxes: list[tuple] = []
            for tbl_raw in (page_tables or []):
                if not tbl_raw:
                    continue
                blk_id = _make_id("tbl", page_num, len(tables))
                tbl_bbox = _find_table_bbox(page, tbl_raw)
                table_bboxes.append(tbl_bbox)

                tables[blk_id] = {
                    "id":       blk_id,
                    "type":     "table",        # 預設；classifier 可能改為 overview
                    "page":     page_num,
                    "bbox":     list(tbl_bbox),
                    "raw_rows": _clean_table(tbl_raw),
                }
                structure.append(blk_id)

            # ── 1b. 擷取文字（排除表格區域）────────────────────
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True,
                extra_attrs=["size", "fontname"],
            ) or []

            # 依行分組
            lines = _group_words_to_lines(words, y_tolerance=4)

            for line_words in lines:
                if not line_words:
                    continue
                bbox = _words_bbox(line_words)
                # 若落在表格區域內則跳過
                if _in_any_bbox(bbox, table_bboxes, overlap_threshold=0.6):
                    continue

                blk_id = _make_id("txt", page_num, len(texts))
                content = " ".join(w["text"] for w in line_words)
                font_size = _dominant_font_size(line_words)
                font_name = _dominant_font_name(line_words)

                texts[blk_id] = {
                    "id":        blk_id,
                    "type":      "unknown",     # classifier 填入
                    "page":      page_num,
                    "bbox":      list(bbox),
                    "content":   content,
                    "font_size": font_size,
                    "font_name": font_name,
                }
                structure.append(blk_id)

    # ── Step 2：PyMuPDF 擷取嵌入圖片 ─────────────────────────
    fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page_num in range(len(fitz_doc)):
        page_fitz = fitz_doc[page_num]
        img_list   = page_fitz.get_images(full=True)

        for img_index, img_info in enumerate(img_list):
            xref       = img_info[0]
            base_image = fitz_doc.extract_image(xref)
            img_bytes  = base_image.get("image", b"")
            if not img_bytes:
                continue

            # 取得圖片在頁面上的位置（bbox）
            img_rects = page_fitz.get_image_rects(xref)
            bbox = list(img_rects[0]) if img_rects else [0.0, 0.0, 0.0, 0.0]

            blk_id = _make_id("img", page_num + 1, img_index)
            images[blk_id] = img_bytes
            structure.append(blk_id)

            # 在 texts dict 裡補一個 placeholder（讓 structure 順序完整）
            texts[blk_id] = {
                "id":        blk_id,
                "type":      "image",
                "page":      page_num + 1,
                "bbox":      bbox,
                "content":   "",
                "font_size": None,
                "font_name": None,
                "image_ext": base_image.get("ext", "png"),
            }

    fitz_doc.close()

    # ── 整理 structure（去重並依 page + y0 排序）─────────────
    structure = _sort_and_dedupe_structure(structure, texts, tables)

    logger.info(
        "[Parser] 完成：%d 頁，%d 文字區塊，%d 表格，%d 圖片",
        page_count, len(texts), len(tables), len(images),
    )

    return {
        "doc_id":     doc_id,
        "filename":   filename,
        "page_count": page_count,
        "texts":      texts,
        "tables":     tables,
        "images":     images,
        "structure":  structure,
    }


# ── 私有工具函式 ──────────────────────────────────────────────

def __bytes_to_stream(data: bytes):
    """將 bytes 包成 file-like object 給 pdfplumber.open()。"""
    import io
    return io.BytesIO(data)


def _make_id(prefix: str, page: int, index: int) -> str:
    return f"{prefix}-p{page:02d}-{index:04d}"


def _clean_table(raw: list[list]) -> list[list[str]]:
    """將 None 替換為空字串，統一為 str。"""
    return [
        [str(cell) if cell is not None else "" for cell in row]
        for row in raw
    ]


def _find_table_bbox(page, raw_table: list[list]) -> tuple[float, float, float, float]:
    """
    嘗試從 pdfplumber page.find_tables() 取得精確 bbox；
    fallback 回傳整頁寬度的估算值。
    """
    try:
        found = page.find_tables()
        if found:
            for t in found:
                return (t.bbox[0], t.bbox[1], t.bbox[2], t.bbox[3])
    except Exception:
        pass
    # fallback
    return (0.0, 0.0, float(page.width), float(page.height))


def _group_words_to_lines(
    words: list[dict], y_tolerance: float = 4.0
) -> list[list[dict]]:
    """依 top 座標分群，相近的 word 視為同一行。"""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / y_tolerance), w["x0"]))
    lines:  list[list[dict]] = []
    current: list[dict] = [sorted_words[0]]
    prev_top = sorted_words[0]["top"]

    for w in sorted_words[1:]:
        if abs(w["top"] - prev_top) <= y_tolerance:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
            prev_top = w["top"]
    lines.append(current)
    return lines


def _words_bbox(words: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(w["x0"]     for w in words)
    y0 = min(w["top"]    for w in words)
    x1 = max(w["x1"]     for w in words)
    y1 = max(w["bottom"] for w in words)
    return (x0, y0, x1, y1)


def _dominant_font_size(words: list[dict]) -> Optional[float]:
    sizes = [w.get("size") for w in words if w.get("size")]
    if not sizes:
        return None
    return round(max(set(sizes), key=sizes.count), 2)


def _dominant_font_name(words: list[dict]) -> Optional[str]:
    names = [w.get("fontname") for w in words if w.get("fontname")]
    if not names:
        return None
    return max(set(names), key=names.count)


def _in_any_bbox(
    bbox: tuple,
    table_bboxes: list[tuple],
    overlap_threshold: float = 0.6,
) -> bool:
    """
    判斷 bbox 是否與任何 table_bbox 重疊超過門檻。
    用來過濾文字擷取中屬於表格的部分。
    """
    bx0, by0, bx1, by1 = bbox
    b_area = max((bx1 - bx0) * (by1 - by0), 1e-6)

    for tx0, ty0, tx1, ty1 in table_bboxes:
        ix0 = max(bx0, tx0)
        iy0 = max(by0, ty0)
        ix1 = min(bx1, tx1)
        iy1 = min(by1, ty1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        overlap = (ix1 - ix0) * (iy1 - iy0) / b_area
        if overlap >= overlap_threshold:
            return True
    return False


def _sort_and_dedupe_structure(
    structure: list[str],
    texts: dict,
    tables: dict,
) -> list[str]:
    """去重並依 (page, y0) 重新排序 structure。"""
    seen: set[str] = set()
    unique = []
    for blk_id in structure:
        if blk_id not in seen:
            seen.add(blk_id)
            unique.append(blk_id)

    def sort_key(blk_id: str):
        meta = texts.get(blk_id) or tables.get(blk_id) or {}
        page = meta.get("page", 0)
        bbox = meta.get("bbox", [0, 0, 0, 0])
        y0   = bbox[1] if len(bbox) > 1 else 0
        return (page, y0)

    return sorted(unique, key=sort_key)
