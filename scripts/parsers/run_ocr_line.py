#!/usr/bin/env python3
"""Resilient line OCR driver: processes images one-by-one with retry + progress, flushes output.
Usage: .venv/bin/python /tmp/run_ocr_line.py <line> [method] [gap]
Output: data/lines/<line>.jsonl
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/wangrunji/Codes/next-train/scripts")
sys.path.insert(0, "/Users/wangrunji/Codes/next-train")

from timetable_ocr import parse_image_full

line = sys.argv[1]
method = sys.argv[2] if len(sys.argv) > 2 else "auto"
gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.022

timetables_dir = Path("/Users/wangrunji/Codes/next-train/timetables")
images = sorted(timetables_dir.glob(f"{line}-*.jpg"))
if not images:
    images = sorted([p for p in timetables_dir.glob("*.jpg") if p.stem.split("-")[0] == line])
if not images:
    print(f"错误: 未找到线路 {line} 的图片")
    sys.exit(1)

station_list = []
for p in images:
    parts = p.stem.split("-")
    if len(parts) > 1 and parts[1] not in station_list:
        station_list.append(parts[1])

output = f"/Users/wangrunji/Codes/next-train/data/lines/{line}.jsonl"
os.makedirs(os.path.dirname(output), exist_ok=True)

print(f"线路 {line}: {len(images)} 张图片, method={method}, gap={gap}, {len(station_list)}站", flush=True)
success = 0
fail = 0
fail_list = []

with open(output, "w", encoding="utf-8") as fout:
    for i, img_path in enumerate(images, 1):
        record = None
        for attempt in range(3):
            try:
                record = parse_image_full(str(img_path), method=method, minute_gap=gap,
                                          station_list=station_list)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
        if record is None:
            fail += 1
            fail_list.append(img_path.name)
            print(f"  X [{i}/{len(images)}] {img_path.name}: 解析失败", flush=True)
            continue
        success += 1
        fout.write(json.dumps(record, ensure_ascii=False) + "\n")
        fout.flush()
        if i % 10 == 0:
            print(f"  ... {i}/{len(images)} 完成 (成功{success}, 失败{fail})", flush=True)

print(f"\n线路 {line}: 成功 {success}, 失败 {fail}", flush=True)
if fail_list:
    print(f"失败图片: {fail_list}", flush=True)
print(f"输出: {output}", flush=True)
