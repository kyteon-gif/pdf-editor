"""
診斷工具：直接呼叫 renderer.build_html() 印出完整 HTML，
存成檔案供肉眼檢查，或用瀏覽器打開直接看渲染結果。

用法（在 pdf-editor/ 專案根目錄執行）：
    python dump_html.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, ".")

from pdf_editor.services.cache_manager import CacheManager
from pdf_editor.services.renderer import build_html

cache_root = Path("file_caches")
if not cache_root.exists():
    print("找不到 file_caches/ 目錄")
    sys.exit(1)

dirs = sorted(
    [d for d in cache_root.iterdir() if d.is_dir() and not d.name.startswith(".")],
    key=lambda p: p.stat().st_mtime, reverse=True
)
if not dirs:
    print("file_caches/ 是空的，請先上傳一次 PDF")
    sys.exit(1)

target = dirs[0]
doc_id = target.name
print(f"使用最新快取：{doc_id}")

cm = CacheManager.from_doc_id(doc_id)
doc = cm.load()

html = build_html(doc, cm)

out_path = Path("debug_export.html")
out_path.write_text(html, encoding="utf-8")
print(f"已輸出至 {out_path.resolve()}")
print(f"HTML 總長度：{len(html)} 字元")

# 順便列出每個區塊的高度估算資訊，協助判斷哪裡撐爆版面
texts = doc.get("texts", {})
tables = doc.get("tables", {})
structure = doc.get("structure", [])

print("\n各區塊摘要：")
for blk_id in structure:
    blk = texts.get(blk_id) or tables.get(blk_id)
    if blk is None:
        continue
    btype = blk.get("type")
    bbox = blk.get("bbox", [0,0,0,0])
    w = bbox[2] - bbox[0] if len(bbox) == 4 else 0
    h = bbox[3] - bbox[1] if len(bbox) == 4 else 0
    extra = ""
    if btype in ("table", "overview"):
        rows = blk.get("raw_rows", [])
        extra = f"  rows={len(rows)}"
    print(f"  {blk_id:20s} type={btype:10s} bbox_w={w:.1f} bbox_h={h:.1f}{extra}")
