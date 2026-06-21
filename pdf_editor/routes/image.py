"""
routes/image.py — 圖片置換與調整

POST /api/doc/<doc_id>/image/<block_id>/replace
    multipart/form-data，欄位 "image" 為新圖片檔案
    更換圖片二進位，寫入 {block_id}_replaced.{ext}

PATCH /api/doc/<doc_id>/image/<block_id>/transform
    JSON body: { "width":, "height":, "x":, "y": }（皆為選填，至少一項）
    只調整尺寸與位置，不更換圖片本身

POST /api/doc/<doc_id>/image/<block_id>/restore
    刪除 _replaced 版本，還原為原始圖片

GET  /api/doc/<doc_id>/image/<block_id>
    回傳目前使用中的圖片（優先 replaced，否則原始），以二進位串流回傳
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, send_file
from pdf_editor.services.cache_manager import CacheManager

logger = logging.getLogger(__name__)
image_bp = Blueprint("image", __name__)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


# ── 共用工具 ──────────────────────────────────────────────────

def _get_cache_or_404(doc_id: str):
    cm = CacheManager.from_doc_id(doc_id)
    if not cm.exists():
        return None
    return cm


def _block_exists(cm: CacheManager, block_id: str) -> bool:
    doc = cm.load()
    return block_id in doc["texts"] or block_id in doc["tables"]


def _ext_from_filename(filename: str) -> str:
    if "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()
        if ext in ALLOWED_IMAGE_EXT:
            return ext
    return "png"


# ── 置換圖片 ──────────────────────────────────────────────────

@image_bp.post("/api/doc/<doc_id>/image/<block_id>/replace")
def replace_image(doc_id: str, block_id: str):
    cm = _get_cache_or_404(doc_id)
    if cm is None:
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    if not _block_exists(cm, block_id):
        return jsonify({"error": f"找不到區塊 {block_id}"}), 404

    if "image" not in request.files:
        return jsonify({"error": "請提供 image 欄位"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "未選擇檔案"}), 400

    ext = _ext_from_filename(file.filename)
    img_bytes = file.read()

    if len(img_bytes) == 0:
        return jsonify({"error": "圖片內容為空"}), 400

    patch_data = {"bytes": img_bytes, "ext": ext}

    # 若請求中附帶尺寸，一併更新
    for key in ("width", "height", "x", "y"):
        val = request.form.get(key)
        if val is not None:
            try:
                patch_data[key] = float(val)
            except ValueError:
                return jsonify({"error": f"{key} 必須為數字"}), 400

    try:
        cm.patch(block_id, "image", patch_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    doc   = cm.load()
    block = doc["texts"].get(block_id)
    return jsonify({"ok": True, "block": block})


# ── 調整尺寸與位置（不更換圖片）──────────────────────────────

@image_bp.patch("/api/doc/<doc_id>/image/<block_id>/transform")
def transform_image(doc_id: str, block_id: str):
    cm = _get_cache_or_404(doc_id)
    if cm is None:
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    if not _block_exists(cm, block_id):
        return jsonify({"error": f"找不到區塊 {block_id}"}), 404

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "缺少 JSON body"}), 400

    allowed_keys = {"width", "height", "x", "y"}
    data = {k: v for k, v in body.items() if k in allowed_keys}

    if not data:
        return jsonify({"error": "至少需要 width / height / x / y 其中一項"}), 400

    for key, val in data.items():
        if not isinstance(val, (int, float)):
            return jsonify({"error": f"{key} 必須為數字"}), 400
        if val < 0:
            return jsonify({"error": f"{key} 不可為負數"}), 400

    try:
        cm.patch(block_id, "image", data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    doc   = cm.load()
    block = doc["texts"].get(block_id)
    return jsonify({"ok": True, "block": block})


# ── 還原原圖 ──────────────────────────────────────────────────

@image_bp.post("/api/doc/<doc_id>/image/<block_id>/restore")
def restore_image(doc_id: str, block_id: str):
    cm = _get_cache_or_404(doc_id)
    if cm is None:
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    if not _block_exists(cm, block_id):
        return jsonify({"error": f"找不到區塊 {block_id}"}), 404

    removed = False
    if cm.images_dir.exists():
        for path in cm.images_dir.iterdir():
            if path.stem == f"{block_id}_replaced":
                path.unlink()
                removed = True

    return jsonify({"ok": True, "restored": removed})


# ── 取得目前使用中的圖片 ──────────────────────────────────────

@image_bp.get("/api/doc/<doc_id>/image/<block_id>")
def get_image(doc_id: str, block_id: str):
    cm = _get_cache_or_404(doc_id)
    if cm is None:
        return jsonify({"error": f"找不到文件 {doc_id[:12]}…"}), 404

    path = cm.get_image_path(block_id)
    if path is None:
        return jsonify({"error": f"找不到 {block_id} 的圖片"}), 404

    mimetype = f"image/{path.suffix.lstrip('.').lower()}"
    if mimetype == "image/jpg":
        mimetype = "image/jpeg"

    return send_file(path, mimetype=mimetype)
