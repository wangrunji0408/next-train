#!/usr/bin/env python3
"""
按线路批量解析时刻表图片 → JSONL

用法:
    .venv/bin/python scripts/parse_line_ocr.py -l 10 [-m auto] [-g 0.022] [-o output.jsonl]
    .venv/bin/python scripts/parse_line_ocr.py -l 亦庄

参数:
    -l, --line    线路号（必填），如 10、亦庄、首都机场
    -m, --method  小时列检测方法: auto / scan / rowlead（默认 auto）
    -g, --gap     分钟合并间距（默认 0.022，京港密排可用 0.0 强制两两合并）
    -o, --output  输出文件（默认 data/lines/{line}.jsonl）
    -d, --debug   输出调试信息
    --dry         只统计不写文件
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from timetable_ocr import parse_image_full


def main():
    parser = argparse.ArgumentParser(description="按线路批量解析时刻表图片")
    parser.add_argument("-l", "--line", required=True, help="线路号")
    parser.add_argument("-m", "--method", default="auto", choices=["auto", "scan", "rowlead"])
    parser.add_argument("-g", "--gap", type=float, default=0.022, help="分钟合并间距")
    parser.add_argument("-o", "--output", default=None, help="输出文件")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--dry", action="store_true", help="只统计不写文件")
    args = parser.parse_args()

    timetables_dir = Path("timetables")
    images = sorted(timetables_dir.glob(f"{args.line}-*.jpg"))
    if not images:
        # 处理线路号带中文字符的情况，确保文件名匹配
        images = sorted([p for p in timetables_dir.glob("*.jpg") if p.stem.split("-")[0] == args.line])
    if not images:
        print(f"错误: 未找到线路 {args.line} 的图片")
        sys.exit(1)

    # 收集站点列表（从文件名第二段）
    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])

    output = args.output or f"data/lines/{args.line}.jsonl"
    os.makedirs(os.path.dirname(output), exist_ok=True)

    print(f"线路 {args.line}: {len(images)} 张图片, method={args.method}, gap={args.gap}, {len(station_list)}站")
    success = 0
    fail = 0
    fail_list = []

    with open(output, "w", encoding="utf-8") as fout:
        for i, img_path in enumerate(images, 1):
            record = parse_image_full(str(img_path), debug=args.debug,
                                      method=args.method, minute_gap=args.gap,
                                      station_list=station_list)
            if record is None:
                fail += 1
                fail_list.append(img_path.name)
                print(f"  ❌ [{i}/{len(images)}] {img_path.name}: 解析失败")
                continue
            success += 1
            if not args.dry:
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            if args.debug:
                print(f"  ✓ [{i}/{len(images)}] {img_path.name}: "
                      f"开往{record['destination']} {record['operating_time']} "
                      f"{len(record['schedule_times'])} 个时间点")

    print(f"\n线路 {args.line}: 成功 {success}, 失败 {fail}")
    if fail_list:
        print(f"失败图片: {fail_list}")
    if not args.dry:
        print(f"输出: {output}")


if __name__ == "__main__":
    main()
