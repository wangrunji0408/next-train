#!/usr/bin/env python3
"""Dedicated OCR parser for Beijing Metro lines 19, S1, 大兴机场, 房山, 昌平, 燕房, 首都机场.

Reuses parse_beijing's robust schedule extraction (hour anchor detection + interpolation,
greedy minute pairing, ≤1min noise removal) and replaces metadata extraction with a
per-line station-list-based matcher that handles Chinese direction lines ("开往XX方向")
with OCR-tolerant fuzzy matching, plus English "To XXX" fallback.

Special cases:
- 首都机场: headerless images (cropped grids) get destination/operating_time inferred
  by schedule-similarity matching against header images of the same station.
- 首都机场 operating time "周一至周四，双休日" maps to "平日" (app convention).
"""
import json, os, re, sys, time
from pathlib import Path
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from preprocess import convert_and_binarize_image, replace_circle_number
from vision_ocr import group_rows, is_num, merge_tokens
from ocrmac import ocrmac

# ---------------------------------------------------------------------------
# Per-line station lists (from timetable filenames)
# ---------------------------------------------------------------------------
STATIONS = {
    "19": ["牡丹园", "北太平庄", "积水潭", "平安里", "太平桥", "牛街", "景风门", "草桥", "新发地", "新宫"],
    "S1": ["苹果园", "金安桥", "桥户营", "四道桥", "栗园庄", "上岸", "小园", "石厂"],
    "大兴机场": ["草桥", "大兴新城", "大兴机场"],
    "房山": ["东管头南", "首经贸", "花乡东桥", "白盆窑", "郭公庄", "大葆台", "稻田", "长阳",
             "篱笆房", "广阳城", "良乡大学城北", "良乡大学城", "良乡大学城西", "良乡南关", "苏庄", "阎村东"],
    "昌平": ["蓟门桥", "西土城", "学院桥", "六道口", "学知园", "清河小营桥", "清河", "清河站",
             "朱房北", "朱辛庄", "生命科学园", "西二旗", "巩华城", "沙河", "沙河高教园", "南邵",
             "北邵洼", "昌平东关", "昌平", "十三陵景区", "昌平西山口"],
    "燕房": ["燕山", "房山城关", "饶乐府", "马各庄", "大石河东", "星城", "阎村", "紫草坞", "阎村东"],
    "首都机场": ["北新桥", "东直门", "三元桥", "2号航站楼", "3号航站楼"],
}

# English -> Chinese destination for "To XXX" fallback (fuzzy-matched by prefix/containment)
EN_DEST = {
    "pingguoyuan": "苹果园", "jinanqiao": "金安桥", "qiaohuying": "桥户营",
    "sishidaoqiao": "四道桥", "liyuanzhuang": "栗园庄", "shangai": "上岸",
    "shang'an": "上岸", "shangan": "上岸", "xiaoyuan": "小园", "shichang": "石厂",
    "dongguantounan": "东管头南", "shoujingmao": "首经贸", "huaxiangdongqiao": "花乡东桥",
    "baipenyao": "白盆窑", "guogongzhuang": "郭公庄", "dabaotai": "大葆台",
    "daotian": "稻田", "changyang": "长阳", "libafang": "篱笆房",
    "guangyangcheng": "广阳城", "liangxiangdaxuechengbei": "良乡大学城北",
    "liangxiangdaxuecheng": "良乡大学城", "liangxiangnanguan": "良乡南关",
    "suzhuang": "苏庄", "yancundong": "阎村东", "yancun": "阎村东",
    "jimenqiao": "蓟门桥", "xitu cheng": "西土城", "xitu": "西土城", "xueyuanqiao": "学院桥",
    "liudaokou": "六道口", "xuezhiyuan": "学知园", "qinghexiaoyingqiao": "清河小营桥",
    "qinghe": "清河", "qinghezhan": "清河站", "zhufangbei": "朱房北",
    "zhuxinzhuang": "朱辛庄", "shengmingkexueyuan": "生命科学园", "xierqi": "西二旗",
    "gonghuacheng": "巩华城", "shahe": "沙河", "shahegaojiaoyuan": "沙河高教园",
    "nanshao": "南邵", "beishaowa": "北邵洼", "changpingdongguan": "昌平东关",
    "changping": "昌平", "shisanlingjingqu": "十三陵景区", "changpingxishankou": "昌平西山口",
    "yanshan": "燕山", "fangshanchengguan": "房山城关", "raolefu": "饶乐府",
    "magezhuang": "马各庄", "dashihedong": "大石河东", "xingcheng": "星城",
    "yancun": "阎村", "zicaowu": "紫草坞", "dashanhe": "大石河东",
    "beixinqiao": "北新桥", "dongzhimen": "东直门", "sanyuanqiao": "三元桥",
    "daxingjichang": "大兴机场", "daxing": "大兴机场", "caoqiao": "草桥",
    "capitalairport": "首都机场", "capital": "首都机场", "airport": "首都机场",
    "beijingsouth": "北京南站",
    # 19线
    "mudanyuan": "牡丹园", "beitaipingzhuang": "北太平庄", "jishuitan": "积水潭",
    "pinganli": "平安里", "taipingqiao": "太平桥", "niujie": "牛街",
    "jingfengmen": "景风门", "xinfadi": "新发地", "xingong": "新宫",
}


