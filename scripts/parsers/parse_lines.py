#!/usr/bin/env python3
"""Custom parser for multiple lines: 3, 15, 18, 19, 首都机场, 燕房, 大兴机场.

Uses the improved coordinate-based approach from parse11.py:
- drop_hour_tokens: value-based hour stripping (handles OCR splitting hour into 2 tokens)
- merge_minutes: all-single-char pairwise; mixed rows greedy
- detect_hour_column_loose: lower ymin to catch 22-23 hours
- metadata extraction with station_list + English fallback

For Line 18: splits the image into left/right halves at x=0.5, then runs the
standard coordinate extraction on each half (the two directions are side-by-side).
"""
import sys, os, json, re
from pathlib import Path
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')
from timetable_ocr import (group_rows, merge_tokens,
                           extract_metadata, is_num, extract_destination_candidate)
from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac
from PIL import Image

# English -> Chinese station mapping (for "To XXX" headers)
EN_MAP = {
    "Moshikou": "模式口", "Xinshougang": "新首钢", "Jinanqiao": "金安桥",
    "Beixinan": "北辛安", "Sishui": "四惠", "Sihuidong": "四惠东",
    "Fengbo": "俸伯", "Beishatan": "北沙滩", "Datunludong": "大屯路东",
    "Dongsi": "东四十条", "Dongbabei": "东坝北", "Dongba": "东坝",
    "Dongbanan": "东坝南", "Shifoying": "石佛营", "Chaoyanggongyuan": "朝阳公园",
    "Chaoyangzhan": "朝阳站", "Yaojiayuan": "姚家园", "Tuanjiehu": "团结湖",
    "Gongrentiyuchang": "工人体育场",
    "Capital": "首都机场", "Airport": "首都机场", "Beixinqiao": "北新桥",
    "Beijing": "首都机场", "Jichang": "首都机场",
}


def greedy_merge(tokens):
    """Order-based pairing: 2-char token = standalone minute; 1-char pairs with next."""
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        text, x = tokens[i]
        if len(text) == 2 and is_num(text):
            result.append((text, x))
            i += 1
        elif len(text) == 1 and i + 1 < n and len(tokens[i+1][0]) == 1:
            result.append((text + tokens[i+1][0], x))
            i += 2
        else:
            i += 1
    return result


def merge_minutes(tokens, gap):
    if not tokens:
        return []
    if all(len(t) == 1 for t, _ in tokens) and len(tokens) >= 2:
        result = []
        for i in range(0, len(tokens) - 1, 2):
            result.append((tokens[i][0] + tokens[i+1][0], tokens[i][1]))
        if len(tokens) % 2 == 1:
            result.append(tokens[-1])
        return result
    return greedy_merge(tokens)


