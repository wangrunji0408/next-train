"""Export OCR records to the app's timetable format.

Reads the compact JSONL written by ``parse_line.py`` plus the hand-checked
metadata in ``scripts/ocr/meta/<line>/meta.json`` and writes one record per
timetable to ``data/lines/<line>.jsonl``:

    {"filename", "route", "station", "destination", "operating_time",
     "schedule_times": ["HH:MM", ...]}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compact  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = {
    'weekday': '工作日',
    'weekend': '双休日',
    'ordinary': '平日',
    'mon-thu_weekend': '平日',
    'friday': '星期五',
    'key_guaranteed': '星期五',
    'sunday_extension': '平日',
}


def to_minutes(t):
    return int(t[:2]) * 60 + int(t[3:])


def drop_phantom_minutes(times):
    """Remove OCR phantom minutes that create 1-minute headways.

    A phantom is always the digit before a real minute (03 read as 02,03).
    Runs of >=3 consecutive minutes keep the ends, pairs keep the later one.
    """
    mins = [to_minutes(t) for t in times]
    n = len(mins)
    keep = [True] * n
    i = 0
    while i < n - 1:
        if mins[i + 1] - mins[i] != 1:
            i += 1
            continue
        start = i
        while i + 1 < n and mins[i + 1] - mins[i] == 1:
            i += 1
        end = i
        if end - start + 1 >= 3:
            for k in range(start + 1, end):
                keep[k] = False
        else:
            keep[start] = False
        i += 1
    return [t for k, t in enumerate(times) if keep[k]]


def drop_isolated_leading(times):
    """Drop legend digits read as times far before the first real train."""
    out = list(times)
    while len(out) > 1:
        gap = next((i for i in range(len(out) - 1)
                    if to_minutes(out[i + 1]) - to_minutes(out[i]) > 120), None)
        if gap is None:
            break
        out = out[gap + 1:]
    return out


def load_meta(line):
    p = os.path.join(HERE, 'meta', line, 'meta.json')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def export_line(line, src_path, out_path):
    meta = load_meta(line)
    images = meta.get('_images') or {}
    records = []
    with open(src_path, encoding='utf-8') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            rec = compact.expand_record(json.loads(raw))
            base = rec['id'].split('#')[0]
            suffix = base.rsplit('-', 1)[-1]
            m = dict(meta.get(suffix) or {})
            m.update(images.get(base) or {})
            times = sorted({f"{t['hour']:02d}:{t['minute']:02d}"
                            for t in rec.get('times') or []})
            times = drop_phantom_minutes(times)
            times = drop_isolated_leading(times)
            if not times:
                continue
            service = m.get('service')
            operating_time = SERVICE.get(service) if service else None
            if operating_time == '工作日' and line == '大兴机场':
                operating_time = '平日'
            records.append({
                'filename': os.path.basename(rec['source']),
                'route': rec['line'],
                'station': rec['station'],
                'destination': m.get('direction'),
                'operating_time': operating_time,
                'schedule_times': times,
            })

    records.sort(key=lambda r: (r['station'], str(r['destination']),
                                str(r['operating_time'])))
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    missing = sum(1 for r in records if not r['destination'] or not r['operating_time'])
    print(f'[{line}] {len(records)} records -> {out_path}'
          + (f'  ({missing} without direction/service)' if missing else ''))
    return records