def _norm(s):
    return re.sub(r'[\s\-\.\'\(\)]', '', s).lower()


def map_en(en, route=None):
    key = _norm(en)
    if not key:
        return None
    if key in EN_DEST:
        return EN_DEST[key]
    # containment: OCR may add/join words ("DaxingJichang" etc.)
    for k, v in EN_DEST.items():
        if len(k) >= 4 and (k in key or key in k):
            return v
    # fuzzy
    try:
        from thefuzz import fuzz
        best_k, best_s = None, 0
        for k, v in EN_DEST.items():
            s = max(fuzz.ratio(key, k), fuzz.partial_ratio(key, k))
            if s > best_s:
                best_s, best_k = s, k
        if best_k and best_s >= 60:
            return EN_DEST[best_k]
    except ImportError:
        pass
    return None


def _lev(a, b):
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


def _subseq_score(text, target):
    """Number of target chars appearing in order within text (OCR-sub tolerant)."""
    score = 0
    it = iter(text)
    for c in target:
        if c in it:
            score += 1
    return score


def fuzzy_match_station(name, station_list, current_station=None):
    """Match an OCR name to the closest station (edit distance + subsequence).
    Ties broken by preferring the longer station name (e.g. 阎村东 vs 阎村)."""
    if not name:
        return None
    cands = [s for s in station_list if s and s != current_station]
    best, best_key = None, None
    for st in cands:
        d = _lev(name, st)
        sub = _subseq_score(name, st)
        score = d
        if sub >= max(2, len(st) - 1):
            score = max(0, score - 2)
        if len(name) >= 2 and name in st:   # name is a strict substring of station
            score = 0
        key = (score, -len(st), -sub)
        if best_key is None or key < best_key:
            best_key, best = key, st
    if best is not None and (best_key[0] <= max(1, len(best) - 1)):
        return best
    return None


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def header_lines(anns):
    """Return list of (y, text) sorted top-first (large y first)."""
    rows = group_rows(anns)
    out = []
    for y, tokens in rows:
        toks = [(t[0], t[2][0]) for t in tokens if t[0].strip()]
        toks.sort(key=lambda v: v[1])
        text = ''.join(t[0] for t in toks)
        if text:
            out.append((y, text))
    out.sort(key=lambda v: -v[0])
    return out


def _subseq(text, target):
    it = iter(text)
    return all(c in it for c in target)


