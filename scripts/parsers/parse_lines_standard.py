#!/usr/bin/env python3
"""Dedicated OCR parser for Beijing Metro lines 1,2,5,7,9 (standard horizontal format).

Method:
- Gray OCR: detect hour anchors (rowlead with small gap) + interpolate missing hours.
- Binary OCR: extract minute tokens per row, greedy pair into 2-digit minutes.
- Destination: English "To XXX" mapping + Chinese regex fallback.
"""
import json, os, re, sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))  # project scripts/ dir
from parse_timetables import convert_and_binarize_image, replace_circle_number
from timetable_ocr import group_rows, is_num, merge_tokens
from ocrmac import ocrmac

# ---------------------------------------------------------------------------
# Destination mapping (English "To" name -> Chinese)
# ---------------------------------------------------------------------------
EN_DEST = {
    # Line 1 / through 八通
    "UniversalResort": "环球度假区",
    "Universal": "环球度假区",
    "Pingguoyuan": "苹果园",
    "Gucheng": "古城",
    "Sihui": "四惠",
    "SihuiEast": "四惠东",
    "Tuqiao": "土桥",
    "Guoyuan": "果园",
    # Line 5
    "Songjiazhuang": "宋家庄",
    "TiantongyuanBei(N)": "天通苑北",
    "TiantongyuanBei": "天通苑北",
    "TiantongyuanNorth": "天通苑北",
    # Line 7
    "BeijingWestRailwayStation": "北京西站",
    "BeijingWest": "北京西站",
    # Line 9
    "NationalLibrary": "国家图书馆",
    "Guogongzhuang": "郭公庄",
    # Line 2 loop
    "Xizhimen": "西直门",
    "Chegongzhuang": "车公庄",
    "Fuchengmen": "阜成门",
    "Fuxingmen": "复兴门",
    "Changchunjie": "长椿街",
    "Xuanwumen": "宣武门",
    "Hepingmen": "和平门",
    "Qianmen": "前门",
    "Chongwenmen": "崇文门",
    "BeijingStation": "北京站",
    "BeijingRailwayStation": "北京站",
    "Jianguomen": "建国门",
    "Chaoyangmen": "朝阳门",
    "DongsiShitiao": "东四十条",
    "Dongsi": "东四十条",
    "Dongzhimen": "东直门",
    "YonghegongLamaTemple": "雍和宫",
    "Yonghegong": "雍和宫",
    "Andingmen": "安定门",
    "GulouDajie": "鼓楼大街",
    "Jishuitan": "积水潭",
    # extra
    "National": "国家图书馆",
    "Beijing": "北京西站",
}

# normalize English names: strip spaces, lowercase, drop punctuation
def _norm_en(s):
    return re.sub(r'[\s\-\.\']', '', s).lower()

def map_en_dest(en, route=None):
    """Map English name -> Chinese destination. Returns (dest, source) or (None, src)."""
    key = _norm_en(en)
    # line-scoped candidate list
    per_line = {
        "1": ["UniversalResort", "Pingguoyuan", "Gucheng", "Sihui", "SihuiEast", "Tuqiao", "Guoyuan"],
        "2": ["Xizhimen", "Chegongzhuang", "Fuchengmen", "Fuxingmen", "Changchunjie", "Xuanwumen",
              "Hepingmen", "Qianmen", "Chongwenmen", "BeijingStation", "Jianguomen", "Chaoyangmen",
              "DongsiShitiao", "Dongzhimen", "YonghegongLamaTemple", "Andingmen", "GulouDajie", "Jishuitan"],
        "5": ["Songjiazhuang", "TiantongyuanBei(N)"],
        "7": ["BeijingWestRailwayStation", "UniversalResort"],
        "9": ["NationalLibrary", "Guogongzhuang"],
    }
    cands = per_line.get(route) or list(EN_DEST.keys())
    for k in cands:
        if _norm_en(k) == key:
            return EN_DEST[k], "en"
    # containment
    for k in cands:
        nk = _norm_en(k)
        if len(nk) >= 5 and (nk in key or key in nk):
            return EN_DEST[k], "en_contain"
    # fuzzy via thefuzz
    try:
        from thefuzz import fuzz
        best_k, best_s = None, 0
        for k in cands:
            nk = _norm_en(k)
            r = fuzz.ratio(key, nk)
            pr = fuzz.partial_ratio(key, nk)
            s = max(r, pr)
            if s > best_s:
                best_s, best_k = s, k
        if best_k and best_s >= 55:
            return EN_DEST[best_k], "en_fuzzy"
    except ImportError:
        pass
    return None, "en_unmapped"

