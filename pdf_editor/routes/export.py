"""
routes/export.py — 匯出最終 PDF

POST /api/doc/<doc_id>/export
    1. 讀取快取中的編輯後內容
    2. 呼叫 renderer.render_pdf() 產生 PDF bytes
    3. 寫入 exports/{doc_id}_{version}.pdf
    4. 更新 cache_manager.mark_exported()（版本號 +1）
    5. 以檔案下載形式回傳 PDF

GET /api/doc/<doc_id>/export/latest
    回傳該文件最近一次匯出的 PDF（不重新渲染，若無匯出紀錄回傳 404）
"""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, send_file

from config import EXPORT_DIR
from pdf_editor.services.cache_manager import CacheManager
from pdf_editor.services.renderer import render_pdf

logger = logging.getLogger(__name__)
export_bp = Blueprint("export", __name__)


# ── 匯出（重新渲染）──────────────────────────────────────────

@export_bp.post("/api/doc/<doc_id>/export")
def export_pdf(doc_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    doc = cm.load()

    try:
        pdf_bytes = render_pdf(doc, cm)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.exception("[Export] 渲染失敗 doc_id=%s", doc_id[:12])
        return jsonify({"error": f"匯出失敗：{e}"}), 500

    # 先遞增版本號，再用「新」版本號命名檔案，
    # 確保 get_latest_export() 用同一個版本號能找到對應檔案
    cm.mark_exported()
    meta    = cm.get_meta()
    version = meta.get("version", 1)
    out_path = EXPORT_DIR / f"{doc_id}_v{version}.pdf"
    out_path.write_bytes(pdf_bytes)

    logger.info("[Export] 完成 %s → %s", doc_id[:12], out_path.name)

    download_name = _build_download_name(doc.get("filename", "document.pdf"), version)

    return send_file(
        out_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


# ── 取得最近一次匯出（不重新渲染）────────────────────────────

@export_bp.get("/api/doc/<doc_id>/export/latest")
def get_latest_export(doc_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    meta = cm.get_meta()
    if not meta.get("exported_at"):
        return jsonify({"error": "尚未匯出過此文件"}), 404

    version  = meta.get("version", 1)
    out_path = EXPORT_DIR / f"{doc_id}_v{version}.pdf"

    if not out_path.exists():
        # version 已更新但檔案因故遺失（例如手動清除 exports/）
        return jsonify({"error": "匯出檔案遺失，請重新匯出"}), 404

    download_name = _build_download_name(meta.get("filename", "document.pdf"), version)

    return send_file(
        out_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


# ── 私有工具 ──────────────────────────────────────────────────

def _build_download_name(original_filename: str, version: int) -> str:
    stem = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
    return f"{stem}_v{version}.pdf"
