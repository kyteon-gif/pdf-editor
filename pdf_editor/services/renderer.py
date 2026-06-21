"""
services/renderer.py — PDF 輸出引擎

職責：
1. 依 structure 順序，將 texts/tables/images 組成 HTML
2. 用 WeasyPrint 把 HTML 轉成 PDF bytes
3. 表格依 BlockType 套用不同樣式（一般表格 vs 總覽表）
4. 圖片優先使用 cache_manager.get_image_path() 回傳的版本（含使用者置換）

輸入：CacheManager.load() 的回傳 dict
輸出：PDF bytes，呼叫端負責寫檔或直接回傳給前端下載

不在此模組做的事：
- 不做數值驗證（由 validator.py 負責）
- 不做區塊分類（由 classifier.py 負責）
"""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── 公開入口 ──────────────────────────────────────────────────

def render_pdf(doc: dict, cache_manager) -> bytes:
    """
    將 CacheManager.load() 回傳的 doc dict 轉成最終 PDF bytes。

    doc 格式：
      { "filename", "page_count", "texts", "tables", "structure", ... }
    cache_manager：用來取得圖片實際路徑（含使用者置換版本）
    """
    html = build_html(doc, cache_manager)

    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(
            f"缺少必要套件：{e}。請執行 pip install weasyprint"
        ) from e

    logger.info("[Renderer] 開始輸出 PDF：%s", doc.get("filename", "unknown"))
    pdf_bytes = HTML(string=html, base_url=".").write_pdf()
    logger.info("[Renderer] PDF 輸出完成，大小 %d bytes", len(pdf_bytes))
    return pdf_bytes


def build_html(doc: dict, cache_manager) -> str:
    """
    將 doc 組成完整 HTML 字串（含內嵌 CSS）。
    拆出此函式方便單獨測試 HTML 結構，不需要 WeasyPrint。
    """
    texts     = doc.get("texts", {})
    tables    = doc.get("tables", {})
    structure = doc.get("structure", [])

    body_parts: list[str] = []
    current_page: Optional[int] = None

    for blk_id in structure:
        blk = texts.get(blk_id) or tables.get(blk_id)
        if blk is None:
            logger.warning("[Renderer] structure 中的 %s 找不到對應內容，略過", blk_id)
            continue

        page = blk.get("page", 1)
        if current_page is not None and page != current_page:
            body_parts.append('<div class="page-break"></div>')
        current_page = page

        btype = blk.get("type", "unknown")

        if btype == "table" or btype == "overview":
            body_parts.append(_render_table(blk))
        elif btype == "image":
            body_parts.append(_render_image(blk, blk_id, cache_manager))
        else:
            body_parts.append(_render_text(blk))

    body_html = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{_DEFAULT_CSS}</style>
</head>
<body>
{body_html}
</body>
</html>"""


# ── 區塊渲染函式 ──────────────────────────────────────────────

def _render_text(blk: dict) -> str:
    btype   = blk.get("type", "body")
    content = escape(blk.get("content", ""))
    font_size = blk.get("font_size")

    css_class = {
        "cover":     "block-cover",
        "heading_1": "block-h1",
        "heading_2": "block-h2",
        "appendix":  "block-appendix",
    }.get(btype, "block-body")

    # 防禦性修正：classifier 對圖表內小型標籤文字（圖例、座標軸文字、
    # 百分比數字等）有時會誤判為 heading_1/heading_2，但這些文字的
    # 實際字級通常遠小於真正的標題。若直接套用標題樣式的大字體與
    # 大段落間距（margin: 1.2em 0 0.6em 等），單一文件中只要有十幾個
    # 這樣的誤判區塊，疊加的間距就足以把原本一頁的內容撐到兩三頁。
    #
    # 這裡用實際字級（font_size）做最後把關：字級明顯小於一般內文
    # （閾值 9pt）時，即使分類結果是 heading，仍強制降級為一般內文
    # 樣式，避免被誤判的標籤撐爆版面。這不修正分類本身的準確度
    # （classifier.py 的職責），只確保渲染結果不會因誤判而失控。
    if btype in ("heading_1", "heading_2") and font_size is not None and font_size < 9:
        return f'<div class="block-body-compact">{content}</div>'

    tag = "h1" if btype in ("cover", "heading_1") else (
        "h2" if btype == "heading_2" else "p"
    )
    return f'<{tag} class="{css_class}">{content}</{tag}>'


def _render_table(blk: dict) -> str:
    rows = blk.get("raw_rows", [])
    if not rows:
        return ""

    btype     = blk.get("type", "table")
    css_class = "table-overview" if btype == "overview" else "table-normal"

    header_row, *body_rows = rows
    thead = "".join(f"<th>{escape(str(c))}</th>" for c in header_row)

    tbody_rows = []
    for row in body_rows:
        is_total = bool(row) and str(row[0]).strip() in ("總計", "合計", "Total")
        row_class = ' class="row-total"' if is_total else ""
        cells = "".join(f"<td>{escape(str(c))}</td>" for c in row)
        tbody_rows.append(f"<tr{row_class}>{cells}</tr>")

    return f"""<table class="{css_class}">