# Chinese fallback: regex on x-sorted line text
def extract_dest_chinese(line_text):
    """Extract destination from Chinese direction line, tolerant of OCR char subs."""
    for end_marker in ["方向", "开向"]:
        idx = line_text.find(end_marker)
        if idx < 0:
            continue
        prefix = line_text[:idx]
        prefix = re.sub(r'[往住注开牙去]', '', prefix)
        m = re.search(r'[一-鿿]{2,12}$', prefix)
        if m:
            dest = re.sub(r'站$', '', m.group(0))
            if dest:
                return dest
    # try "开往...方向" where 往 misread
    return None

def extract_destination_from_line(line_text, route=None):
    """Return (destination, source) or (None, None)."""
    # English To name: capture all consecutive English letters/spaces/dots/hyphens after "To".
    m = re.search(r'To\s*([A-Za-z][A-Za-z\s\.\-\(\)]{1,40}?)(?:[^A-Za-z\s\.\-\(\)]|$)', line_text)
    if not m:
        m = re.search(r'To\s*([A-Za-z][A-Za-z\s\.\-\(\)]{1,40})', line_text)
    if m:
        en = m.group(1).strip()
        d, src = map_en_dest(en, route)
        if d:
            return d, src
        return None, src
    # Chinese fallback
    d = extract_dest_chinese(line_text)
    if d:
        return d, "zh"
    return None, None

# ---------------------------------------------------------------------------
# Hour detection
# ---------------------------------------------------------------------------
def detect_hour_anchors(anns, hour_gap=0.015, x_col=(0.08, 0.18), hmin=4, hmax=24):
    """Return {hour: y} from gray OCR rowlead with small gap.
    Skips rows containing non-numeric tokens (headers/footers) to avoid false anchors."""
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (0.08 < y < 0.94):
            continue
        # Skip rows with any non-numeric text token (footer "表示...", header text, etc.)
        text_tokens = [tok[0] for tok in tokens if len(tok) >= 2 and tok[0].strip()]
        if not text_tokens:
            continue
        if not all(is_num(t) for t in text_tokens):
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2:
                t = replace_circle_number(tok[0])
                if is_num(t):
                    nums.append((t, tok[2][0]))
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        merged = merge_tokens(nums, hour_gap)
        text, x = merged[0]
        try:
            hv = int(text)
        except ValueError:
            continue
        if hmin <= hv <= hmax and x_col[0] < x < x_col[1]:
            candidates.append((y, hv, x))
    if len(candidates) < 3:
        return {}, None
    xs = sorted(set(round(c[2], 2) for c in candidates))
    best, bestcnt = None, 0
    for cx in xs:
        cnt = sum(1 for _, _, x in candidates if abs(x - cx) < 0.013)
        if cnt > bestcnt:
            bestcnt = cnt
            best = cx
    col = {}
    for y, hv, x in candidates:
        if best is not None and abs(x - best) < 0.013:
            col[hv] = y
    return col, best

