"""
services/classifier.py — 區塊角色分類器

使用 multilingual-e5-large-instruct embedding + cosine similarity
將每個文字區塊分類為：cover / heading_1 / heading_2 / body /
                       table / image / overview / appendix

流程：
1. 從 ModelRegistry 取得本機模型路徑
2. 將每個區塊的 content + 視覺特徵（字型大小、位置）組成 prompt
3. 計算與各類別 anchor prompt 的 cosine 相似度
4. 取最高分且超過門檻的類別；否則 fallback 到 rule-based

降級模式（模型不可用時）：
- 僅依字型大小與位置判斷 heading_1 / heading_2 / body
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import CLASSIFIER_THRESHOLD
from pdf_editor.models.document import BlockType

logger = logging.getLogger(__name__)

# ── 類別定義（中英文 anchor prompt）───────────────────────────
# 每個類別給 2 條 anchor，embedding 取平均
_ANCHORS: dict[str, list[str]] = {
    BlockType.COVER: [
        "封面標題 公司名稱 文件名稱",
        "cover page title company name document header",
    ],
    BlockType.OVERVIEW: [
        "總覽 彙總表 整體摘要 各項目合計",
        "overview summary table total summary of all items",
    ],
    BlockType.HEADING1: [
        "一級標題 章節標題 主要章節",
        "chapter heading main section title level one",
    ],
    BlockType.HEADING2: [
        "二級標題 子章節 小節標題",
        "section subheading sub-section level two heading",
    ],
    BlockType.BODY: [
        "正文內文 說明文字 段落內容描述",
        "body text paragraph content description prose",
    ],
    BlockType.TABLE: [
        "表格 項次 品名 單價 數量 小計 總計",
        "table item name unit price quantity subtotal total",
    ],
    BlockType.IMAGE: [
        "圖片 圖表 照片 示意圖 插圖",
        "image photo diagram illustration figure",
    ],
    BlockType.APPENDIX: [
        "附錄 附件 補充資料",
        "appendix attachment supplementary material",
    ],
}

# ── 模型快取（singleton）──────────────────────────────────────
_model = None
_anchor_embeddings: Optional[dict] = None   # {block_type: mean_embedding}


class Classifier:

    @classmethod
    def classify_blocks(cls, parsed: dict) -> dict:
        """
        輸入 parser.parse_pdf() 的回傳值，
        為每個 texts block 填入正確的 type，回傳更新後的 texts dict。
        """
        texts  = parsed.get("texts", {})
        tables = parsed.get("tables", {})

        # 表格直接標記（parser 已識別）
        for blk in tables.values():
            blk["type"] = BlockType.TABLE

        # 文字區塊分類
        model = cls._load_model()

        if model is not None:
            cls._classify_with_model(texts, model)
        else:
            logger.warning("[Classifier] 模型不可用，使用 rule-based 分類")
            cls._classify_rule_based(texts)

        return texts

    # ── 模型分類 ──────────────────────────────────────────────

    @classmethod
    def _classify_with_model(cls, texts: dict, model) -> None:
        global _anchor_embeddings

        if _anchor_embeddings is None:
            _anchor_embeddings = cls._build_anchor_embeddings(model)

        import torch
        import torch.nn.functional as F

        for blk_id, blk in texts.items():
            if blk.get("type") == BlockType.IMAGE:
                continue   # 圖片 placeholder 不重新分類

            prompt = cls._build_prompt(blk)
            emb = model.encode(
                [f"Instruct: Classify document block\nQuery: {prompt}"],
                normalize_embeddings=True,
                convert_to_tensor=True,
            )[0]

            best_type  = BlockType.UNKNOWN
            best_score = -1.0

            for btype, anchor_emb in _anchor_embeddings.items():
                score = float(F.cosine_similarity(
                    emb.unsqueeze(0), anchor_emb.unsqueeze(0)
                ))
                if score > best_score:
                    best_score = score
                    best_type  = btype

            if best_score >= CLASSIFIER_THRESHOLD:
                blk["type"] = best_type
            else:
                # 相似度不足，fallback rule-based
                blk["type"] = cls._rule_based_type(blk)

            logger.debug(
                "[Classifier] %s → %s (score=%.3f)", blk_id, blk["type"], best_score
            )

    @classmethod
    def _build_anchor_embeddings(cls, model) -> dict:
        """預先計算所有類別的 anchor embedding（每次啟動只算一次）。"""
        import torch
        result = {}
        for btype, anchors in _ANCHORS.items():
            embs = model.encode(anchors, normalize_embeddings=True, convert_to_tensor=True)
            result[btype] = embs.mean(dim=0)
            logger.debug("[Classifier] anchor built: %s", btype)
        return result

    @classmethod
    def _build_prompt(cls, blk: dict) -> str:
        """將區塊特徵組合成分類用的文字 prompt。"""
        content   = blk.get("content", "")[:120]    # 截斷，避免 token 超限
        font_size = blk.get("font_size") or 0
        page      = blk.get("page", 1)
        bbox      = blk.get("bbox", [0, 0, 0, 0])
        y0        = bbox[1] if len(bbox) > 1 else 0

        size_hint = ""
        if font_size >= 18:
            size_hint = "大字體標題 "
        elif font_size >= 14:
            size_hint = "中字體小標 "

        page_hint = "首頁 " if page == 1 else ""
        top_hint  = "頂部 " if y0 < 100 else ""

        return f"{page_hint}{top_hint}{size_hint}{content}"

    # ── Rule-based 分類 ───────────────────────────────────────

    @classmethod
    def _classify_rule_based(cls, texts: dict) -> None:
        for blk in texts.values():
            if blk.get("type") in (BlockType.IMAGE,):
                continue
            blk["type"] = cls._rule_based_type(blk)

    @classmethod
    def _rule_based_type(cls, blk: dict) -> str:
        content   = blk.get("content", "")
        font_size = blk.get("font_size") or 0
        page      = blk.get("page", 1)
        bbox      = blk.get("bbox", [0, 0, 0, 0])
        y0        = bbox[1] if len(bbox) > 1 else 0

        # 附錄關鍵字
        if re.search(r"附錄|附件|Appendix", content, re.IGNORECASE):
            return BlockType.APPENDIX

        # 總覽關鍵字
        if re.search(r"總覽|彙總|overview|summary", content, re.IGNORECASE):
            return BlockType.OVERVIEW

        # 封面（第1頁頂部大字）
        if page == 1 and y0 < 200 and font_size >= 16:
            return BlockType.COVER

        # 標題（字型大小判斷）
        if font_size >= 16:
            return BlockType.HEADING1
        if font_size >= 13:
            return BlockType.HEADING2

        # 章節序號模式
        if re.match(r"^[一二三四五六七八九十]+[、.]|^\d+\.", content.strip()):
            return BlockType.HEADING1

        return BlockType.BODY

    # ── 模型載入 ──────────────────────────────────────────────

    @classmethod
    def _load_model(cls):
        global _model
        if _model is not None:
            return _model

        from pdf_editor.services.model_registry import ModelRegistry
        model_path = ModelRegistry.path("multilingual-e5-large-instruct")

        if model_path is None:
            return None

        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(model_path, device="cpu")
            logger.info("[Classifier] 模型載入成功：%s", model_path)
            return _model
        except Exception as e:
            logger.warning("[Classifier] 模型載入失敗：%s，改用 rule-based", e)
            return None
