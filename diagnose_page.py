"""
診斷工具：列出 file_caches/{doc_id}/ 內所有區塊的 page 欄位，
確認是否真的存在頁碼不一致導致誤判分頁的狀況。
用法：python diagnose_page.py <doc_id 或檔案路徑前綴>
"""
import json
import sys
from pathlib import Path

cache_root = Path("file_caches")
if not cache_root.exists():
    print("找不到 file_caches/ 目錄，請在 pdf-editor 專案根目錄執行")
    sys.exit(1)

dirs = sorted(
    [d for d in cache_root.iterdir() if d.is_dir() and not d.name.startswith(".")],
    key=lambda p: p.stat().st_mtime, reverse=True
)
if not dirs:
    print("file_caches/ 是空的")
    sys.exit(1)

target = dirs[0]  # 最新一筆快取
print(f"檢查最新快取：{target.name}")

texts = json.loads((target / "texts.json").read_text(encoding="utf-8"))
tables = json.loads((target / "tables.json").read_text(encoding="utf-8"))
structure = json.loads((target / "structure.json").read_text(encoding="utf-8"))

print(f"\nstructure 共 {len(structure)} 個區塊，依序列出 (page, type, id, y0):\n")
for blk_id in structure:
    blk = texts.get(blk_id) or tables.get(blk_id)
    if blk is None:
        print(f"  [缺失] {blk_id}")
        continue
    page = blk.get("page")
    btype = blk.get("type")
    bbox = blk.get("bbox", [0,0,0,0])
    y0 = bbox[1] if len(bbox) > 1 else None
    print(f"  page={page}  type={btype:10s}  y0={y0}  id={blk_id}")