def detect_hour_column_loose(anns, ymin=0.055, hour_gap=0.020, x_min=0.02, x_max=0.50):
    """rowlead-style hour detection but with lower ymin to catch hour 22.
    Returns (hour_map {hour:y}, hour_x)."""
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (ymin < y < 0.90):
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2 and is_num(tok[0]):
                nums.append((tok[0], tok[2][0]))
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        merged = merge_tokens(nums, hour_gap)
        text, x = merged[0]
        try:
            hv = int(text)
        except ValueError:
            continue
        if 5 <= hv <= 24 and x_min < x < x_max:
            candidates.append((y, hv, x))
    if len(candidates) < 6:
        return None, None
    xs = sorted(c[2] for c in candidates)
    best_center, best_count = None, 0
    for cx in xs:
        count = sum(1 for _, _, x in candidates if abs(x - cx) < 0.015)
        if count > best_count:
            best_count, best_center = count, cx
    if best_center is None or best_count < 6:
        return None, None
    col = {}
    for y, hv, x in candidates:
        if abs(x - best_center) < 0.015:
            col[hv] = y
    if len(col) < 5:
        return None, None
    hours = sorted(col)
    result = dict(col)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i + 1]
        if h2 - h1 > 1:
            y1, y2 = col[h1], col[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result, best_center


def detect_hour_column_monotonic(anns, ymin=0.06, ymax=0.90, hour_gap=0.020,
                                 x_min=0.02, x_max=0.50):
    """Rowlead-style hour detection that CORRECTS OCR misread hour values.

    Schedule rows are in consecutive hour order (bottom row = early hour, top = late).
    We sort candidates by y and assign a consecutive descending hour sequence that
    best matches the OCR values (which may be misread for some rows).
    Returns (hour_map, hour_x)."""
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (ymin < y < ymax):
            continue
        nums = [(t[0], t[2][0]) for t in tokens if len(t) >= 2 and is_num(t[0])]
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        merged = merge_tokens(nums, hour_gap)
        for text, x in merged[:2]:
            if x > x_max:
                break
            try:
                hv = int(text)
            except ValueError:
                continue
            if 5 <= hv <= 24:
                candidates.append((y, hv, x))
                break
    if len(candidates) < 6:
        return None, None
    xs = sorted(c[2] for c in candidates)
    best_center, best_count = None, 0
    for cx in xs:
        count = sum(1 for _, _, x in candidates if abs(x - cx) < 0.015)
        if count > best_count:
            best_count, best_center = count, cx
    if best_center is None or best_count < 6:
        return None, None
    col = [(y, hv) for y, hv, x in candidates if abs(x - best_center) < 0.015]
    col.sort(key=lambda v: -v[0])  # top to bottom (y descending)
    n = len(col)
    if n < 8:
        return None, best_center
    hours = [hv for _, hv in col]
    # Choose the top hour (23 or 24 typically) maximizing agreement with OCR values.
    best_top, best_score = None, -1
    for top in range(5, 25):
        if top - n + 1 < 1:
            continue
        seq = [top - i for i in range(n)]
        score = sum(1 for a, b in zip(seq, hours) if a == b)
        if score > best_score:
            best_score, best_top = score, top
    if best_top is None:
        return None, best_center
    result = {}
    for i, (y, hv) in enumerate(col):
        h = best_top - i
        if 5 <= h <= 24:
            result[h] = y
    if len(result) < 8:
        return None, best_center
    return result, best_center


def drop_hour_tokens(nums, h):
    """Drop leading hour-column tokens. nums: [(text,x)] sorted by x. h: assigned hour.
    Returns index to slice from."""
    if not nums:
        return 0
    t0 = nums[0][0]
    if is_num(t0) and int(t0) == h:
        return 1
    if len(nums) >= 2:
        t1 = nums[1][0]
        if is_num(t0) and is_num(t1) and int(t0 + t1) == h:
            return 2
    # fallback: x-threshold based drop (hour column usually leftmost)
    i = 0
    while i < len(nums) and nums[i][1] < 0.105:
        i += 1
    return i


def _extract_schedule_from_anns(anns_g, anns_b, ymin=0.06, ymax=0.90, gap=0.022,
                                hour_ymin=0.055, hour_x_max=0.50):
    """Core schedule extraction from grayscale+binary annotations.
    Returns list of times sorted.
    Hour column: prefer binary annotations (matches minute rows' y positions exactly).
    Fall back to gray if binary fails or has too few hours."""
    hour_map, hour_x = detect_hour_column_loose(anns_b, ymin=hour_ymin, x_max=hour_x_max)
    if hour_map is None or len(hour_map) < 8:
        hour_map, hour_x = detect_hour_column_monotonic(anns_b, ymin=hour_ymin, x_max=hour_x_max)
    if hour_map is None or len(hour_map) < 8:
        hour_map, hour_x = detect_hour_column_loose(anns_g, ymin=hour_ymin, x_max=hour_x_max)
    if hour_map is None or len(hour_map) < 8:
        hour_map, hour_x = detect_hour_column_monotonic(anns_g, ymin=hour_ymin, x_max=hour_x_max)
    if not hour_map:
        return None
    result = {h: [] for h in hour_map}
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (ymin < y < ymax):
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2 and is_num(tok[0]):
                nums.append((tok[0], tok[2][0]))
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.025:
            continue
        # Filter: drop tokens left of the hour column (legend/footer digits pollute rows)
        if hour_x is not None:
            nums = [v for v in nums if v[1] >= hour_x - 0.015]
            if not nums:
                continue
        drop = drop_hour_tokens(nums, best_h)
        merged = merge_minutes(nums[drop:], gap)
        for text, x in merged:
            try:
                m = int(text)
                if 0 <= m <= 59:
                    result[best_h].append(m)
            except ValueError:
                pass
    times = []
    for h in sorted(result):
        for m in sorted(set(result[h])):
            times.append(f"{h:02d}:{m:02d}")
    return times if times else None


def extract_schedule_custom(path, gap=0.022, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    times = _extract_schedule_from_anns(anns_g, anns_b, gap=gap)
    return times, (anns_g, anns_b)


def _split_image_crop(gray, binary, split_x=0.5):
    """Crop gray and binary into left/right halves at split_x."""
    w, h = gray.size
    sx = int(w * split_x)
    Lg, Lb = gray.crop((0, 0, sx, h)), binary.crop((0, 0, sx, h))
    Rg, Rb = gray.crop((sx, 0, w, h)), binary.crop((sx, 0, w, h))
    return (Lg, Lb), (Rg, Rb)


def _line18_side_meta(anns, station_list=None):
    """Extract (destination, operating_time) from one side's grayscale annotations.
    Metadata is written vertically along the outer edge."""
    # Collect Chinese chars sorted by y (top to bottom)
    cn_tokens = []
    for t, c, b in anns:
        if len(t) >= 1 and any('一' <= ch <= '鿿' for ch in t):
            cn_tokens.append((t, b[1], b[0]))
    cn_tokens.sort(key=lambda v: v[1])
    cn_text = "".join(t for t, _, _ in cn_tokens)
    cn_text_rev = "".join(t for t, _, _ in reversed(cn_tokens))

    # operating_time
    opt = None
    if "工作日" in cn_text or "作日" in cn_text:
        opt = "工作日"
    elif "双休日" in cn_text or "休日" in cn_text:
        opt = "双休日"
    elif "平日" in cn_text:
        opt = "平日"

    # destination: prefer longest station name match
    def match_station(text):
        best = None
        if station_list:
            for st in station_list:
                if st and st in text:
                    if best is None or len(st) > len(best):
                        best = st
        return best

    dest = match_station(cn_text) or match_station(cn_text_rev)
    if dest is None:
        m = re.search(r"[开牙去][往住注]?(.+?)站?(?:方向|To)", cn_text)
        if m:
            dest = m.group(1).strip()
    if dest is None:
        m = re.search(r"([一-鿿]{2,6})站", cn_text)
        if m:
            dest = m.group(1)
    return dest, opt


def parse_line18(path, gap=0.022, station_list=None, debug=False):
    """Parse line 18: split image into left/right, extract each side's schedule."""
    pairs = convert_and_binarize_image(path)
    results = []
    for pi, (gray, binary) in enumerate(pairs):
        suffix = f"-{pi+1}" if len(pairs) > 1 else ""
        # --- schedule from split halves ---
        (Lg, Lb), (Rg, Rb) = _split_image_crop(gray, binary, 0.5)
        # Tall format (3820x2160): left hour col at left-half x~0.60, right half has
        # stray tokens at x<0.25 that block rowlead hour detection.
        tall = gray.size[0] >= 3000
        schedules = []
        for side_i, (sg, sb) in enumerate([(Lg, Lb), (Rg, Rb)]):
            if tall and side_i == 1:
                # Right half: drop stray tokens left of the hour column
                anns_g = ocrmac.OCR(sg, framework="livetext").recognize()
                anns_b = ocrmac.OCR(sb, framework="livetext").recognize()
                anns_g = [a for a in anns_g if a[2][0] >= 0.25]
                anns_b = [a for a in anns_b if a[2][0] >= 0.25]
            else:
                anns_g = ocrmac.OCR(sg, framework="livetext").recognize()
                anns_b = ocrmac.OCR(sb, framework="livetext").recognize()
            schedules.append(_extract_schedule_from_anns(anns_g, anns_b, gap=gap, hour_x_max=0.70))

        # --- metadata: deterministic destination for line 18 ---
        # Line 18 terminals are 马连洼 (west) and 天通苑东 (east).
        # Observed pattern: image -1 = direction toward 天通苑东, image -2 = toward 马连洼.
        stem = Path(path).stem
        parts = stem.split("-")
        station = parts[1] if len(parts) > 1 else None
        num = parts[-1] if parts else "1"
        if station == "马连洼":
            dest = "天通苑东"
        elif station == "天通苑东":
            dest = "马连洼"
        elif num == "2":
            dest = "马连洼"
        else:
            dest = "天通苑东"
        left_dest = right_dest = dest
        left_opt = "工作日"
        right_opt = "双休日"

        for side_name, dest, opt, times in [
            ("左", left_dest, left_opt, schedules[0]),
            ("右", right_dest, right_opt, schedules[1]),
        ]:
            if times is None:
                continue
            times = clean_1min_gaps(times)
            results.append({
                "filename": os.path.basename(path) + suffix,
                "route": parts[0],
                "station": parts[1] if len(parts) > 1 else None,
                "destination": dest,
                "operating_time": opt,
                "schedule_times": times,
                "_side": side_name,
            })
    return results


def clean_1min_gaps(times):
    """Remove spurious minutes in 1-minute gaps (OCR misreads).
    Metro intervals are >=2 min, so a 1-min gap is a duplicate/misread."""
    if len(times) < 3:
        return times
    mtimes = [int(t[:2]) * 60 + int(t[3:]) for t in times]
    result = list(mtimes)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            if result[i + 1] - result[i] == 1:
                prev = result[i - 1] if i > 0 else None
                nxt = result[i + 2] if i + 2 < len(result) else None
                if nxt is not None and nxt - result[i + 1] == 1:
                    del result[i + 1]  # run of 1-min gaps: drop the middle
                elif prev is not None and result[i] - prev == 1:
                    del result[i]
                elif nxt is not None and prev is not None:
                    ga = result[i] - prev
                    gb = nxt - result[i + 1]
                    if ga <= gb:
                        del result[i + 1]
                    else:
                        del result[i]
                elif prev is None:
                    del result[i + 1]
                else:
                    del result[i]
                changed = True
            else:
                i += 1
    return [f"{m // 60:02d}:{m % 60:02d}" for m in result]


def _eng_dest_fallback(anns_g, station_list=None):
    """Find English 'To XXX' header and map to Chinese station name."""
    rows = group_rows(anns_g)
    for y, tokens in rows:
        texts = "".join(tok[0] for tok in tokens if len(tok) >= 2)
        if "To" in texts or "to" in texts:
            for en, cn in EN_MAP.items():
                if en.lower() in texts.lower():
                    return cn
    return None


def parse_image(path, gap=0.022, station_list=None, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination, operating_time = extract_metadata(anns_g, station_list=station_list)
    if destination is None:
        destination = _eng_dest_fallback(anns_g, station_list)
    # Fuzzy-correct destination against station list (handles OCR misreads like 育部机场)
    if destination and station_list:
        from thefuzz import fuzz
        if destination not in station_list:
            best, best_score = destination, 0
            for st in station_list:
                sc = fuzz.ratio(destination, st)
                if sc > best_score:
                    best, best_score = st, sc
            if best_score >= 60:
                destination = best
    # 首都机场: infer destination from direction markers if still None
    if destination is None and station_list and "首都机场" in station_list:
        rows = group_rows(anns_g)
        for y, tokens in rows:
            line_text = "".join(tok[0] for tok in tokens if len(tok) >= 2)
            if "方向" in line_text or "To" in line_text or "to" in line_text:
                if "机场" in line_text:
                    destination = "首都机场"
                elif "北新桥" in line_text or "Beixinqiao" in line_text or "Beixinqiao".lower() in line_text.lower():
                    destination = "北新桥"
                if destination:
                    break
        # Terminal stations (2号/3号航站楼) have no direction line; service goes toward the city.
        if destination is None:
            stem = Path(path).stem
            parts = stem.split("-")
            station_name = parts[1] if len(parts) > 1 else ""
            if station_name in ("2号航站楼", "3号航站楼"):
                destination = "北新桥"
    # operating_time fallback: OCR often scrambles/reverses the label (e.g. 工作日 -> 日作,
    # Weekdays -> yadkeeW). Check both forward and reversed line text.
    if operating_time is None:
        rows = group_rows(anns_g)
        for y, tokens in rows:
            line_text = "".join(tok[0] for tok in tokens if len(tok) >= 2)
            rev = line_text[::-1]
            if any(k in line_text or k in rev for k in ["作日", "工作日", "Weekdays"]):
                operating_time = "工作日"
            elif any(k in line_text or k in rev for k in ["双休日", "休日", "Weekends"]):
                operating_time = "双休日"
            elif any(k in line_text or k in rev for k in ["平日", "Ordinary"]):
                operating_time = "平日"
            elif "周五" in line_text or "星期五" in line_text:
                operating_time = "星期五"
            if operating_time:
                break
    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    times = _extract_schedule_from_anns(anns_g, anns_b, gap=gap)
    if times is None:
        return None
    times = clean_1min_gaps(times)
    stem = Path(path).stem
    parts = stem.split("-")
    return {
        "filename": os.path.basename(path),
        "route": parts[0],
        "station": parts[1] if len(parts) > 1 else None,
        "destination": destination,
        "operating_time": operating_time,
        "schedule_times": times,
    }


def _worker(args):
    """Process a single image in a worker process (isolates OCR framework crashes)."""
    img_str, line, gap, station_list, debug = args
    try:
        if line == "18":
            recs = parse_line18(img_str, gap=gap, station_list=station_list, debug=debug)
            recs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in recs]
            return recs
        r = parse_image(img_str, gap=gap, station_list=station_list, debug=debug)
        return [r] if r else None
    except Exception as e:
        return [{"filename": os.path.basename(img_str), "error": str(e)}]


if __name__ == "__main__":
    import argparse
    from concurrent.futures import ProcessPoolExecutor, as_completed
    ap = argparse.ArgumentParser()
    ap.add_argument("-l", "--line", required=True)
    ap.add_argument("-g", "--gap", type=float, default=0.022)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-d", "--debug", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=1)
    ap.add_argument("--start", type=int, default=0, help="batch start index")
    ap.add_argument("--count", type=int, default=0, help="batch size (0=all)")
    a = ap.parse_args()

    # Glob both jpg and png
    images = sorted(Path("timetables").glob(f"{a.line}-*.jpg")) + \
             sorted(Path("timetables").glob(f"{a.line}-*.png"))
    images = sorted(images, key=lambda p: p.name)
    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])
    # 首都机场 destinations include "首都机场" (not a station in filenames) and "北新桥"
    if a.line == "首都机场":
        for extra in ["首都机场", "北新桥"]:
            if extra not in station_list:
                station_list.append(extra)

    # batch selection
    if a.count > 0:
        images = images[a.start:a.start + a.count]
    elif a.start > 0:
        images = images[a.start:]

    out = a.output or f"data/lines/{a.line}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = fail = 0
    tasks = [(str(img), a.line, a.gap, station_list, a.debug) for img in images]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool, open(out, "w", encoding="utf-8") as fo:
        futs = {pool.submit(_worker, t): os.path.basename(t[0]) for t in tasks}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                recs = fut.result()
            except Exception as e:
                print(f"CRASH {name}: {e}")
                fail += 1
                continue
            if not recs:
                print(f"FAIL {name}")
                fail += 1
                continue
            for r in recs:
                if "error" in r:
                    print(f"FAIL {name}: {r['error']}")
                    fail += 1
                    continue
                ok += 1
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                fo.flush()
    print(f"ok={ok} fail={fail} -> {out}")
