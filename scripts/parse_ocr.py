#!/usr/bin/env python3
"""Timetable OCR pipeline: normalise posters, read the tables, write app data.

Usage:
  .venv/bin/python scripts/parse_ocr.py -l 14
  .venv/bin/python scripts/parse_ocr.py --lines 14,17
  .venv/bin/python scripts/parse_ocr.py --all
"""
import argparse
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr'))
import export  # noqa: E402
import parse_line  # noqa: E402
from prep import prep  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getcwd()
PREP_DIR = os.path.join(ROOT, 'work', 'prep')
FALLBACK_LINES = {'燕房', '大兴机场'}
ALL_LINES = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13',
             '14', '15', '16', '17', '18', '19', 'S1', '亦庄', '八通', '大兴机场',
             '房山', '昌平', '燕房', '首都机场']


def build_lines(lines, jobs=4):
    os.makedirs(PREP_DIR, exist_ok=True)
    tasks = []
    for line in lines:
        mm = parse_line.line_meta(line, {})
        oo = parse_line.line_overrides(line, {})
        for p in parse_line.images_for(line):
            tasks.append((line, p, mm, oo))

    results = defaultdict(lambda: ([], []))
    lock = threading.Lock()

    def work(task):
        line, p, mm, oo = task
        dst = os.path.join(PREP_DIR, os.path.basename(p).rsplit('.', 1)[0] + '.jpg')
        try:
            prep(p, dst)
            rs = parse_line.build_one(dst, mm, oo, orig=p)
        except Exception as e:  # noqa: BLE001
            return line, [], [dict(source=os.path.relpath(p, ROOT), error=repr(e)[:300])]
        rep = []
        for r in rs:
            rep.append(dict(source=r['source'], id=r['id'], n_times=len(r['times']),
                            stats=r.pop('_stats'), issues=r.pop('_issues'),
                            flags=r.pop('_flags')))
        return line, rs, rep

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for line, rs, rep in ex.map(work, tasks):
            with lock:
                results[line][0].extend(rs)
                results[line][1].extend(rep)

    for line in lines:
        parse_line.write_line(line, *results[line])
    return results


def main():
    ap = argparse.ArgumentParser(description='解析时刻表图片为 data/lines/*.jsonl')
    ap.add_argument('-l', '--line', help='线路，如 14')
    ap.add_argument('--lines', help='多条线路，逗号分隔')
    ap.add_argument('--all', action='store_true', help='全部线路')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--no-export', action='store_true', help='只解析不导出 app 格式')
    args = ap.parse_args()

    if args.all:
        lines = ALL_LINES
    elif args.lines:
        lines = [x.strip() for x in args.lines.split(',') if x.strip()]
    elif args.line:
        lines = [args.line]
    else:
        ap.error('需要 -l/--lines/--all 之一')

    for line in lines:
        out = os.path.join('data', 'lines', f'{line}.jsonl')
        if line in FALLBACK_LINES:
            # square poster layouts that the main engine cannot read
            sys.path.insert(0, os.path.join(HERE, 'ocr', 'legacy'))
            import airport
            airport.run_line(line, out, workers=args.jobs)
            continue
        build_lines([line], jobs=args.jobs)
        if not args.no_export:
            src = os.path.join(parse_line.OUT, f'{line}.jsonl')
            if os.path.exists(src):
                export.export_line(line, src, out)


if __name__ == '__main__':
    main()
