#!/usr/bin/env python3
"""Post-processing: re-parse records with severe time gaps sequentially (deterministic).

Batch OCR under parallel load is non-deterministic on macOS Vision, degrading some
records. This script re-parses any record whose schedule has a gap >= threshold using
a single-process parse (deterministic) and replaces it if the re-parse is better.
"""
import json, os, sys, time
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
from parse_lines_airport import parse_image, STATIONS

THRESHOLD = 30  # minutes


def max_gap(times):
    prev = None
    worst = 0
    for ts in times:
        h, m = map(int, ts.split(':'))
        cur = h * 60 + m
        if prev is not None:
            gap = cur - prev
            if gap > worst:
                worst = gap
        prev = cur
    return worst


def main():
    line = sys.argv[1]
    path = f"/Users/wangrunji/Codes/next-train/data/lines/{line}.jsonl"
    if not os.path.exists(path):
        print(f"no file {path}")
        sys.exit(1)
    records = [json.loads(l) for l in open(path)]
    station_list = STATIONS.get(line, [])
    replaced = 0
    unchanged = 0
    for r in records:
        if max_gap(r["schedule_times"]) < THRESHOLD:
            continue
        img = f"/Users/wangrunji/Codes/next-train/timetables/{r['filename']}"
        for attempt in range(3):
            try:
                rec, info = parse_image(img, station_list, route=line)
                break
            except Exception:
                rec, info = None, None
                time.sleep(1.0)
        if rec is None:
            unchanged += 1
            continue
        new_gap = max_gap(rec["schedule_times"])
        old_gap = max_gap(r["schedule_times"])
        if new_gap < old_gap:
            r["destination"] = rec["destination"]
            r["operating_time"] = rec["operating_time"]
            r["schedule_times"] = rec["schedule_times"]
            replaced += 1
            print(f"  REPLACED {r['filename']}: gap {old_gap}->{new_gap} "
                  f"dest {rec['destination']} op {rec['operating_time']} n={len(rec['schedule_times'])}")
        else:
            unchanged += 1
            print(f"  kept {r['filename']}: gap {old_gap} (reparse {new_gap})")
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"line {line}: replaced={replaced} unchanged={unchanged}")


if __name__ == "__main__":
    main()
