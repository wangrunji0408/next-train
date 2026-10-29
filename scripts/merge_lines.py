#!/usr/bin/env python3
"""
合并 data/lines/ 下各线路的 JSONL 为最终 data/timetable.jsonl

用法:
    .venv/bin/python scripts/merge_lines.py [-o data/timetable.jsonl] [-c]

参数:
    -o, --output   输出文件（默认 data/timetable.jsonl）
    -c, --check    合并后自动运行 check_timetable.py 检查
    -d, --dedup    去重（同一 filename+destination+operating_time 只保留 schedule_times 最多的）
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="合并各线路 JSONL")
    parser.add_argument("-o", "--output", default="data/timetable.jsonl")
    parser.add_argument("-c", "--check", action="store_true")
    parser.add_argument("-d", "--dedup", action="store_true")
    parser.add_argument(
        "-k", "--keep",
        action="store_true",
        help="保留已有输出中未出现在 data/lines 的线路（局部更新时使用）",
    )
    args = parser.parse_args()

    lines_dir = Path("data/lines")
    if not lines_dir.exists():
        print("错误: data/lines 目录不存在")
        sys.exit(1)

    routes_in_lines = {f.stem for f in lines_dir.glob("*.jsonl")}

    all_records = []
    missing = []
    if args.keep and os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as fh:
            kept = [json.loads(line) for line in fh if line.strip()]
        kept = [r for r in kept if r.get("route") not in routes_in_lines]
        print(f"  保留原有线路: {len(kept)} 条")
        all_records.extend(kept)

    for f in sorted(lines_dir.glob("*.jsonl")):
        route = f.stem
        try:
            with open(f, encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh if line.strip()]
        except json.JSONDecodeError as e:
            print(f"  ⚠️ {route}: JSON 解析错误 {e}")
            continue
        print(f"  {route}: {len(records)} 条")
        all_records.extend(records)

    print(f"\n总计: {len(all_records)} 条记录")

    # 去重
    if args.dedup:
        seen = {}
        for r in all_records:
            key = (r.get("filename"), r.get("destination"), r.get("operating_time"))
            if key not in seen or len(r.get("schedule_times", [])) > len(seen[key].get("schedule_times", [])):
                seen[key] = r
        all_records = list(seen.values())
        print(f"去重后: {len(all_records)} 条")

    # 排序：按线路、站名、目的地、时段
    def safe(v):
        return v if isinstance(v, str) else ""

    all_records.sort(key=lambda r: (
        safe(r.get("route")),
        safe(r.get("station")),
        safe(r.get("destination")),
        safe(r.get("operating_time")),
    ))

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fout:
        for r in all_records:
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"输出: {args.output}")

    if args.check:
        os.system(f".venv/bin/python scripts/check_timetable.py -f {args.output}")


if __name__ == "__main__":
    main()
