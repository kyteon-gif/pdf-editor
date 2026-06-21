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

    # ── Step 0：提前開啟 fitz 文件，供 cid 亂碼 fallback 使用 ──
    # （圖片擷取也會用到，避免重複開檔，這裡統一管理生命週期）
    fitz_doc_for_text = fitz.open(stream=file_bytes, filetype="pdf")
    fitz_page_cache: dict[int, "fitz.Page"] = {}

    # ── Step 1：pdfplumber 擷取文字與表格 ─────────────────────
    with pdfplumber.open(file_bytes if isinstance(file_bytes, (str, Path))
                         else __bytes_to_stream(file_bytes)) as pdf:

        page_count = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages, start=1):
            logger.debug("[Parser] 處理第 %d/%d 頁", page_num, page_count)

            # 對應快取同一頁的 fitz page 物件，供 cid 亂碼 fallback 使用
            if page_num not in fitz_page_cache:
                fitz_page_cache[page_num] = fitz_doc_for_text[page_num - 1]

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

                # ── cid 亂碼偵測與 OCR fallback ────────────────
                # 某些 PDF（常見於 DOCX 轉檔且嵌入子集字型但缺少完整
                # ToUnicode CMap）會讓任何標準文字抽取 API（pdfplumber、
                # PyMuPDF 皆然）回傳無意義的字型內部編碼或偽字符，
                # 這是 PDF 本身字型結構的限制，並非函式庫的 bug，
                # 唯一可靠的解法是用 OCR 對該區域重新辨識。
                # 此路徑需要本機已安裝 tesseract 與對應語言包
                # （繁中：chi_tra，簡中：chi_sim），否則 fallback 會
                # 靜默失敗並保留原始（雖無意義但至少不誤導的）內容。
                is_garbled = _is_cid_garbled(content)
                ocr_used = False
                ocr_low_confidence = False
                if is_garbled:
                    ocr_text = _extract_text_via_ocr(fitz_page_cache, page_num, bbox)
                    if ocr_text:
                        content = ocr_text
                        ocr_used = True
                        # OCR 有跑出結果不代表結果可信：若辨識出的內容
                        # 看起來像亂湊的英數混雜字串（例如 "meran_ N_ 7
                        # mwmsax"），明顯不像正常標題或內文，保留警示
                        # 而非直接判定為已解決，避免使用者誤信錯誤內容。
                        if _looks_like_ocr_noise(content):
                            ocr_low_confidence = True
                        else:
                            is_garbled = False  # 結果可信，解除警示

                texts[blk_id] = {
                    "id":        blk_id,
                    "type":      "unknown",     # classifier 填入
                    "page":      page_num,
                    "bbox":      list(bbox),
                    "content":   content,
                    "font_size": font_size,
                    "font_name": font_name,
                    "encoding_warning": is_garbled or ocr_low_confidence,
                    "ocr_used":  ocr_used,
                    "ocr_low_confidence": ocr_low_confidence,
                }
                structure.append(blk_id)

    # ── Step 2：PyMuPDF 擷取嵌入圖片 ─────────────────────────
    # 圖片擷取沿用同一份 fitz 文件，避免重複開檔
    fitz_doc = fitz_doc_for_text
    for page_num in range(len(fitz_doc)):
        page_fitz = fitz_doc[page_num]
        img_list   = page_fitz.get_images(full=True)

        for img_index, img_info in enumerate(img_list):
            xref       = img_info[0]
            base_image = fitz_doc.extract_image(xref)
            img_bytes  = base_image.get("image", b"")
            if not img_bytes:
                continue

            # ── 色彩空間正規化 ────────────────────────────────
            # 部分 PDF（尤其印刷流程產出）內嵌 CMYK 色彩模式的圖片，
            # 但匯出階段 WeasyPrint/Pillow 存檔為 PNG 時只支援
            # RGB/RGBA/灰階，CMYK 會直接拋出
            # "cannot write mode CMYK as PNG"。在擷取當下就統一轉成
            # RGB，避免問題延遲到匯出階段才爆炸、且難以定位是哪張圖。
            img_bytes, img_ext = _normalize_image_colorspace(
                img_bytes, base_image.get("ext", "png")
            )

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
                "image_ext": img_ext,
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