def extract_operating_time(lines, route=None):
    """Return operating_time string or None. Chinese keywords prioritized
    (OCR-garbled text handled by subsequence matching)."""
    all_text = "".join(t for _, t in lines)
    # 首都机场 special: "周一至周四，双休日" => 平日
    if _subseq(all_text, "周一") and (_subseq(all_text, "周四") or _subseq(all_text, "周五")) \
            and _subseq(all_text, "双休日"):
        return "平日"
    for y, text in lines:
        if "双休日" in text or "休日" in text:
            return "双休日"
        if "工作日" in text or "作日" in text or "Workdays" in text or "Weekday" in text:
            return "工作日"
        if "平日" in text or "Ordinary" in text:
            return "平日"
        if "星期五" in text or "周五" in text or "Friday" in text:
            return "星期五"
    # subsequence fallback (OCR char-garbled)
    if _subseq(all_text, "双休日") or _subseq(all_text, "休日") or _subseq(all_text, "Weekends"):
        return "双休日"
    if _subseq(all_text, "工作日") or _subseq(all_text, "作日"):
        return "工作日"
    if _subseq(all_text, "平日") or "Ordinary" in all_text:
        return "平日"
    if _subseq(all_text, "周五") or "Friday" in all_text:
        return "星期五"
    return None


def extract_destination(lines, station_list, current_station, route=None):
    """Return destination or None. Chinese direction line first, then English To."""
    for y, text in lines:
        if not any(k in text for k in ["方向", "开向", "开往", "去往", "往"]) and \
                not re.search(r'\b[Tt][oO]\b', text):
            continue
        # --- Chinese: capture name after 开往/去往/往, terminated by 站+boundary ---
        m = re.search(
            r'(?:开往|去往|前往|[往住注])([一-鿿]{2,12}?)(?:站)?'
            r'(?=[^一-鿿]|方向|开向|向|$)',
            text)
        if m:
            name = re.sub(r'[^一-鿿]', '', m.group(1))
            if name:
                # fuzzy-clean against station list
                fm = fuzzy_match_station(name, station_list, current_station)
                if fm:
                    return fm
                # for 首都机场 aggregate "首都机场" not in station list -> keep raw
                if route == "首都机场" and ("首都机场" in text or "机场" in name):
                    return "首都机场"
                # if name is long/clean, keep it
                if len(name) >= 2:
                    return name
        # --- English To (word-boundary to avoid matching "to" inside words) ---
        m = re.search(r'\b[Tt][oO]\s*([A-Za-z][A-Za-z\s\.\-\(\)]{1,40}?)(?:[^A-Za-z\s\.\-\(\)]|$)', text)
        if m:
            en = m.group(1).strip()
            d = map_en(en, route)
            if d:
                return d
    # 首都机场: airport-side stations always depart toward the city.
    if route == "首都机场":
        if current_station in ("2号航站楼", "3号航站楼"):
            return "北新桥"
        # city-side stations: leave None so schedule-similarity inference fills it
        # (a city station can depart toward 首都机场 or toward another city station).
    return None


def extract_metadata(anns, station_list, current_station, route=None):
    lines = header_lines(anns)
    op = extract_operating_time(lines, route=route)
    dest = extract_destination(lines, station_list, current_station, route=route)
    return dest, op


# ---------------------------------------------------------------------------
# Schedule extraction (from parse_beijing)
# ---------------------------------------------------------------------------
def ocr_retry(img):
    for attempt in range(4):
        anns = ocrmac.OCR(img, framework="livetext").recognize()
        if anns:
            return anns
        time.sleep(1.0 * (attempt + 1))
    return anns


def detect_hour_anchors(anns, hour_gap=0.015, x_col=(0.08, 0.18), hmin=4, hmax=24):
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (0.08 < y < 0.94):
            continue
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


