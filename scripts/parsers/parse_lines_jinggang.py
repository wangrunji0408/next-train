#!/usr/bin/env python3
"""
Dedicated parser for 京港地铁 (BJMTR) vertical timetable format.
Lines: 4, 14, 16, 17. Images ~1181x2362.

Key differences from generic scripts/parse_line_ocr.py:
- Minute OCR splits two-digit minutes into single chars -> pairwise/greedy merge
- Two-digit hours (10-23) split into two single chars -> value-based hour-token drop
- Footer "5 20 终点站" must be excluded from hour detection
- Destination header: line 14 uses "开往XX方向", lines 4/16/17 use bare station name
"""
import sys, os, json
from pathlib import Path
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')
from timetable_ocr import group_rows, merge_tokens, is_num, _substr_match
from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac

# English -> Chinese station fallback for destination (rarely used)
EN_MAP = {
    "Moshikou": "模式口", "Xinshougang": "新首钢", "Jinanqiao": "金安桥",
    "Beixinan": "北辛安", "Anheqiao": "安河桥北", "Tiangongyuan": "天宫院",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def row_has_non_digit(tokens, x_thresh=0.20):
    """True if the row contains a non-digit token at x > x_thresh.
    Used to exclude footer ('5 20 表示5点20分') and header rows."""
    for tok in tokens:
        text = tok[0]
        x = tok[2][0]
        if text.strip() and not is_num(text) and x > x_thresh:
            return True
    return False


def row_nums(tokens):
    """Extract [(text, x)] numeric tokens sorted by x. Skip non-digit rows optionally."""
    nums = []
    for tok in tokens:
        if len(tok) >= 2 and is_num(tok[0]):
            nums.append((tok[0], tok[2][0]))
    nums.sort(key=lambda v: v[1])
    return nums


def subseq_score(text, target):
    """Number of chars of target appearing in order within text."""
    score = 0
    it = iter(text)
    for c in target:
        if c in it:
            score += 1
    return score


def greedy_merge(tokens):
    """Order-based pairing: 2-char token = standalone; 1-char pairs with next."""
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        text, x = tokens[i]
        if len(text) == 2 and is_num(text):
            result.append((text, x))
            i += 1
        elif len(text) == 1 and i + 1 < n and len(tokens[i + 1][0]) == 1:
            result.append((text + tokens[i + 1][0], x))
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
            result.append((tokens[i][0] + tokens[i + 1][0], tokens[i][1]))
        if len(tokens) % 2 == 1:
            result.append(tokens[-1])
        return result
    return greedy_merge(tokens)


# ---------------------------------------------------------------------------
# hour column detection
# ---------------------------------------------------------------------------

def detect_hour_column(anns, ymin=0.055, ymax=0.90, hour_gap=0.030):
    """rowlead-style hour detection with footer exclusion.
    Returns ({hour: y}, hour_x) or (None, None)."""
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (ymin < y < ymax):
            continue
        # exclude rows containing text (footer '5 20 表示...' or header)
        if row_has_non_digit(tokens, x_thresh=0.15):
            continue
        nums = row_nums(tokens)
        if not nums:
            continue
        merged = merge_tokens(nums, hour_gap)
        text, x = merged[0]
        try:
            hv = int(text)
        except ValueError:
            continue
        if 5 <= hv <= 24 and 0.02 < x < 0.50:
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
            # keep the candidate with larger y (higher on screen = smaller y from bottom? No:
            # y is bottom-up, higher on screen = LARGER y). Hour rows: 5 at top (large y),
            # 23 at bottom (small y). For duplicate hour (footer), prefer larger y.
            if hv not in col or y > col[hv]:
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
    """nums: [(text,x)] sorted by x. Drop leading hour-column tokens.
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
    i = 0
    while i < len(nums) and nums[i][1] < 0.08:
        i += 1
    return i


# ---------------------------------------------------------------------------
# metadata (destination / operating_time)
# ---------------------------------------------------------------------------

def reconstruct_lines(anns):
    """Return list of (y, text) from grouped rows, all tokens joined by x order."""
    out = []
    for y, tokens in group_rows(anns):
        toks = [(t[0], t[2][0]) for t in tokens if t[0].strip()]
        toks.sort(key=lambda v: v[1])
        text = ''.join(t[0] for t in toks)
        if text:
            out.append((y, text))
    out.sort(key=lambda v: -v[0])
    return out


def find_operating_time(lines):
    keywords = [
        ("工作日", ["作日", "工作日", "Weekdays", "Weekday"]),
        ("双休日", ["双休日", "休日", "Weekends", "Weekend"]),
        ("平日", ["平日"]),
    ]
    for text in lines:
        for label, kws in keywords:
            if any(k in text for k in kws) or any(_substr_match(text, k) for k in kws):
                return label
    return None


def _lev(a, b):
    """Levenshtein edit distance (handles OCR char substitution/deletion)."""
    m, n = len(a), len(b)
    if m < n:
        a, b = b, a
        m, n = n, m
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
            prev = cur
    return dp[n]


def _best_lev(text, st_sorted, max_dist):
    """Find station minimizing edit distance to text. Returns (station, dist) or (None, big)."""
    import re
    best, best_d = None, 10 ** 9
    # only keep CJK chars for distance computation
    text_clean = re.sub(r'[^一-鿿]', '', text)
    for st in st_sorted:
        d = _lev(text_clean, st)
        if d < best_d:
            best_d = d
            best = st
    if best is not None and best_d <= max_dist:
        return best, best_d
    return None, best_d


def find_destination(lines, station_list, current_station):
    """lines: [(y, text)] header lines. Return destination station or None.

    Unified candidate scoring: gather (edit-distance, station) candidates from
    direction lines and bare CJK runs, then pick the globally lowest distance
    (preferring longer station names on ties, e.g. 未来科学城 vs 未来科学城北)."""
    import re
    st_sorted = [s for s in station_list if s and s != current_station]
    candidates = []  # (dist, -len, station)

    for y, text in lines:
        # direction line "往XXX方向" -> match against the extracted name only.
        # All destinations on these lines are >=3 CJK chars; a short (<3) OCR
        # fragment is unreliable and can cause false matches (e.g. "享庄"->方庄).
        m = re.search(r'[开牙去]?[往住注](.{2,8}?)方?向', text)
        if m:
            name = re.sub(r'[^一-鿿]', '', m.group(1))
            if len(name) >= 3 or any(_lev(name, st) == 0 for st in st_sorted):
                for st in st_sorted:
                    d = _lev(name, st)
                    candidates.append((d, -len(st), st))
                    s = subseq_score(name, st)
                    if s >= max(2, len(st) - 1):
                        candidates.append((len(st) - s, -len(st), st))
        # bare CJK runs (>=3 chars, edit-distance <=1 to a station). The current
        # station is excluded from st_sorted, so its own row won't match; a
        # destination like 未来科学城北 (1 edit from current 未来科学城) must match.
        for run in re.findall(r'[一-鿿]{3,8}', text):
            for st in st_sorted:
                d = _lev(run, st)
                if d <= 1:
                    candidates.append((d, -len(st), st))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    best_d, _, best_st = candidates[0]
    # confidence threshold: distance small enough
    if best_d <= max(2, len(best_st) - 1):
        return best_st
    return None


def extract_metadata(gray_anns, binary_anns, station_list, current_station,
                     binary_is_crop=False):
    g_lines = reconstruct_lines(gray_anns)
    b_lines = reconstruct_lines(binary_anns) if binary_anns is not None else []
    # header region only: y above the hour rows (hour 5 at ~0.85)
    g_head = [(y, t) for y, t in g_lines if y > 0.82]
    if binary_is_crop:
        b_head = b_lines  # crop only contains the header region
    else:
        b_head = [(y, t) for y, t in b_lines if y > 0.82]
    all_head = b_head + g_head
    op = find_operating_time([t for _, t in all_head])
    dest = find_destination(all_head, station_list, current_station)
    return dest, op


# ---------------------------------------------------------------------------
# main extraction
# ---------------------------------------------------------------------------

def clean_times(times):
    """Remove times within 1 minute of the previous kept time.
    Real metro schedules never have 1-min headways; such pairs are OCR artifacts."""
    result = []
    prev = None
    for t in times:
        h, m = map(int, t.split(':'))
        cur = h * 60 + m
        if prev is not None:
            diff = cur - prev
            if diff < 0:
                diff += 24 * 60
            if diff <= 1:
                continue
        result.append(t)
        prev = cur
    return result


def parse_image(path, gap=0.022, station_list=None, debug=False, gray_only=False):
    current_station = Path(path).stem.split("-")[1]
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    if gray_only:
        anns_b_meta = None
    else:
        # OCR just the header crop of the binary image (fast) for destination accuracy
        h = binary.size[1]
        crop = binary.crop((0, 0, binary.size[0], int(h * 0.24)))
        anns_b_meta = ocrmac.OCR(crop, framework="livetext").recognize()

    destination, operating_time = extract_metadata(
        anns_g, anns_b_meta, station_list or [], current_station,
        binary_is_crop=(anns_b_meta is not None))

    # minutes come from gray OCR (halves full-OCR load)
    anns_b = anns_g

    hour_map, hour_x = detect_hour_column(anns_g)
    if not hour_map:
        return None

    result = {h: [] for h in hour_map}
    for y, tokens in group_rows(anns_b):
        if not (0.055 < y < 0.90):
            continue
        if row_has_non_digit(tokens, x_thresh=0.15):
            continue
        nums = row_nums(tokens)
        if not nums:
            continue
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.028:
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
        mins = sorted(set(result[h]))
        if mins:
            for m in mins:
                times.append(f"{h:02d}:{m:02d}")
    times = clean_times(times)
    if not times:
        return None

    parts = Path(path).stem.split("-")
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
    ap.add_argument("-l", "--line", required=True)
    ap.add_argument("-g", "--gap", type=float, default=0.022)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-d", "--debug", action="store_true")
    ap.add_argument("--gray-only", action="store_true", help="use gray OCR for minutes too")
    ap.add_argument("--one", help="parse just one file (for testing)")
    a = ap.parse_args()

    timetables_dir = Path("timetables")
    if a.one:
        images = [Path(a.one)]
    else:
        images = sorted(timetables_dir.glob(f"{a.line}-*.jpg"))
    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])

    out = a.output or f"data/lines/{a.line}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = fail = 0
    fail_list = []
    with open(out, "w", encoding="utf-8") as fo:
        for img in images:
            try:
                r = parse_image(str(img), gap=a.gap, station_list=station_list, debug=a.debug,
                                gray_only=a.gray_only)
            except Exception as e:
                print(f"ERR {img.name}: {e}", flush=True)
                fail += 1
                fail_list.append(img.name)
                continue
            if r is None:
                fail += 1
                fail_list.append(img.name)
                print(f"FAIL {img.name}", flush=True)
                continue
            ok += 1
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            fo.flush()
            if ok % 10 == 0:
                print(f"  progress {ok}", flush=True)
            if a.debug:
                print(f"  {img.name}: dest={r['destination']} op={r['operating_time']} n={len(r['schedule_times'])}")
    print(f"line {a.line}: ok={ok} fail={fail}")
    if fail_list:
        print(f"failures: {fail_list}")
    print(f"-> {out}")
