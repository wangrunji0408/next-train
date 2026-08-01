#!/usr/bin/env python3
"""Parse one timetable image via subprocess (crash-isolated)."""
import sys, os, json, glob
sys.path.insert(0, 'scripts')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from parse_lines_jinggang import parse_image


def main():
    line = sys.argv[1]
    img = sys.argv[2]
    station_list = []
    for p in sorted(glob.glob(f'timetables/{line}-*.jpg')):
        st = Path(p).stem.split('-')[1]
        if st not in station_list:
            station_list.append(st)
    r = parse_image(img, station_list=station_list)
    if r is None:
        sys.exit(3)
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0)


if __name__ == '__main__':
    main()
