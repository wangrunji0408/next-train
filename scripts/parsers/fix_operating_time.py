#!/usr/bin/env python3
"""Post-processor: fill missing operating_time for data/lines/<line>.jsonl.

The OCR sometimes garbles 工作日/双休日 (e.g. reads "日作" or reverses chars).
Strategy:
1. Re-run extract_metadata on the gray OCR to get operating_time.
2. If still missing, use the filename suffix heuristic:
   - suffix 1/2 -> 工作日, suffix 3/4/5/6 -> 双休日
   (verified against existing data where suffix is unambiguous)

Usage: .venv/bin/python scripts/parsers/fix_operating_time.py <line>
"""
import json
import sys
import glob
from pathlib import Path

sys.path.insert(0, "/Users/wangrunji/Codes/next-train/scripts")
sys.path.insert(0, "/Users/wangrunji/Codes/next-train")

from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac
from timetable_ocr import group_rows, extract_metadata

line = sys.argv[1]
path = f"/Users/wangrunji/Codes/next-train/data/lines/{line}.jsonl"
if not Path(path).exists():
    print(f"错误: {path} 不存在")
    sys.exit(1)

station_list = sorted(set(Path(p).stem.split("-")[1]
                          for p in glob.glob(f"/Users/wangrunji/Codes/next-train/timetables/{line}-*.jpg")
                          if len(Path(p).stem.split("-")) > 1))


def heuristic_op(fname):
    """Infer operating_time from filename suffix."""
    sfx = fname.rsplit("-", 1)[1].split(".")[0]
    try:
        n = int(sfx)
    except ValueError:
        return None
    if n <= 2:
        return "工作日"
    return "双休日"


def detect_op_from_ocr(anns_g):
    """Look for 工作日/双休日 markers in garbled OCR text."""
    rows = group_rows(anns_g)
    for y, tokens in rows:
        texts = [tok[0] for tok in tokens if len(tok) >= 2]
        line = "".join(texts)
        if not line:
            continue
        # reversed/partial forms
        if "日作" in line or "作日" in line or "Weekday" in line.lower() or "Weekdays" in line.lower():
            return "工作日"
        if "日休" in line or "休日" in line or "Weekend" in line.lower() or "Weekends" in line.lower():
            return "双休日"
    return None


records = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
fixed = 0
still_missing = 0
for rec in records:
    if rec.get("operating_time"):
        continue
    fname = rec.get("filename", "")
    img = f"/Users/wangrunji/Codes/next-train/timetables/{fname}"
    op = None
    if Path(img).exists():
        try:
            pairs = convert_and_binarize_image(img)
            gray, _ = pairs[0]
            anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
            _, op = extract_metadata(anns_g, station_list=station_list)
            if not op:
                op = detect_op_from_ocr(anns_g)
        except Exception:
            op = None
    if not op:
        op = heuristic_op(fname)
    if op:
        rec["operating_time"] = op
        fixed += 1
    else:
        still_missing += 1

with open(path, "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"线路 {line}: 修复 {fixed} 条, 仍缺失 {still_missing} 条")
