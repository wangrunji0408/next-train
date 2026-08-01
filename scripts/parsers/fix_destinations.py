#!/usr/bin/env python3
"""
Post-processor: re-extract missing destinations for records in data/lines/*.jsonl
using the improved fuzzy matcher (handles garbled "往<站>站" direction lines).

Usage: .venv/bin/python scripts/parsers/fix_destinations.py <line>
"""
import json
import os
import sys
import glob
from pathlib import Path

sys.path.insert(0, "/Users/wangrunji/Codes/next-train/scripts")
sys.path.insert(0, "/Users/wangrunji/Codes/next-train")
sys.path.insert(0, "/Users/wangrunji/Codes/next-train/scripts/parsers")

from parse_lines_split_hour import fuzzy_destination
from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac

line = sys.argv[1]
out_path = f"/Users/wangrunji/Codes/next-train/data/lines/{line}.jsonl"
if not os.path.exists(out_path):
    print(f"错误: {out_path} 不存在")
    sys.exit(1)

# station list from filenames
station_list = sorted(set(Path(p).stem.split("-")[1]
                          for p in glob.glob(f"/Users/wangrunji/Codes/next-train/timetables/{line}-*.jpg")
                          if len(Path(p).stem.split("-")) > 1))

records = [json.loads(l) for l in open(out_path, encoding="utf-8") if l.strip()]
fixed = 0
missing = 0
for rec in records:
    if rec.get("destination"):
        continue
    fname = rec.get("filename", "")
    img = f"/Users/wangrunji/Codes/next-train/timetables/{fname}"
    if not os.path.exists(img):
        missing += 1
        continue
    try:
        pairs = convert_and_binarize_image(img)
        gray, _ = pairs[0]
        anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
        dest = fuzzy_destination(anns_g, station_list)
        if dest:
            rec["destination"] = dest
            fixed += 1
        else:
            missing += 1
    except Exception as e:
        missing += 1

with open(out_path, "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"线路 {line}: 修复 {fixed} 条, 仍缺失 {missing} 条")
