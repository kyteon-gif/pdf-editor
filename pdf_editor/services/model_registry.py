"""
services/model_registry.py — 本機模型管理

職責：
1. Flask 啟動時呼叫 ensure_all()，逐一檢查每個模型是否完整存在。
2. 若缺少且網路可達，自動下載並寫入 models/manifest.json。
3. 提供 path(name) 給 classifier / table_parser 使用本機路徑。
4. 提供 status() 給 /api/health 端點回傳目前狀態。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import MODEL_DIR, MODEL_MANIFEST

logger = logging.getLogger(__name__)

MANIFEST_PATH = MODEL_DIR / "manifest.json"

# 執行期快取：{name: local_path_str or None}
_registry: dict[str, Optional[str]] = {}


class ModelRegistry:

    # ── 公開 API ──────────────────────────────────────────────

    @classmethod
    def ensure_all(cls) -> None:
        """Flask create_app() 呼叫，掃描所有模型。"""
        for name, spec in MODEL_MANIFEST.items():
            local_path = cls._check_local(name, spec)
            if local_path:
                _registry[name] = str(local_path)
                logger.info("[ModelRegistry] ✅ %s — 本機就緒", name)
            else:
                logger.warning("[ModelRegistry] ⚠️  %s — 本機未找到，嘗試下載…", name)
                downloaded = cls._download(name, spec)
                if downloaded:
                    _registry[name] = str(spec["local_dir"])
                    cls._write_manifest(name, spec)
                    logger.info("[ModelRegistry] ⬇️  %s — 下載完成", name)
                else:
                    _registry[name] = None
                    if spec["required"]:
                        logger.error(
                            "[ModelRegistry] ❌ 必要模型 %s 無法取得，部分功能將無法使用", name
                        )
                    else:
                        logger.warning(
                            "[ModelRegistry] ⚠️  選用模型 %s 無法取得，啟用降級模式", name
                        )

    @classmethod
    def path(cls, name: str) -> Optional[str]:
        """回傳本機模型路徑字串，供 from_pretrained() 使用。若不存在回傳 None。"""
        return _registry.get(name)

    @classmethod
    def is_ready(cls, name: str) -> bool:
        return _registry.get(name) is not None

    @classmethod
    def status(cls) -> dict:
        """回傳各模型目前狀態（供 /api/health）。"""
        result = {}
        for name, spec in MODEL_MANIFEST.items():
            result[name] = {
                "ready":    cls.is_ready(name),
                "path":     _registry.get(name),
                "required": spec["required"],
                "license":  spec["license"],
                "size_gb":  spec["size_gb"],
            }
        return result

    # ── 私有工具 ──────────────────────────────────────────────

    @classmethod
    def _check_local(cls, name: str, spec: dict) -> Optional[Path]:
        """檢查四個關鍵檔案是否都存在，全部存在才回傳路徑。"""
        local_dir: Path = spec["local_dir"]
        missing = [
            f for f in spec["validate_files"]
            if not (local_dir / f).exists()
        ]
        if missing:
            logger.debug("[ModelRegistry] %s 缺少檔案: %s", name, missing)
            return None
        return local_dir

    @classmethod
    def _download(cls, name: str, spec: dict) -> bool:
        """使用 huggingface_hub.snapshot_download 下載模型。"""
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            logger.warning("[ModelRegistry] huggingface_hub 未安裝，無法下載 %s", name)
            return False

        try:
            snapshot_download(
                repo_id   = spec["hf_id"],
                local_dir = str(spec["local_dir"]),
                ignore_patterns = ["*.bin", "*.onnx"],  # 跳過冗餘格式
            )
            return True
        except Exception as exc:
            logger.warning("[ModelRegistry] 下載 %s 失敗: %s", name, exc)
            return False

    @classmethod
    def _write_manifest(cls, name: str, spec: dict) -> None:
        manifest: dict = {}
        if MANIFEST_PATH.exists():
            try:
                manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        manifest[name] = {
            "hf_id":        spec["hf_id"],
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "local_dir":    str(spec["local_dir"]),
            "license":      spec["license"],
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