<thead><tr>{thead}</tr></thead>
<tbody>{"".join(tbody_rows)}</tbody>
</table>"""


def _render_image(blk: dict, blk_id: str, cache_manager) -> str:
    path = None
    if cache_manager is not None:
        try:
            path = cache_manager.get_image_path(blk_id)
        except Exception as e:
            logger.warning("[Renderer] 取得圖片路徑失敗 %s: %s", blk_id, e)

    if path is None or not Path(path).exists():
        return f'<div class="image-missing">[圖片遺失：{escape(blk_id)}]</div>'

    # 圖片渲染尺寸優先順序：
    # 1. blk["width"]/["height"]（使用者透過 transform API 手動調整過的值）
    # 2. bbox 算出的寬高（圖片在原始 PDF 頁面上應呈現的實際尺寸）
    # 3. 都沒有時才退回 CSS max-width:100% 自動撐開
    #
    # 重要修復：原本完全依賴 width/height 欄位，但 parser.py 從未填入
    # 這兩個欄位（永遠是 None），導致高解析度圖片以原始像素尺寸渲染，
    # 經常遠超過一頁 A4 紙的可用高度，逼得 WeasyPrint 自動分頁，
    # 讓本該是單頁的內容被拆成多頁。改用 bbox 的寬高還原圖片在
    # 原始 PDF 頁面上的實際比例與大小，避免異常撐高。
    width  = blk.get("width")
    height = blk.get("height")

    if not width or not height:
        bbox = blk.get("bbox")
        if bbox and len(bbox) == 4:
            x0, top, x1, bottom = bbox
            bbox_width  = x1 - x0
            bbox_height = bottom - top
            if bbox_width > 0 and bbox_height > 0:
                width, height = bbox_width, bbox_height

    style_parts = []
    if width:
        style_parts.append(f"width:{width}pt")
    if height:
        style_parts.append(f"height:{height}pt")
    style_attr = f' style="{";".join(style_parts)}"' if style_parts else ""

    # WeasyPrint 支援 file:// 路徑
    file_url = Path(path).resolve().as_uri()
    return f'<img src="{file_url}" class="block-image"{style_attr} />'


# ── 預設樣式 ──────────────────────────────────────────────────

_DEFAULT_CSS = """
@page { size: A4; margin: 2.5cm 2cm; }
body  { font-family: "Noto Sans CJK TC", "Microsoft JhengHei", sans-serif; font-size: 11pt; line-height: 1.6; }

.page-break { page-break-before: always; }

.block-cover    { font-size: 24pt; font-weight: bold; text-align: center; margin: 2em 0; }
.block-h1       { font-size: 16pt; font-weight: bold; margin: 1.2em 0 0.6em; }
.block-h2       { font-size: 13pt; font-weight: bold; margin: 1em 0 0.5em; }
.block-body     { margin: 0.4em 0; }
.block-appendix { font-size: 10pt; color: #444; margin: 0.4em 0; }
.block-body-compact { font-size: 9pt; margin: 0.15em 0; line-height: 1.3; }

table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
th, td { border: 1px solid #999; padding: 4px 8px; font-size: 10pt; text-align: left; }
th { background: #f0f0f0; font-weight: bold; }

.table-overview th { background: #dce6f1; }
.row-total td { font-weight: bold; background: #f7f7f7; }

.block-image { max-width: 100%; max-height: 24cm; display: block; margin: 0.8em auto; }
.image-missing { color: #c0392b; font-style: italic; padding: 1em; border: 1px dashed #c0392b; }
"""
