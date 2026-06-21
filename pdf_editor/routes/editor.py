"""
routes/editor.py — 區塊讀取與局部更新

GET  /api/doc/<doc_id>
    回傳文件完整結構（texts + tables + structure + meta）

GET  /api/doc/<doc_id>/block/<block_id>
    回傳單一區塊內容

PATCH /api/doc/<doc_id>/block/<block_id>
    局部更新單一區塊，寫入 file_caches
    Body JSON:
      { "type": "text"|"table"|"image", "data": { ...欄位 } }

GET  /api/doc/<doc_id>/overview
    回傳總覽頁表格與所有聯動關係
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, send_file
from pdf_editor.services.cache_manager import CacheManager
from pdf_editor.services.validator import Validator

logger = logging.getLogger(__name__)
editor_bp = Blueprint("editor", __name__)


# ── GET 文件完整結構 ──────────────────────────────────────────

@editor_bp.get("/api/doc/<doc_id>/raw")
def get_raw_pdf(doc_id: str):
    """
    回傳原始上傳的 PDF 二進位內容，供前端 pdf.js 渲染左側預覽用。
    與編輯狀態無關，永遠是使用者最初上傳的檔案。
    """
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    raw_path = cm.cache_dir / "original.pdf"
    if not raw_path.exists():
        return jsonify({"error": "原始 PDF 檔案遺失"}), 404

    return send_file(raw_path, mimetype="application/pdf")


@editor_bp.get("/api/doc/<doc_id>")
def get_document(doc_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    doc = cm.load()
    meta = cm.get_meta()

    return jsonify({
        "doc_id":     doc["doc_id"],
        "filename":   doc["filename"],
        "page_count": doc["page_count"],
        "structure":  doc["structure"],
        "texts":      doc["texts"],
        "tables":     doc["tables"],
        "meta":       meta,
    })


# ── GET 單一區塊 ──────────────────────────────────────────────

@editor_bp.get("/api/doc/<doc_id>/block/<block_id>")
def get_block(doc_id: str, block_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    doc = cm.load()
    block = (
        doc["texts"].get(block_id)
        or doc["tables"].get(block_id)
    )
    if block is None:
        return jsonify({"error": f"找不到區塊 {block_id}"}), 404

    return jsonify({"block": block})


# ── PATCH 單一區塊 ────────────────────────────────────────────

@editor_bp.patch("/api/doc/<doc_id>/block/<block_id>")
def patch_block(doc_id: str, block_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "缺少 JSON body"}), 400

    block_type = body.get("type")
    data       = body.get("data")

    if block_type not in ("text", "table", "image"):
        return jsonify({"error": f"type 必須為 text / table / image，收到 {block_type!r}"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "data 必須為 JSON 物件"}), 400

    try:
        cm.patch(block_id, block_type, data)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # 回傳更新後的區塊
    doc   = cm.load()
    block = doc["texts"].get(block_id) or doc["tables"].get(block_id)

    response = {"ok": True, "block": block}

    # 表格類型更新後，附帶數值一致性驗證結果
    # （不阻擋存檔，只回傳警示供前端顯示）
    if block_type == "table" and block is not None:
        validation = Validator.validate_table(block_id, block)

        # 若該表格有聯動總覽頁，一併檢查聯動是否一致
        overview_id = block.get("linked_overview_block")
        if overview_id and overview_id in doc["tables"]:
            full_check = Validator.validate_document(doc)
            overview_issues = [
                issue.to_dict() for issue in full_check.issues
                if issue.block_id == block_id and "OVERVIEW" in issue.code
            ]
            validation_dict = validation.to_dict()
            validation_dict["issues"].extend(overview_issues)
            validation_dict["error_count"] += sum(
                1 for i in overview_issues if i["severity"] == "error"
            )
            validation_dict["warning_count"] += sum(
                1 for i in overview_issues if i["severity"] == "warning"
            )
            validation_dict["is_valid"] = validation_dict["error_count"] == 0
            response["validation"] = validation_dict
        else:
            response["validation"] = validation.to_dict()

    return jsonify(response)


# ── GET 總覽頁 ────────────────────────────────────────────────

@editor_bp.get("/api/doc/<doc_id>/overview")
def get_overview(doc_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    doc = cm.load()

    # 找出所有 type == overview 的表格
    overview_tables = {
        blk_id: blk
        for blk_id, blk in doc["tables"].items()
        if blk.get("type") == "overview"
    }

    # 找出所有帶有 linked_overview_block 的子表格
    linked = {
        blk_id: {
            "total":                blk.get("total"),
            "linked_overview_block": blk.get("linked_overview_block"),
            "linked_overview_cell":  blk.get("linked_overview_cell"),
        }
        for blk_id, blk in doc["tables"].items()
        if blk.get("linked_overview_block")
    }

    return jsonify({
        "overview_tables": overview_tables,
        "linked_tables":   linked,
    })
