"""
輔助診斷：列出所有 heading_1/heading_2 區塊的實際 font_size，
確認 9pt 閾值是否能正確區分「真標題」與「圖表小標籤」。
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, ".")
from pdf_editor.services.cache_manager import CacheManager

cache_root = Path("file_caches")
dirs = sorted(
    [d for d in cache_root.iterdir() if d.is_dir() and not d.name.startswith(".")],
    key=lambda p: p.stat().st_mtime, reverse=True
)
target = dirs[0]
doc_id = target.name

cm = CacheManager.from_doc_id(doc_id)
doc = cm.load()
texts = doc.get("texts", {})

print(f"快取：{doc_id}\n")
print("所有 heading_1/heading_2 區塊的 font_size：\n")
for blk_id, blk in texts.items():
    if blk.get("type") in ("heading_1", "heading_2"):
        fs = blk.get("font_size")
        content = (blk.get("content") or "")[:20]
        print(f"  {blk_id:20s}  font_size={fs}  content={content!r}")