def fit_robust(pts):
    """Robust linear fit y = a + b*hour (Theil-Sen median of slopes).
    pts: [(y, hour)]. Returns (a, b) or (None, None)."""
    pts = list(set((round(y, 4), h) for y, h in pts))
    if len(pts) < 4:
        return None, None
    slopes = []
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            y1, h1 = pts[i]
            y2, h2 = pts[j]
            if h2 != h1:
                slopes.append((y2 - y1) / (h2 - h1))
    if not slopes:
        return None, None
    slopes.sort()
    b = slopes[len(slopes) // 2]
    if abs(b) < 0.005 or abs(b) > 0.10:
        return None, None
    ints = sorted(y - b * h for y, h in pts)
    a = ints[len(ints) // 2]
    # refine: keep points near the line and refit (least squares)
    spacing = abs(b)
    keep = [(y, h) for y, h in pts if abs(y - (a + b * h)) < 2.5 * spacing]
    if len(keep) >= 4:
        xs = [p[1] for p in keep]
        ys = [p[0] for p in keep]
        n2 = len(xs)
        sx = sum(xs)
        sy = sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n2 * sxx - sx * sx
        if denom != 0:
            b2 = (n2 * sxy - sx * sy) / denom
            a2 = (sy - b2 * sx) / n2
            if abs(b2) > 0.005 and abs(b2) < 0.10:
                a, b = a2, b2
    return a, b


def fit_hour_model(anns, hour_gap=0.015, x_col=(0.05, 0.30), hmin=5, hmax=24):
    """Detect hour row positions via a robust linear model y = a + b*hour.
    Returns (a, b) or None. Resistant to OCR misread hour VALUES."""
    rows = group_rows(anns)
    cands = []  # (y, hour)
    for y, tokens in rows:
        if not (0.05 < y < 0.95):
            continue
        text_tokens = [tok[0] for tok in tokens if len(tok) >= 2 and tok[0].strip()]
        if not text_tokens or not all(is_num(t) for t in text_tokens):
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
        # candidate hour = first merged token in the hour-column x range
        first_text, first_x = merged[0]
        try:
            hv = int(first_text)
        except ValueError:
            continue
        if hmin <= hv <= hmax and x_col[0] < first_x < x_col[1]:
            cands.append((y, hv, first_x))
    if len(cands) < 6:
        return None
    # cluster x to find the hour column center
    xs = sorted(c[2] for c in cands)
    best_center, best_count = None, 0
    for cx in xs:
        cnt = sum(1 for _, _, x in cands if abs(x - cx) < 0.013)
        if cnt > best_count:
            best_count, best_center = cnt, cx
    if best_center is None or best_count < 5:
        return None
    pts = [(y, hv) for y, hv, x in cands if abs(x - best_center) < 0.013]
    a, b = fit_robust(pts)
    return (a, b) if a is not None else None


def build_hour_map(anchors, hmin=5, hmax=23):
    a = {}
    for h in sorted(anchors):
        if hmin <= h <= hmax:
            a[h] = anchors[h]
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
    rows = group_rows(anns)
    sched = []
    for y, tokens in rows:
        if not (0.17 < y < 0.94):
            continue
        text_tokens = [tok[0] for tok in tokens if len(tok) >= 2 and tok[0].strip()]
        if not text_tokens:
            continue
        if not all(is_num(replace_circle_number(t)) for t in text_tokens):
            continue
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
    sched.sort(key=lambda r: -r[0])
    left_xs = [r[1][0][1] for r in sched]
    center = float(sorted(left_xs)[len(left_xs) // 2])
    row_anchors = {}
    for i, (y, digits) in enumerate(sched):
        lead = []
        for text, x in digits:
            if x < center + 0.022:
                lead.append((text, x))
            else:
                break
        if not lead:
            continue
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
        return None, False
    hour_map = {}
    for i, (y, _) in enumerate(sched):
        h = best_start + i
        hour_map[h] = y
    return hour_map, True


def clean_digits(tokens):
    out = []
    for text, x in tokens:
        t = replace_circle_number(text)
        digits = ''.join(c for c in t if c.isdigit())
        if not digits:
            continue
        out.append((digits, x))
    return out


def greedy_minutes(cleaned):
    minutes = []
    i = 0
    n = len(cleaned)
    while i < n:
        text, _ = cleaned[i]
        if len(text) >= 4 and len(text) % 2 == 0:
            pairs = [int(text[j:j + 2]) for j in range(0, len(text), 2)]
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
        if i + 1 < n:
            text2, _ = cleaned[i + 1]
            combined = text + text2
            if len(combined) == 2:
                m = int(combined)
                if 0 <= m <= 59:
                    minutes.append(m)
                i += 2
                continue
        i += 1
    return minutes


def clean_times(times):
    result = []
    prev = None
    for t in times:
        h, m = map(int, t.split(':'))
        cur = h * 60 + m
        if prev is not None and cur - prev <= 1:
            continue
        result.append(t)
        prev = cur
    return result


# ---------------------------------------------------------------------------
# Full parse
# ---------------------------------------------------------------------------
def parse_image(path, station_list, route=None, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocr_retry(gray)

    # summary-card detection: two direction lines stacked
    n_dir = 0
    for _y, _toks in group_rows(anns_g):
        if "方向" in "".join(t[0] for t in _toks if len(t) >= 2):
            n_dir += 1
    if n_dir >= 2:
        return None, {"error": "summary_card"}

    stem = Path(path).stem
    parts = stem.split("-")
    if route is None:
        route = parts[0]
    station = parts[1] if len(parts) > 1 else None

    dest, op = extract_metadata(anns_g, station_list, station, route=route)

    # Robust linear hour model (y = a + b*hour) first: resists OCR misread hour values.
    model = fit_hour_model(anns_g)
    if model:
        a, b = model
        hour_map = {h: a + b * h for h in range(5, 24)}
        hour_col_center = None
    else:
        anchors, hour_col_center = detect_hour_anchors(anns_g)
        hour_map = build_hour_map(anchors)
        if not hour_map or len(hour_map) < 12:
            hour_map, ok = assign_hours_rowbased(anns_g)
    if not hour_map:
        return None, {"error": "hour map failed"}

    hour_boundary = (hour_col_center if hour_col_center is not None else 0.11) + 0.018
    anns_b = anns_g  # reuse gray OCR annotations for minutes (parse_beijing default)
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
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.020:
            continue
        cleaned = clean_digits(nums)
        # Drop hour-column tokens by VALUE (robust when a 2-digit hour like "10"
        # is OCR-split into '1','0' and a fixed x-boundary cuts between them).
        # Consider leading tokens whose x is within the hour-column band.
        consumed = 0
        lead = [t for t in cleaned if t[1] < hour_boundary + 0.035]
        if lead:
            t0 = lead[0][0]
            if t0.isdigit() and int(t0) == best_h:
                consumed = 1
            elif len(lead) >= 2 and lead[0][0].isdigit() and lead[1][0].isdigit():
                if int(lead[0][0] + lead[1][0]) == best_h:
                    consumed = 2
        if consumed == 0:
            # fallback: x-based drop
            for text, x in cleaned:
                if x < hour_boundary:
                    consumed += 1
                else:
                    break
        minutes_tokens = cleaned[consumed:]
        if not minutes_tokens:
            continue
        minutes = greedy_minutes(minutes_tokens)
        result[best_h].extend(minutes)

    times = []
    for h in sorted(result):
        for m in sorted(set(result[h])):
            times.append(f"{h:02d}:{m:02d}")
    times = clean_times(times)
    if not times:
        return None, {"error": "no times"}

    record = {
        "filename": os.path.basename(path),
        "route": route,
        "station": station,
        "destination": dest,
        "operating_time": op,
        "schedule_times": times,
    }
    return record, {}


def _to_min(t):
    h, m = map(int, t.split(':'))
    return h * 60 + m


def schedule_overlap(a, b):
    """Jaccard-ish overlap between two schedules (by minute-of-day)."""
    if not a or not b:
        return 0.0
    sa = set(_to_min(t) for t in a)
    sb = set(_to_min(t) for t in b)
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return inter / min(len(sa), len(sb))


def infer_missing_metadata(records):
    """For records missing destination/operating_time, match by schedule overlap
    to records of the same station that DO have metadata."""
    # group by station
    from collections import defaultdict
    by_station = defaultdict(list)
    for r in records:
        by_station[r["station"]].append(r)
    changed = 0
    for station, recs in by_station.items():
        known = [r for r in recs if r["destination"] and r["operating_time"]]
        unknown = [r for r in recs if not (r["destination"] and r["operating_time"])]
        if not known:
            continue
        for u in unknown:
            best, best_score = None, 0.0
            for k in known:
                s = schedule_overlap(u["schedule_times"], k["schedule_times"])
                if s > best_score:
                    best_score, best = s, k
            if best and best_score >= 0.7:
                u["destination"] = best["destination"]
                u["operating_time"] = best["operating_time"]
                changed += 1
            elif best and best_score >= 0.3:
                u["destination"] = best["destination"]
                changed += 1
    return changed


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------
def process_one(args):
    path, station_list, route = args
    name = Path(path).name
    for attempt in range(3):
        try:
            rec, info = parse_image(path, station_list, route=route)
            if rec is not None:
                return name, rec, None
            if info and info.get("error") == "summary_card":
                return name, None, info
            time.sleep(0.8 * (attempt + 1))
        except Exception as e:
            if attempt >= 2:
                return name, None, {"exception": str(e)}
            time.sleep(0.8 * (attempt + 1))
    return name, None, info


def _fix_service(line, records):
    """大兴机场线新版海报把「星期六和星期日」「星期一至星期五」当表头，
    解析器只认「工作日/双休日/平日」，这里按版式补齐。"""
    if line != "大兴机场":
        return
    for name, r in records.items():
        suffix = name.rsplit(".", 1)[0].rsplit("-", 1)[-1]
        terminal = r["station"] in ("大兴机场", "草桥")
        weekend = suffix == "1" or (suffix == "2" and not terminal)
        r["operating_time"] = "双休日" if weekend else "平日"


def run_line(line, out, workers=3, quiet=False):
    """Parse one line and write app-format JSONL. Returns the record count."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    root = Path.cwd()
    timetables_dir = root / "timetables"
    images = sorted(timetables_dir.glob(f"{line}-*.png")) + \
             sorted(timetables_dir.glob(f"{line}-*.jpg"))
    if not images:
        raise FileNotFoundError(f"no images for line {line}")
    station_list = STATIONS.get(line, [])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if not quiet:
        print(f"line {line}: {len(images)} images, {len(station_list)} stations", flush=True)

    records, fails, skips = {}, {}, {}
    args = [(str(p), station_list, line) for p in images]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(process_one, arg) for arg in args]
        done = 0
        for fut in as_completed(futs):
            name, rec, err = fut.result()
            done += 1
            if rec is None:
                if err and err.get("error") == "summary_card":
                    skips[name] = err
                else:
                    fails[name] = err
            else:
                records[name] = rec
            if not quiet and done % 20 == 0:
                print(f"  {done}/{len(images)} done, {len(fails)} fail", flush=True)

    _fix_service(line, records)
    missing = [r for r in records.values() if not (r["destination"] and r["operating_time"])]
    if missing:
        infer_missing_metadata(list(records.values()))

    with open(out, "w", encoding="utf-8") as f:
        for name in sorted(records):
            f.write(json.dumps(records[name], ensure_ascii=False) + "\n")

    n_meta_missing = sum(1 for r in records.values()
                         if not (r["destination"] and r["operating_time"]))
    if not quiet:
        print(f"[{line}] ok={len(records)} fail={len(fails)} "
              f"summary_card={len(skips)} meta_missing={n_meta_missing} -> {out}")
    for name, info in list(fails.items())[:20]:
        print(f"  FAIL {name}: {info}")
    return len(records)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="燕房线/大兴机场线兜底解析器")
    ap.add_argument("-l", "--line", required=True)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-w", "--workers", type=int, default=3)
    a = ap.parse_args()
    out = a.output or os.path.join("data", "lines", f"{a.line}.jsonl")
    run_line(a.line, out, workers=a.workers)


if __name__ == "__main__":
    main()
