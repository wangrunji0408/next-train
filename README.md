# Next Train

A dependency-free web app that shows when the next train leaves the nearest
metro station in Beijing. Timetables come from the operators' official
station posters, OCR'd into structured data.

## Features

- 📍 locate the nearest station (or search by name)
- 🕐 next departure + live countdown
- ↔️ pick a direction for multi-terminus stations
- 🌗 light/dark theme, Chinese/English UI
- 📊 27 lines, 1991 timetables (weekday / weekend variants)

## Run

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Everything is static; opening `index.html` via `file://` fails on `fetch`.
For geolocation on a phone (HTTPS is required), use
`.venv/bin/python scripts/serve_https.py 8443`.

## Layout

```
.
├── index.html / app.js / i18n.js   # front end, no build step
├── data/
│   ├── routes.json                 # line colours + station coordinates
│   └── timetable.jsonl             # the dataset (27 lines)
├── timetables/                     # poster images (gitignored, ~2 GB)
├── scripts/
│   ├── parse_ocr.py                # ★ poster image -> data/lines/*.jsonl
│   ├── ocr/                        # OCR engine (prep, parser, meta, legacy fallback)
│   ├── download_timetables.py      # fetch posters from the three operators
│   ├── check_timetable.py          # data quality checks
│   ├── check_line_updates.py       # read "updated YYYY-MM" off bjsubway.com
│   ├── merge_lines.py              # data/lines/*.jsonl -> data/timetable.jsonl
│   ├── fetch_osm_subway.py         # refresh station coordinates from OSM
│   └── serve_https.py              # local HTTPS server for phone testing
└── work/                           # parse artefacts (gitignored)
```

## Data format

One JSON object per timetable in `data/timetable.jsonl`:

```json
{"filename": "1-万寿路-1.jpg", "route": "1", "station": "万寿路",
 "destination": "环球度假区", "operating_time": "工作日",
 "schedule_times": ["05:11", "05:15", "05:19"]}
```

`operating_time` is one of `工作日` / `双休日` / `平日` / `星期五`.

## Refreshing the data

```bash
.venv/bin/python scripts/download_timetables.py -l 14
.venv/bin/python scripts/parse_ocr.py --lines 14,17
.venv/bin/python scripts/merge_lines.py -k -o data/timetable.jsonl
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl
```

Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
plus `brew install tesseract` (eng + snum language data).

## Sources

- Beijing Subway — <https://www.bjsubway.com/station/xltcx/> (20 lines)
- MTR Beijing — <https://www.mtr.bj.cn/service/line/> (4/14/16/17)
- Beijing Rail Operations — <https://www.bjmoa.cn/trainTimeList_363.html> (19, 燕房, 大兴机场)

Line colours follow the Beijing Metro colour template (DB11/T 657.2).

## Limitations

- Static timetable; holidays and temporary changes are not reflected.
- bjsubway.com has been down since 2026-10, so those 20 lines cannot be refreshed.
- 燕房 / 大兴机场 posters use a square layout handled by a separate fallback parser.
