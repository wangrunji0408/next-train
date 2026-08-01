import sys, os, json
from pathlib import Path
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')
from timetable_ocr import (group_rows, merge_tokens,
                           extract_metadata, is_num, extract_destination_candidate)
from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac

# English -> Chinese station mapping (for "To Moshikou" style headers)
EN_MAP = {
    "Moshikou": "模式口", "Xinshougang": "新首钢", "Jinanqiao": "金安桥",
    "Beixinan": "北辛安", "Sishui": "四惠", "Sihuidong": "四惠东",
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
        # pairwise for all-single-char (safe with OCR reordering)
        result = []
        for i in range(0, len(tokens) - 1, 2):
            result.append((tokens[i][0] + tokens[i+1][0], tokens[i][1]))
        if len(tokens) % 2 == 1:
            result.append(tokens[-1])
        return result
    return greedy_merge(tokens)


def detect_hour_column_loose(anns, ymin=0.055, hour_gap=0.030, x_min=0.02, x_max=0.50):
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
    # fallback: x-threshold based drop
    i = 0
    while i < len(nums) and nums[i][1] < 0.132:
        i += 1
    return i


def extract_schedule_custom(path, gap=0.022, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    hour_map, hour_x = detect_hour_column_loose(anns_g)
    if not hour_map:
        return None, None
    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    result = {h: [] for h in hour_map}
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (0.06 < y < 0.90):
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
        drop = drop_hour_tokens(nums, best_h)
        merged = merge_minutes(nums[drop:], gap)
        for text, x in merged:
            try:
                m = int(text)
                if 0 <= m <= 59:
                    result[best_h].append(m)
            except ValueError:
                pass
    final = {}
    for h, mins in result.items():
        mins = sorted(set(mins))
        if mins:
            final[h] = mins
    return final, (anns_g, hour_map)


def parse_image(path, gap=0.022, station_list=None, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination, operating_time = extract_metadata(anns_g, station_list=station_list)
    # English fallback for destination
    if destination is None:
        rows = group_rows(anns_g)
        for y, tokens in rows:
            texts = "".join(tok[0] for tok in tokens if len(tok) >= 2)
            if "To" in texts or "to" in texts:
                for en, cn in EN_MAP.items():
                    if en.lower() in texts.lower():
                        destination = cn
                        break
            if destination:
                break
    hour_map, hour_x = detect_hour_column_loose(anns_g)
    if not hour_map:
        return None
    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    result = {h: [] for h in hour_map}
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (0.06 < y < 0.90):
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
    if not times:
        return None
    stem = Path(path).stem
    parts = stem.split("-")
    return {
        "filename": os.path.basename(path),
        "route": parts[0],
        "station": parts[1],
        "destination": destination,
        "operating_time": operating_time,
        "schedule_times": times,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-l", "--line", default="11")
    ap.add_argument("-g", "--gap", type=float, default=0.022)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-d", "--debug", action="store_true")
    a = ap.parse_args()
    timetables_dir = Path("timetables")
    images = sorted(timetables_dir.glob(f"{a.line}-*.jpg"))
    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])
    out = a.output or f"data/lines/{a.line}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = fail = 0
    with open(out, "w", encoding="utf-8") as fo:
        for img in images:
            r = parse_image(str(img), gap=a.gap, station_list=station_list, debug=a.debug)
            if r is None:
                fail += 1
                print(f"FAIL {img.name}")
                continue
            ok += 1
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            if a.debug:
                print(f"  {img.name}: dest={r['destination']} op={r['operating_time']} n={len(r['schedule_times'])}")
    print(f"ok={ok} fail={fail} -> {out}")
