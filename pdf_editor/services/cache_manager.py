"""
services/cache_manager.py — 解析結果快取管理

職責：
- 以 SHA-256 (doc_id) 為目錄名，儲存解析後的 JSON 與圖片
- check()     → 快取是否存在且完整
- save()      → 首次解析後寫入
- load()      → 快速讀取（回傳與 parse_pdf 相同格式的 dict）
- patch()     → 使用者存檔時局部更新單一區塊
- mark_exported() → 匯出後更新版本號
- delete()    → 清除該文件的全部快取

目錄結構：
  file_caches/{doc_id}/
    meta.json        版本、時間戳、來源檔名
    texts.json       所有文字區塊
    tables.json      所有表格區塊
    structure.json   排列順序
    images/
      {blk_id}.png   原始擷取圖片
      {blk_id}_replaced.png   使用者更換後的圖片
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import CACHE_DIR

logger = logging.getLogger(__name__)

# 快取完整性驗證：這些檔案都存在才算有效快取
_REQUIRED_FILES = ("meta.json", "texts.json", "tables.json", "structure.json")


class CacheManager:

    def __init__(self, doc_id: str, filename: str = ""):
        self.doc_id     = doc_id
        self.filename   = filename
        self.cache_dir  = CACHE_DIR / doc_id
        self.images_dir = self.cache_dir / "images"

    # ── 工廠方法（只有 doc_id 時使用）──────────────────────────
    @classmethod
    def from_doc_id(cls, doc_id: str) -> "CacheManager":
        obj = cls.__new__(cls)
        obj.doc_id     = doc_id
        obj.filename   = ""
        obj.cache_dir  = CACHE_DIR / doc_id
        obj.images_dir = obj.cache_dir / "images"
        return obj

    # ── 查詢 ──────────────────────────────────────────────────
    def exists(self) -> bool:
        """所有必要檔案都存在才回傳 True。"""
        return all((self.cache_dir / f).exists() for f in _REQUIRED_FILES)

    def load(self) -> dict:
        """
        快速讀取快取，回傳與 parse_pdf() 相同格式的 dict。
        呼叫前應先確認 exists() == True。
        """
        texts     = self._read_json("texts.json")
        tables    = self._read_json("tables.json")
        structure = self._read_json("structure.json")
        meta      = self._read_json("meta.json")

        # 圖片二進位（只讀取實際存在的）
        images: dict[str, bytes] = {}
        if self.images_dir.exists():
            for img_path in self.images_dir.iterdir():
                # 跳過 _replaced 版本（透過 get_image_path 取用）
                if "_replaced" not in img_path.stem:
                    blk_id = img_path.stem
                    images[blk_id] = img_path.read_bytes()

        logger.info("[CacheManager] 快取載入：%s…", self.doc_id[:12])
        return {
            "doc_id":     self.doc_id,
            "filename":   meta.get("filename", self.filename),
            "page_count": meta.get("page_count", 0),
            "texts":      texts,
            "tables":     tables,
            "images":     images,
            "structure":  structure if isinstance(structure, list) else structure.get("order", []),
        }

    # ── 首次寫入 ──────────────────────────────────────────────
    def save(self, parsed: dict) -> None:
        """
        parse_pdf() + classify_blocks() 完成後呼叫，
        將全量結果寫入 file_caches/{doc_id}/。
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(exist_ok=True)

        # meta
        self._write_json("meta.json", {
            "doc_id":      self.doc_id,
            "filename":    parsed.get("filename", self.filename),
            "page_count":  parsed.get("page_count", 0),
            "created_at":  _now(),
            "last_edited_at": None,
            "exported_at": None,
            "version":     1,
        })

        # 文字、表格、排列順序
        self._write_json("texts.json",    parsed.get("texts",  {}))
        self._write_json("tables.json",   parsed.get("tables", {}))

        structure = parsed.get("structure", [])
        # structure 統一存為 list（包在 dict 方便日後擴充）
        self._write_json("structure.json", structure)

        # 圖片二進位
        for blk_id, img_bytes in parsed.get("images", {}).items():
            # 取得副檔名（texts 裡有 image_ext 欄位）
            ext = parsed["texts"].get(blk_id, {}).get("image_ext", "png")
            (self.images_dir / f"{blk_id}.{ext}").write_bytes(img_bytes)

        logger.info("[CacheManager] 快取已儲存：%s…", self.doc_id[:12])

    # ── 局部更新 ──────────────────────────────────────────────
    def patch(self, block_id: str, block_type: str, new_data: dict) -> None:
        """
        使用者存檔時呼叫，只更新指定區塊。
        block_type: "text" | "table" | "image"
        """
        if block_type == "text":
            data = self._read_json("texts.json")
            if block_id not in data:
                raise KeyError(f"block_id {block_id} 不存在於 texts.json")
            data[block_id].update(new_data)
            self._write_json("texts.json", data)

        elif block_type == "table":
            data = self._read_json("tables.json")
            if block_id not in data:
                raise KeyError(f"block_id {block_id} 不存在於 tables.json")
            data[block_id].update(new_data)
            self._write_json("tables.json", data)
            # 聯動更新 overview（若有 linked_overview_block）
            self._propagate_overview(block_id, new_data.get("total"))

        elif block_type == "image":
            img_bytes = new_data.get("bytes")
            ext       = new_data.get("ext", "png")
            if img_bytes:
                self.images_dir.mkdir(exist_ok=True)
                (self.images_dir / f"{block_id}_replaced.{ext}").write_bytes(img_bytes)
            # 更新 texts 中對應的 image metadata
            texts = self._read_json("texts.json")
            if block_id in texts:
                for key in ("width", "height", "x", "y"):
                    if key in new_data:
                        texts[block_id][key] = new_data[key]
                self._write_json("texts.json", texts)

        else:
            raise ValueError(f"未知的 block_type: {block_type}")

        # 更新 meta
        meta = self._read_json("meta.json")
        meta["last_edited_at"] = _now()
        self._write_json("meta.json", meta)
        logger.debug("[CacheManager] patch %s (%s)", block_id, block_type)

    # ── 匯出標記 ──────────────────────────────────────────────
    def mark_exported(self) -> None:
        meta = self._read_json("meta.json")
        meta["exported_at"] = _now()
        meta["version"]     = meta.get("version", 1) + 1
        self._write_json("meta.json", meta)

    # ── 圖片取用 ──────────────────────────────────────────────
    def get_image_path(self, block_id: str) -> Optional[Path]:
        """優先回傳使用者置換後的圖片，否則回傳原始圖片。"""
        if not self.images_dir.exists():
            return None
        for path in self.images_dir.iterdir():
            if path.stem == f"{block_id}_replaced":
                return path
        for path in self.images_dir.iterdir():
            if path.stem == block_id:
                return path
        return None

    # ── 清除快取 ──────────────────────────────────────────────
    def delete(self) -> None:
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            logger.info("[CacheManager] 快取已清除：%s…", self.doc_id[:12])

    # ── meta 讀取 ─────────────────────────────────────────────
    def get_meta(self) -> dict:
        return self._read_json("meta.json")

    # ── 私有工具 ──────────────────────────────────────────────
    def _read_json(self, filename: str) -> dict | list:
        path = self.cache_dir / filename
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("[CacheManager] JSON 讀取失敗 %s: %s", filename, e)
            return {}

    def _write_json(self, filename: str, data: dict | list) -> None:
        path = self.cache_dir / filename
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _propagate_overview(self, block_id: str, new_total) -> None:
        """子表格 total 更新後，聯動更新總覽頁對應欄位。"""
        if new_total is None:
            return
        tables = self._read_json("tables.json")
        blk    = tables.get(block_id, {})
        overview_id   = blk.get("linked_overview_block")
        overview_cell = blk.get("linked_overview_cell")

        if not overview_id or not overview_cell:
            return

        overview = tables.get(overview_id)
        if not overview:
            return

        # cell 格式如 "B3"：col=B(1), row=3(0-indexed=2)
        try:
            col = ord(overview_cell[0].upper()) - ord("A")
            row = int(overview_cell[1:]) - 1
            sheet = overview.get("raw_rows", [])
            if row < len(sheet) and col < len(sheet[row]):
                sheet[row][col] = str(new_total)
                overview["raw_rows"] = sheet
                tables[overview_id]  = overview
                self._write_json("tables.json", tables)
                logger.debug(
                    "[CacheManager] overview 聯動更新 %s[%s] = %s",
                    overview_id, overview_cell, new_total,
                )
        except (IndexError, ValueError) as e:
            logger.warning("[CacheManager] overview 聯動失敗: %s", e)


# ── 模組層級工具 ──────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_all_caches() -> list[dict]:
    """回傳所有快取的 meta 清單（供管理介面使用）。"""
    result = []
    if not CACHE_DIR.exists():
        return result
    for meta_path in sorted(CACHE_DIR.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            result.append(meta)
        except Exception:
            pass
    return result
