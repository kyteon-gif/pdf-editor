"""
routes/upload.py — PDF 上傳路由

POST /api/upload
  1. 接收 multipart/form-data 的 PDF 檔案
  2. 用 CacheManager 判斷是否已有快取
     - 命中 → 直接回傳，跳過解析與 NLP
     - 未命中 → parse_pdf → classifier → cache_manager.save()
  3. 回傳結構化 JSON 給前端

回傳格式：
{
  "doc_id":     str,
  "filename":   str,
  "page_count": int,
  "source":     "cache" | "parsed",
  "structure":  [block_id, ...],
  "texts":      { block_id: {...} },
  "tables":     { block_id: {...} },
  "images":     { block_id: "<base64>" }   ← bytes 轉 base64 供前端顯示
}
"""

from __future__ import annotations

import base64
import logging

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from config import ALLOWED_EXTENSIONS, UPLOAD_DIR
from pdf_editor.services.cache_manager import CacheManager
from pdf_editor.services.parser import parse_pdf
from pdf_editor.services.classifier import Classifier

logger = logging.getLogger(__name__)
upload_bp = Blueprint("upload", __name__)


# ── 路由 ──────────────────────────────────────────────────────

@upload_bp.post("/api/upload")
def upload():
    # ── 1. 驗證請求 ───────────────────────────────────────────
    if "pdf" not in request.files:
        return jsonify({"error": "請提供 pdf 欄位"}), 400

    file = request.files["pdf"]

    if file.filename == "":
        return jsonify({"error": "未選擇檔案"}), 400

    if not _allowed(file.filename):
        return jsonify({"error": "只接受 PDF 檔案"}), 415

    filename   = secure_filename(file.filename)
    file_bytes = file.read()

    if len(file_bytes) == 0:
        return jsonify({"error": "檔案內容為空"}), 400

    # ── 2. 儲存原始檔（uploads/）────────────────────────────
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(file_bytes)

    # ── 3. 建立 CacheManager，判斷快取 ───────────────────────
    cm = CacheManager(
        doc_id   = _sha256(file_bytes),
        filename = filename,
    )

    if cm.exists():
        logger.info("[Upload] 快取命中：%s", cm.doc_id[:12])
        parsed = cm.load()
        source = "cache"
        # 快取命中時也要確保原始 PDF 存在（理論上第一次已寫入，這裡防禦性補寫）
        _ensure_raw_pdf(cm, file_bytes)
    else:
        logger.info("[Upload] 快取未命中，開始解析：%s", filename)

        # ── 4a. PDF 解析 ─────────────────────────────────────
        try:
            parsed = parse_pdf(file_bytes, filename)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500

        # ── 4b. NLP 區塊分類 ─────────────────────────────────
        Classifier.classify_blocks(parsed)

        # ── 4c. 寫入快取 ─────────────────────────────────────
        cm.doc_id = parsed["doc_id"]   # 確保 doc_id 一致
        cm.save(parsed)
        _ensure_raw_pdf(cm, file_bytes)
        source = "parsed"

    # ── 5. 組合回傳 JSON ─────────────────────────────────────
    return jsonify({
        "doc_id":     parsed["doc_id"],
        "filename":   parsed["filename"],
        "page_count": parsed["page_count"],
        "source":     source,
        "structure":  parsed["structure"],
        "texts":      parsed["texts"],
        "tables":     parsed["tables"],
        "images":     _encode_images(parsed.get("images", {})),
    })


# ── 私有工具 ──────────────────────────────────────────────────

def _ensure_raw_pdf(cm: CacheManager, file_bytes: bytes) -> None:
    """
    將原始 PDF bytes 存一份到 file_caches/{doc_id}/original.pdf，
    供 GET /api/doc/<doc_id>/raw 直接以 doc_id 取用（不依賴原始檔名）。
    冪等操作：若已存在則不重複寫入。
    """
    raw_path = cm.cache_dir / "original.pdf"
    if not raw_path.exists():
        cm.cache_dir.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(file_bytes)


def _allowed(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def _sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _encode_images(images: dict[str, bytes]) -> dict[str, str]:
    """將圖片 bytes 轉為 base64 字串，供前端 <img src='data:...'> 使用。"""
    result = {}
    for blk_id, img_bytes in images.items():
        if isinstance(img_bytes, bytes) and img_bytes:
            result[blk_id] = base64.b64encode(img_bytes).decode("utf-8")
    return result