_CID_PATTERN = __import__("re").compile(r"\(cid:\d+\)")


def _looks_like_ocr_noise(text: str) -> bool:
    """
    粗略判斷 OCR 辨識結果是否「不像正常文字」。

    典型噪聲特徵：英數字與底線/符號混雜、無空白分隔的隨機字母組合
    （例如 "meran_ N_ 7 mwmsax"），通常發生在裁切框圈到不連續內容
    （例如圖表中跨越多個無關元素的窄帶區域）導致 OCR 誤判背景雜訊
    或圖形線條為文字筆畫。

    判斷標準（任一成立即視為噪聲）：
    - 完全不含中文字元，且包含底線 "_"（正常 OCR 輸出極少出現底線，
      通常是 Tesseract 把雜訊筆畫誤判為底線符號）
    - 完全不含中文，且為 3 個以上由空白分隔的短字母片段
      （長度均 <= 4 的破碎詞組，不像完整單字或句子）
    """
    if not text:
        return False

    has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if has_chinese:
        return False  # 含中文字元的結果，噪聲機率低，不在此啟發式範圍內

    if "_" in text:
        return True

    tokens = text.split()
    short_tokens = [t for t in tokens if len(t) <= 4]
    if len(tokens) >= 3 and len(short_tokens) == len(tokens):
        return True

    return False


def _is_cid_garbled(text: str) -> bool:
    """
    判斷文字是否為 cid 編碼亂碼。
    判斷標準：若字串中 "(cid:N)" 片段佔比過高（>= 30% 的字元數），
    視為該行主要由無法解碼的字型內部編碼組成。
    """
    if not text:
        return False
    matches = _CID_PATTERN.findall(text)
    if not matches:
        return False
    cid_char_count = sum(len(m) for m in matches)
    return cid_char_count / max(len(text), 1) >= 0.3


