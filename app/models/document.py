"""
models/document.py — 文件結構資料模型

所有服務、路由都以這些 dataclass 為共同語言，
序列化/反序列化統一透過 to_dict() / from_dict()。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── 區塊類型常數 ──────────────────────────────────────────────
class BlockType:
    COVER    = "cover"
    OVERVIEW = "overview"
    HEADING1 = "heading_1"
    HEADING2 = "heading_2"
    BODY     = "body"
    TABLE    = "table"
    IMAGE    = "image"
    APPENDIX = "appendix"
    UNKNOWN  = "unknown"

    ALL = {COVER, OVERVIEW, HEADING1, HEADING2, BODY, TABLE, IMAGE, APPENDIX, UNKNOWN}


# ── 表格資料 ──────────────────────────────────────────────────
@dataclass
class TableData:
    headers: list[str]               = field(default_factory=list)
    rows: list[list[str]]            = field(default_factory=list)
    total: Optional[float]           = None
    linked_overview_cell: Optional[str] = None   # e.g. "B3"
    linked_overview_block: Optional[str] = None  # block_id of overview table

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TableData":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── 單一區塊 ──────────────────────────────────────────────────
@dataclass
class Block:
    id: str                          = field(default_factory=lambda: f"blk-{uuid.uuid4().hex[:8]}")
    type: str                        = BlockType.UNKNOWN
    page: int                        = 1
    bbox: list[float]                = field(default_factory=lambda: [0, 0, 0, 0])
    content: str                     = ""
    table_data: Optional[TableData]  = None
    image_path: Optional[str]        = None     # 相對於 file_caches/{hash}/images/
    font_size: Optional[float]       = None
    font_name: Optional[str]         = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # table_data 已被 asdict 展開，不需額外處理
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        td_raw = d.pop("table_data", None)
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if td_raw:
            obj.table_data = TableData.from_dict(td_raw)
        return obj


# ── 總覽頁聯動關係 ────────────────────────────────────────────
@dataclass
class OverviewLink:
    """記錄某個子表格 block 的 total 對應到總覽頁哪個 cell。"""
    source_block_id: str   = ""     # 子表格 block id
    overview_block_id: str = ""     # 總覽頁 table block id
    cell: str              = ""     # e.g. "B3"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OverviewLink":
        return cls(**d)


# ── 完整文件 ──────────────────────────────────────────────────
@dataclass
class Document:
    doc_id: str                      = ""
    filename: str                    = ""
    page_count: int                  = 0
    blocks: list[Block]              = field(default_factory=list)
    overview_links: list[OverviewLink] = field(default_factory=list)

    # ── 查詢工具 ──────────────────────────────────────────────
    def get_block(self, block_id: str) -> Optional[Block]:
        for b in self.blocks:
            if b.id == block_id:
                return b
        return None

    def blocks_by_type(self, block_type: str) -> list[Block]:
        return [b for b in self.blocks if b.type == block_type]

    def blocks_on_page(self, page: int) -> list[Block]:
        return [b for b in self.blocks if b.page == page]

    # ── 序列化 ────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "doc_id":         self.doc_id,
            "filename":       self.filename,
            "page_count":     self.page_count,
            "blocks":         [b.to_dict() for b in self.blocks],
            "overview_links": [ol.to_dict() for ol in self.overview_links],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        doc = cls(
            doc_id     = d.get("doc_id", ""),
            filename   = d.get("filename", ""),
            page_count = d.get("page_count", 0),
        )
        doc.blocks = [Block.from_dict(b) for b in d.get("blocks", [])]
        doc.overview_links = [OverviewLink.from_dict(ol) for ol in d.get("overview_links", [])]
        return doc