def build_hour_map(anchors, hmin=5, hmax=23):
    """Interpolate anchors to {hour: y} for hmin..hmax. Returns dict or None."""
    a = {}
    for h in sorted(anchors):
        if hmin <= h <= hmax:
            a[h] = anchors[h]
    # If we have hour 4 anchor and no 5, keep 4 to anchor top extrapolation
    if 4 in anchors and 5 not in a:
        a[5] = anchors[4]
    if len(a) < 3:
        return None
    result = dict(a)
    hours = sorted(a)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i + 1]
        if h2 - h1 > 1:
            y1, y2 = a[h1], a[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result


def assign_hours_rowbased(anns):
    """Robust hour assignment via row-index.
    Returns (hour_map {hour: y}, ok_bool).
    Schedule rows are all-numeric rows in the schedule band. Hours are assigned by
    searching the best starting hour (4-7) that matches visible hour anchors.
    Handles images where OCR misses most hour digits."""
    rows = group_rows(anns)
    # 1. Identify schedule rows (all-numeric, >=2 digit tokens, in band)
    sched = []  # (y, [digit tokens])
    for y, tokens in rows:
        if not (0.17 < y < 0.94):
            continue
        text_tokens = [tok[0] for tok in tokens if len(tok) >= 2 and tok[0].strip()]
        if not text_tokens:
            continue
        if not all(is_num(replace_circle_number(t)) for t in text_tokens):
            continue  # header/footer
        digits = []
        for tok in tokens:
            if len(tok) >= 2:
                t = replace_circle_number(tok[0])
                if is_num(t):
                    digits.append((t, tok[2][0]))
        if len(digits) >= 2:
            digits.sort(key=lambda v: v[1])
            sched.append((y, digits))
    if len(sched) < 8:
        return None, False
    sched.sort(key=lambda r: -r[0])  # top first

    # 2. Estimate hour column center from the leftmost digit x of each row
    left_xs = [r[1][0][1] for r in sched]
    center = float(sorted(left_xs)[len(left_xs) // 2])

    # 3. Parse hour anchors per row: leading tokens at x < center + 0.02
    row_anchors = {}  # row_index -> hour
    for i, (y, digits) in enumerate(sched):
        # collect leading tokens within hour column
        lead = []
        for text, x in digits:
            if x < center + 0.022:
                lead.append((text, x))
            else:
                break
        if not lead:
            continue
        # try to form hour from leading tokens
        hv = None
        if len(lead) >= 1:
            try:
                v1 = int(lead[0][0])
                if len(lead[0][0]) == 1 and len(lead) >= 2 and len(lead[1][0]) == 1 \
                        and (lead[1][1] - lead[0][1]) < 0.018:
                    hv = int(lead[0][0] + lead[1][0])
                else:
                    hv = v1
            except ValueError:
                hv = None
        if hv is not None and 4 <= hv <= 24:
            row_anchors[i] = hv

    # 4. Search best starting hour
    R = len(sched)
    best_start, best_score = None, -1
    for start in range(4, 8):
        score = 0
        for idx, h in row_anchors.items():
            assigned = start + idx
            if h == assigned:
                score += 1
            elif abs(h - assigned) <= 1:
                score += 0.5
        if score > best_score:
            best_score, best_start = score, start
    if best_start is None or best_score <= 0:
        # fall back to interpolation from anchors
        return None, False

    # 5. Build hour -> y map
    hour_map = {}
    for i, (y, _) in enumerate(sched):
        h = best_start + i
        hour_map[h] = y
    return hour_map, True

# ---------------------------------------------------------------------------
# Minute extraction (greedy pairing)
# ---------------------------------------------------------------------------
def clean_digits(tokens):
    """tokens: [(text, x)]. Convert circled nums, keep digits, return [(digits_str, x)]."""
    out = []
    for text, x in tokens:
        t = replace_circle_number(text)
        digits = ''.join(c for c in t if c.isdigit())
        if not digits:
            continue
        out.append((digits, x))
    return out

def greedy_minutes(cleaned):
    """Greedy pair into minutes. cleaned: [(digits, x)] sorted by x."""
    minutes = []
    i = 0
    n = len(cleaned)
    while i < n:
        text, _ = cleaned[i]
        if len(text) >= 4 and len(text) % 2 == 0:
            # possibly merged multiple minutes e.g. "1618"
            pairs = [int(text[j:j+2]) for j in range(0, len(text), 2)]
            if all(0 <= p <= 59 for p in pairs):
                minutes.extend(pairs)
                i += 1
                continue
        if len(text) >= 2:
            m = int(text[:2])
            if 0 <= m <= 59:
                minutes.append(m)
            i += 1
            continue
        # single char -> pair with next
        if i + 1 < n:
            text2, _ = cleaned[i + 1]
            combined = text + text2
            if len(combined) == 2:
                m = int(combined)
                if 0 <= m <= 59:
                    minutes.append(m)
                i += 2
                continue
            # else skip
        i += 1
    return minutes

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def extract_metadata_robust(anns_g, route=None):
    """Return (destination, operating_time)."""
    rows = group_rows(anns_g)
    destination, operating_time = None, None
    for y, tokens in rows:
        tokens_sorted = sorted(tokens, key=lambda a: a[2][0])
        line_text = "".join(t[0] for t in tokens_sorted if len(t) >= 2)
        if not line_text:
            continue
        if operating_time is None:
            # Prioritize Chinese keywords over English (source images can have
            # conflicting text, e.g. "双休日 Weekdays").
            if _substr(line_text, "双休日") or "双休日" in line_text:
                operating_time = "双休日"
            elif _substr(line_text, "工作日") or "工作日" in line_text or "作日" in line_text:
                operating_time = "工作日"
            elif "平日" in line_text or _substr(line_text, "平日") or "Ordinary" in line_text:
                operating_time = "平日"
            elif "周五" in line_text or _substr(line_text, "周五") or "Friday" in line_text:
                operating_time = "星期五"
            elif any(k in line_text for k in ["Weekdays"]):
                operating_time = "工作日"
            elif any(k in line_text for k in ["Weekends"]):
                operating_time = "双休日"
        if destination is None:
            is_dir = any(k in line_text for k in ["方向", "开向", "To", "开往", "往", "去往"])
            if is_dir:
                d, src = extract_destination_from_line(line_text, route)
                if d:
                    destination = d
                    continue
    return destination, operating_time

def _substr(text, target):
    it = iter(text)
    return all(c in it for c in target)

# ---------------------------------------------------------------------------
# Full parse
# ---------------------------------------------------------------------------
def ocr_retry(img):
    """Run OCR, retrying on empty annotations (Vision service is flaky)."""
    import time
    for attempt in range(4):
        anns = ocrmac.OCR(img, framework="livetext").recognize()
        if anns:
            return anns
        time.sleep(1.0 * (attempt + 1))
    return anns

def parse_image(path, debug=False, minute_img="gray"):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocr_retry(gray)
    # Detect "首末班车" summary cards: they stack two mini-timetables (工作日 + 双休日)
    # in one image, so there are two direction lines ("方向"). Full timetables have one.
    n_dir = 0
    for _y, _toks in group_rows(anns_g):
        if "方向" in "".join(t[0] for t in _toks if len(t) >= 2):
            n_dir += 1
    if n_dir >= 2:
        return None, {"error": "summary_card"}
    stem = Path(path).stem
    parts = stem.split("-")
    route = parts[0]
    station = parts[1] if len(parts) > 1 else None
    destination, operating_time = extract_metadata_robust(anns_g, route=route)

    anchors, hour_col_center = detect_hour_anchors(anns_g)
    hour_map = build_hour_map(anchors)
    method = "interp"
    if not hour_map or len(hour_map) < 12:
        hour_map, ok = assign_hours_rowbased(anns_g)
        method = "rowbased" if ok else "interp"
        if not hour_map:
            return None, {"error": "hour map failed", "anchors": anchors, "method": method}
    # recompute center from row-based if used
    if method == "rowbased" and hour_col_center is None:
        hour_col_center = 0.11
    hour_boundary = (hour_col_center if hour_col_center is not None else 0.11) + 0.018

    img_min = gray if minute_img == "gray" else binary
    anns_b = ocr_retry(img_min)
    result = {h: [] for h in hour_map}
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if y < 0.17 or y > 0.94:
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2:
                t = replace_circle_number(tok[0])
                if is_num(t):
                    nums.append((t, tok[2][0]))
        if len(nums) < 2:
            continue
        nums.sort(key=lambda v: v[1])
        # find nearest hour by y
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.020:
            continue
        # strip hour-column tokens (x near hour col). We determine hour column x
        # from the anchor clustering? Instead use: tokens with x < first-minute-x.
        # Determine hour boundary: if the leading token(s) combine to best_h.
        # Simple approach: drop leading tokens whose combined value equals best_h.
        cleaned = clean_digits(nums)
        # Strip leading hour-column tokens: anything with x < hour_boundary is the hour.
        # This also correctly handles rows where the hour digit was NOT recognized
        # (first token is a minute, at x > hour_boundary -> kept).
        consumed = 0
        for text, x in cleaned:
            if x < hour_boundary:
                consumed += 1
            else:
                break
        minutes_tokens = cleaned[consumed:]
        if not minutes_tokens:
            continue
        minutes = greedy_minutes(minutes_tokens)
        if debug:
            print(f"  h={best_h} y={y:.3f} raw={[(t, round(x,3)) for t,x in minutes_tokens]} -> {minutes}")
        result[best_h].extend(minutes)

    times = []
    for h in sorted(result):
        for m in sorted(set(result[h])):
            times.append(f"{h:02d}:{m:02d}")
    # Post-process: remove times that create <=1-min gap with a neighbor (always OCR noise).
    # Work in minutes-from-midnight.
    def to_min(t):
        hh, mm = map(int, t.split(":"))
        return hh * 60 + mm
    mt = [to_min(t) for t in times]
    cleaned = []
    for m in mt:
        if cleaned and m - cleaned[-1] <= 1:
            # keep the earlier one, skip this (or if this is surrounded by a gap, prefer keeping structure)
            continue
        cleaned.append(m)
    times = [f"{m // 60:02d}:{m % 60:02d}" for m in cleaned]
    if not times:
        return None, {"error": "no times", "hour_map": {h: round(y,3) for h,y in hour_map.items()}}

    stem = Path(path).stem
    parts = stem.split("-")
    route = parts[0]
    station = parts[1] if len(parts) > 1 else None

    record = {
        "filename": os.path.basename(path),
        "route": route,
        "station": station,
        "destination": destination,
        "operating_time": operating_time,
        "schedule_times": times,
    }
    return record, {"hour_map": {h: round(y,3) for h,y in hour_map.items()}, "anchors": anchors}

if __name__ == "__main__":
    for f in sys.argv[1:]:
        print("=" * 60)
        print(os.path.basename(f))
        rec, info = parse_image(f, debug=True)
        if rec is None:
            print("  FAILED:", info)
            continue
        print(f"  dest={rec['destination']} op={rec['operating_time']} n={len(rec['schedule_times'])}")
        # print hours coverage
        hours = {}
        for t in rec["schedule_times"]:
            h, m = t.split(":")
            hours.setdefault(int(h), []).append(int(m))
        for h in sorted(hours):
            print(f"  {h:02d}: {hours[h]}")