def _extract_text_via_ocr(
    page_cache: dict[int, "object"], page_num: int, bbox: tuple
) -> str:
    """
    用 OCR（Tesseract）重新辨識指定 bbox 區域的文字。

    背景：當 PDF 嵌入字型缺少有效的 /ToUnicode 對照表時，這是
    PDF 檔案本身的結構限制 —— 無論 pdfplumber 或 PyMuPDF 的標準
    文字抽取 API 都無法正確解碼，只能回傳無意義的內部編碼或
    錯誤映射後的偽字符。OCR 是這種情況下唯一可靠的還原方式：
    把該文字區域渲染成點陣圖，再用光學辨識讀出實際顯示的字元。

    本機需求：
    - pip install pytesseract pillow
    - 系統安裝 tesseract-ocr 主程式
    - 安裝繁體中文語言包（Ubuntu/Debian: apt install
      tesseract-ocr-chi-tra；macOS: brew install tesseract-lang）
      缺少語言包時仍會嘗試辨識，但準確率會大幅下降甚至失敗。

    任何環節缺失（套件未安裝、辨識失敗、結果為空）都會靜默
    回傳空字串，呼叫端會保留原始內容並維持 encoding_warning 標記，
    不會讓解析流程中斷。
    """
    page = page_cache.get(page_num)
    if page is None:
        return ""

    try:
        import fitz  # PyMuPDF；獨立 import，避免依賴 parse_pdf() 區域變數
        import pytesseract
        from PIL import Image
        import io as _io
    except ImportError as e:
        logger.warning(
            "[Parser] OCR fallback 略過：缺少套件 %s"
            "（請執行 pip install pytesseract pillow，並安裝系統 tesseract）",
            e,
        )
        return ""

    try:
        x0, y0, x1, y1 = bbox
        box_height = y1 - y0
        box_width  = x1 - x0

        # 留白邊界：原本固定 2pt 對窄小文字行（常見於圖表內的小字
        # 標籤、座標軸文字）幾乎沒有緩衝，放大後字符容易貼邊被裁切，
        # 嚴重影響辨識率。改為依區塊高度等比例留白，並設最小值。
        padding_y = max(box_height * 0.6, 4)
        padding_x = max(box_width * 0.05, 4)
        clip = fitz.Rect(
            x0 - padding_x, y0 - padding_y,
            x1 + padding_x, y1 + padding_y,
        )

        # 放大渲染倍率（zoom）以提升小字辨識準確率，
        # 區塊越小，放大倍率拉得更高（Tesseract 對過小的字元辨識率很差）
        zoom = 4.0 if box_height < 15 else 3.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, clip=clip)

        img = Image.open(_io.BytesIO(pix.tobytes("png")))

        # PSM (Page Segmentation Mode)：
        # 這些區塊絕大多數是單行短文字（標題、標籤、百分比），
        # 預設的「自動分段」模式常誤判為多欄版面而切錯。
        # --psm 7 = 將整張圖視為單一文字行，--psm 6 = 視為單一區塊，
        # 短而窄的區塊用 7，較寬的區塊（可能跨多個詞組）用 6。
        psm = 7 if box_height < 20 else 6
        config = f"--psm {psm}"

        # 優先嘗試繁體中文，語言包不存在時 fallback 純英文
        # （Tesseract 找不到語言包會拋出 TesseractError）
        try:
            text = pytesseract.image_to_string(img, lang="chi_tra+eng", config=config)
        except Exception:
            text = pytesseract.image_to_string(img, lang="eng", config=config)

        result = text.strip().replace("\n", " ")

        # 第一次辨識為空時，多半是極窄區塊（如圖例小標籤）被
        # psm 7 誤判為無文字行，改用 psm 8（單詞模式）重試一次
        if not result and box_height < 20:
            try:
                retry_text = pytesseract.image_to_string(
                    img, lang="chi_tra+eng", config="--psm 8"
                )
            except Exception:
                retry_text = pytesseract.image_to_string(img, lang="eng", config="--psm 8")
            result = retry_text.strip().replace("\n", " ")

        return result

    except Exception as e:
        logger.warning("[Parser] OCR fallback 辨識失敗 page=%d: %s", page_num, e)
        return ""


def _normalize_image_colorspace(img_bytes: bytes, ext: str) -> tuple[bytes, str]:
    """
    將圖片色彩空間正規化為匯出流程相容的格式。

    背景：部分 PDF（尤其經印刷流程產出）內嵌 CMYK 色彩模式的圖片。
    PNG 格式本身不支援 CMYK，WeasyPrint/Pillow 在匯出階段存檔為 PNG
    時會直接拋出 "cannot write mode CMYK as PNG" 而讓整個匯出失敗。
    在擷取當下就統一轉換，問題定位更直接，也讓快取中存的圖片本身
    就是可直接使用的格式。

    若 Pillow 未安裝或轉換過程出錯，靜默回傳原始 bytes/ext，
    不讓解析流程因為這個非核心步驟而中斷（匯出階段仍可能失敗，
    但至少解析與編輯功能不受影響）。
    """
    try:
        from PIL import Image
        import io as _io
    except ImportError:
        return img_bytes, ext

    try:
        img = Image.open(_io.BytesIO(img_bytes))

        if img.mode in ("CMYK", "LAB", "P"):
            # P（調色盤模式）也一併正規化，避免少數調色盤含透明索引
            # 在某些 PDF 檢視器與 WeasyPrint 之間出現不一致的轉換結果
            img = img.convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), "png"

        # 其他模式（RGB/RGBA/L/1 等）原生相容，不需轉換
        return img_bytes, ext

    except Exception as e:
        logger.warning("[Parser] 圖片色彩空間正規化失敗，保留原始格式: %s", e)
        return img_bytes, ext


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
