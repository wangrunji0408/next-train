#!/usr/bin/env python3
"""
后处理：移除时刻表 JSONL 中造成 1 分钟间隔的幻影时间点。

1 分钟间隔几乎总是 OCR 误配对产生的幻影分钟（圆圈符号干扰、丢位数字等），
真实地铁发车间隔 >= 2 分钟。check_timetable.py 将其计为错误。

用法：
    .venv/bin/python scripts/parsers/clean_1min_gaps.py <线路1> [线路2] ...   # 处理 data/lines/<线路>.jsonl
    .venv/bin/python scripts/parsers/clean_1min_gaps.py <file.jsonl>          # 直接处理文件
"""
import json
import os
import sys
from pathlib import Path


def parse(t):
    h, m = map(int, t.split(':'))
    if h == 24:
        h = 0
    return h * 60 + m


def clean_schedule(times):
    """移除每个 1 分钟间隔中的第二个分钟（幻影分钟）。"""
    result = []
    prev = None
    for t in times:
        cur = parse(t)
        if prev is not None:
            gap = cur - prev
            if gap == 1:
                continue  # 幻影分钟
            if gap <= 0:
                # 跨午夜回绕（如 23:52 -> 24:00）
                if gap + 1440 == 1:
                    continue
        result.append(t)
        prev = cur
    return result


def process_file(path: Path):
    if not path.exists():
        print(f'{path}: 文件不存在')
        return
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    n_in = n_out = 0
    for d in records:
        orig = len(d['schedule_times'])
        cleaned = clean_schedule(d['schedule_times'])
        d['schedule_times'] = cleaned
        n_in += orig
        n_out += len(cleaned)
    with open(path, 'w', encoding='utf-8') as f:
        for d in records:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')
    print(f'{path}: {n_in} -> {n_out} 个时间点（移除 {n_in - n_out} 个幻影分钟）')


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    here = Path(os.path.dirname(os.path.abspath(__file__)))
    lines_dir = here.parent.parent / 'data' / 'lines'
    for arg in args:
        # 支持传线路名或直接传文件路径
        if arg.endswith('.jsonl') and os.path.exists(arg):
            process_file(Path(arg))
        else:
            process_file(lines_dir / f'{arg}.jsonl')


if __name__ == '__main__':
    main()
