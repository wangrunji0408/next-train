#!/usr/bin/env python3
"""Robust timetable OCR parser for 亦庄/八通/房山/昌平/S1 lines.
Based on /tmp/parse11.py (the 11号线 success) with fixes:
1. smaller hour-gap so hour token doesn't merge with first minute
2. extrapolation for top/bottom hours missed by gray OCR
3. footer/legend row filtering
4. robust operating_time fallback on full text
"""
import sys, os, json
from pathlib import Path
import re
sys.path.insert(0, '/Users/wangrunji/Codes/next-train/scripts')
sys.path.insert(0, '/Users/wangrunji/Codes/next-train')
from timetable_ocr import (group_rows, merge_tokens,
                           extract_metadata, is_num, extract_destination_candidate)
from parse_timetables import convert_and_binarize_image, replace_circle_number
from ocrmac import ocrmac

EN_MAP = {
    # 亦庄
    "Yizhuang Railway": "亦庄火车站", "Songjiazhuang": "宋家庄", "Wanyuanjie": "万源街",
    "Yizhuangwenhuayuan": "亦庄文化园", "Yizhuangqiao": "亦庄桥", "Tongjinanlu": "同济南路",
    "Xiaohongmen": "小红门", "Jiugong": "旧宫", "Ciqu": "次渠", "Ciqunan": "次渠南",
    "Jinghailu": "经海路", "Xiaocun": "肖村", "Rongjingdongjie": "荣京东街",
    "Rongchangdongjie": "荣昌东街",
    # 八通
    "Universal Resort": "环球度假区", "Tuqiao": "土桥", "Lihe": "梨园", "Jiukeshu": "九棵树",
    "Guoyuan": "果园", "Shuangqiao": "双桥", "Guanzhuang": "管庄", "Baliqiao": "八里桥",
    "Gaobeidian": "高碑店", "Communication Univ. of China": "传媒大学", "Huazhuang": "花庄",
    "Tongzhou Beiyuan": "通州北苑", "Linheli": "临河里",
    # 房山
    "Dongguantounan": "东管头南", "Huaxiang Dongqiao": "花乡东桥", "Baipenyao": "白盆窑",
    "Guogongzhuang": "郭公庄", "Dabaotai": "大葆台", "Daotian": "稻田", "Changyang": "长阳",
    "Libafang": "篱笆房", "Guangyangcheng": "广阳城", "Liangxiang Univ. Town North": "良乡大学城北",
    "Liangxiang Univ. Town": "良乡大学城", "Liangxiang Univ. Town West": "良乡大学城西",
    "Liangxiang Nanguan": "良乡南关", "Suzhuang": "苏庄", "Yancundong": "阎村东",
    "Shoujingmao": "首经贸",
    # 昌平
    "Xitucheng": "西土城", "Xueyuanqiao": "学院桥", "Liudaokou": "六道口", "Xuezhigarden": "学知园",
    "Xierqi": "西二旗", "Life Science Park": "生命科学园", "Zhuxinzhuang": "朱辛庄",
    "Gonghuacheng": "巩华城", "Shahe": "沙河", "Shahe Univ. Park": "沙河高教园",
    "Changping": "昌平", "Changping Xishankou": "昌平西山口", "Shisanling Scenic Area": "十三陵景区",
    "Nanshao": "南邵", "Beishaowa": "北邵洼", "Changping Dongguan": "昌平东关",
    "Zhufangbei": "朱房北", "Qinghe": "清河", "Qinghe Xiaoyingqiao": "清河小营桥",
    "Qinghe Station": "清河站", "Jimenqiao": "蓟门桥",
    # S1
    "Pingguoyuan": "苹果园", "Jinanqiao": "金安桥", "Qiaohuying": "桥户营",
    "Sishidaoqiao": "四道桥", "Li. yuanzhuang": "栗园庄", "Xiaoyuan": "小园", "Shichang": "石厂",
    "Shanggai": "上岸",
}

EN_SUB = [
    ("yizhuang", "亦庄火车站"), ("songjiazhuang", "宋家庄"),
    ("universal", "环球度假区"), ("tuqiao", "土桥"), ("guoyuan", "果园"),
    ("dongguantounan", "东管头南"), ("yancundong", "阎村东"), ("dabaotai", "大葆台"),
    ("changping", "昌平"), ("xishankou", "昌平西山口"), ("jimenqiao", "蓟门桥"),
    ("pingguoyuan", "苹果园"), ("jinanqiao", "金安桥"), ("shichang", "石厂"),
]


def greedy_merge(tokens):
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


def merge_minutes_lone(tokens, gap, lone_starts):
    """Merge minutes, but digits at positions in lone_starts are treated as
    lone single-digit minutes (they start a new minute column, e.g. after a ◎)."""
    if not tokens:
        return []
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        text, x = tokens[i]
        if len(text) == 2 and is_num(text):
            result.append((text, x))
            i += 1
            continue
        # single char
        if x in lone_starts:
            # lone minute (tens digit dropped, e.g. "7" for 07 after ◎)
            if is_num(text):
                result.append((text, x))
            i += 1
            continue
        if i + 1 < n:
            nxt = tokens[i+1]
            if len(nxt[0]) == 1 and nxt[1] not in lone_starts:
                cand = text + nxt[0]
                if is_num(cand) and 0 <= int(cand) <= 59:
                    result.append((cand, x))
                    i += 2
                    continue
        # fallback: lone or skip
        if is_num(text) and 0 <= int(text) <= 9:
            result.append((text, x))
        i += 1
    return result


def detect_hour_column_loose(anns, ymin=0.055, hour_gap=0.018, x_min=0.02, x_max=0.55):
    rows = group_rows(anns)
    candidates = []
    for y, tokens in rows:
        if not (ymin < y < 0.90):
            continue
        if is_footer_row(tokens):
            continue
        nums = []
        for tok in tokens:
            if is_num(tok[0]):
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
    # monotonicity check: hour increases while y decreases (larger y = higher up)
    ys = [col[h] for h in hours]
    if len(ys) >= 3 and not all(ys[i] > ys[i+1] for i in range(len(ys)-1)):
        return None, None
    result = dict(col)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i + 1]
        if h2 - h1 > 1:
            y1, y2 = col[h1], col[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result, best_center


def hour_spacing(hour_map):
    hs = sorted(hour_map)
    diffs = [abs(hour_map[hs[i+1]] - hour_map[hs[i]]) for i in range(len(hs)-1)]
    if not diffs:
        return 0.03
    return sorted(diffs)[len(diffs)//2]


def fit_robust(pts):
    """Robust linear fit y = a + b*hour using Theil-Sen (median of slopes).
    pts: [(y, hour)]. Returns (a, b) or (None, None)."""
    pts = list(set((round(y,4), h) for y, h in pts))
    if len(pts) < 4:
        return None, None
    # Theil-Sen slope: median of pairwise slopes
    slopes = []
    n = len(pts)
    for i in range(n):
        for j in range(i+1, n):
            y1, h1 = pts[i]; y2, h2 = pts[j]
            if h2 != h1:
                slopes.append((y2 - y1) / (h2 - h1))
    if not slopes:
        return None, None
    slopes.sort()
    b = slopes[len(slopes)//2]
    if abs(b) < 0.01 or abs(b) > 0.08:
        return None, None
    # intercept = median of (y - b*h)
    ints = sorted(y - b*h for y, h in pts)
    a = ints[len(ints)//2]
    # optional refinement: keep points near the line and refit (least squares)
    spacing = abs(b)
    keep = [(y, h) for y, h in pts if abs(y - (a + b*h)) < 2.5*spacing]
    if len(keep) >= 4:
        xs = [p[1] for p in keep]; ys = [p[0] for p in keep]
        n2 = len(xs)
        sx = sum(xs); sy = sum(ys); sxx = sum(x*x for x in xs); sxy = sum(x*y for x, y in zip(xs, ys))
        denom = n2*sxx - sx*sx
        if denom != 0:
            b2 = (n2*sxy - sx*sy)/denom
            a2 = (sy - b2*sx)/n2
            if abs(b2) > 0.01 and abs(b2) < 0.08:
                a, b = a2, b2
    return a, b


def detect_hour_model(anns, hour_gap=0.018, x_min=0.02, x_max=0.55):
    """Detect hour column position and fit y=a+b*hour from readable anchors.
    Returns (a, b, hour_x) or None."""
    rows = group_rows(anns)
    cands = []
    for y, tokens in rows:
        if not (0.05 < y < 0.90):
            continue
        if is_footer_row(tokens):
            continue
        nums = [(t[0], t[2][0]) for t in tokens if is_num(t[0])]
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
            cands.append((y, hv, x))
    if len(cands) < 6:
        return None
    xs = sorted(c[2] for c in cands)
    best_center, best_count = None, 0
    for cx in xs:
        cnt = sum(1 for _, _, x in cands if abs(x - cx) < 0.015)
        if cnt > best_count:
            best_count, best_center = cnt, cx
    if best_center is None or best_count < 6:
        return None
    pts = [(y, hv) for y, hv, x in cands if abs(x - best_center) < 0.015]
    a, b = fit_robust(pts)
    if a is None:
        return None
    return a, b, best_center


def is_footer_row(tokens):
    txt = "".join(t[0] for t in tokens if len(t) >= 2)
    for ch in ["表", "分", "点", "示", "终", "发"]:
        if ch in txt:
            return True
    return False


def extract_operating_time_full(gray_anns):
    dest, op = extract_metadata(gray_anns)
    if op:
        return op
    all_text = "".join(t[0] for t in gray_anns if len(t) >= 2)
    for label, keywords in [("工作日", ["工作日", "作日", "Weekdays"]),
                             ("双休日", ["双休日", "Weekends"]),
                             ("平日", ["平日", "Ordinary"]),
                             ("星期五", ["星期五", "周五", "Friday"])]:
        for k in keywords:
            if k in all_text:
                return label
    return None


def _station_in_line(line_text, station_list):
    """Find a station from station_list present in line_text (contiguous)."""
    for st in station_list:
        if st and st in line_text:
            return st
    return None


def _is_subseq(needle, haystack):
    """True if needle's chars appear in haystack in order."""
    it = iter(haystack)
    return all(c in it for c in needle)


def _fuzzy_station(cand, station_list):
    """Fuzzy-match a garbled Chinese candidate against station_list."""
    from thefuzz import fuzz
    best, best_score = None, 0
    for st in station_list:
        if not st:
            continue
        score = fuzz.ratio(cand, st)
        if score > best_score:
            best_score, best = score, st
    if best and best_score >= 55:
        return best
    return None


def extract_destination_full(gray_anns, station_list):
    """Extract destination from the real direction line (开往...方向 / To ...).
    Only lines near the top with '开往'/'方向' or 'To' are considered, avoiding
    false matches from bottom legend notes (e.g. 'Tombs' contains 'To')."""
    rows = group_rows(gray_anns)
    for y, tokens in rows:
        texts = "".join(tok[0] for tok in tokens if len(tok) >= 2)
        if not texts:
            continue
        # a real direction line has Chinese direction markers, or an English "To"
        has_cn_dir = ("开往" in texts) or ("方向" in texts) or ("开向" in texts)
        has_en_to = ("To" in texts) or ("to" in texts)
        if not (has_cn_dir or (has_en_to and y > 0.5)):
            continue
        # try Chinese station match first
        st = _station_in_line(texts, station_list)
        if st:
            return st
        # English fallback (normalize spaces; OCR may embed "To" in the name)
        low = texts.lower().replace(" ", "")
        for en, cn in EN_MAP.items():
            enl = en.lower().replace(" ", "")
            if enl in low:
                return cn
            # subsequence match handles OCR inserting "to" (e.g. JimenToQiao)
            if len(enl) >= 5 and _is_subseq(enl, low):
                return cn
        for en, cn in EN_SUB:
            if en in low:
                return cn
        if has_cn_dir:
            # Chinese direction present but no station matched — try regex + fuzzy
            cand = extract_destination_candidate(texts)
            if cand and not cand.isdigit() and len(cand) <= 12:
                st = _fuzzy_station(cand, station_list)
                if st:
                    return st
                return cand
    return None


def parse_image(path, gap=0.022, station_list=None, debug=False):
    pairs = convert_and_binarize_image(path)
    gray, binary = pairs[0]
    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination = extract_destination_full(anns_g, station_list)
    operating_time = extract_operating_time_full(anns_g)

    # prefer model-based hour detection; fall back to rowlead hour_map
    model = detect_hour_model(anns_g)
    hour_map = None
    hour_x = None
    if model:
        a, b, hour_x = model
        spacing = abs(b)
    else:
        hour_map, hour_x = detect_hour_column_loose(anns_g)
        if not hour_map:
            return None
        spacing = hour_spacing(hour_map)
        min_h, max_h = min(hour_map), max(hour_map)
        y_max_top = hour_map[min_h]
        y_min_bot = hour_map[max_h]

    anns_b = anns_g  # reuse the gray OCR annotations for minutes too
    # for each hour, keep the row closest to the model-predicted y (handles OCR row-splitting)
    best_rows = {}  # hour -> (dist, y, merged_minutes)
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (0.06 < y < 0.95):
            continue
        if is_footer_row(tokens):
            continue
        nums = []
        block_xs = []  # x positions of block symbols that mark a minute column
        for tok in tokens:
            txt = replace_circle_number(tok[0])
            if is_num(txt):
                nums.append((txt, tok[2][0]))
            elif tok[0] in "◎○●◆□▲△":
                block_xs.append(tok[2][0])
        if len(nums) < 2:
            continue
        nums.sort(key=lambda v: v[1])
        # digits immediately right of a block symbol start a new (lone) minute
        lone_starts = set()
        for bx in block_xs:
            for t, x in nums:
                if 0 < x - bx < 0.035:
                    lone_starts.add(x)
                    break
        # table rows should have a reasonable horizontal span of digits
        if nums[-1][1] - nums[0][1] < 0.03:
            continue
        if model:
            hf = (y - a) / b
            best_h = int(round(hf))
            if not (0 <= best_h <= 24):
                continue
            # row must be near a grid position (filters footers/legends)
            if abs(y - (a + b*best_h)) > spacing * 0.6:
                continue
        else:
            best_h, best_d = None, 1e9
            for h, hy in hour_map.items():
                d = abs(y - hy)
                if d < best_d:
                    best_d, best_h = d, h
            if best_h is None:
                continue
            if best_d > spacing * 0.6:
                if y > y_max_top:
                    best_h = min_h - round((y - y_max_top) / spacing)
                elif y < y_min_bot:
                    best_h = max_h + round((y_min_bot - y) / spacing)
                if not (0 <= best_h <= 24):
                    continue
        # drop hour-column tokens by x-position (robust to OCR dropping hour digits)
        hx = hour_x if hour_x else 0.13
        drop = 0
        while drop < len(nums) and nums[drop][1] < hx + 0.025:
            drop += 1
        # fallback: if nothing dropped and first token value-matches best_h (2-char), drop it
        if drop == 0 and nums and abs(nums[0][1] - hx) < 0.045:
            t0 = nums[0][0]
            if len(t0) == 2 and is_num(t0) and int(t0) == best_h:
                drop = 1
            elif len(t0) == 1 and is_num(t0) and int(t0) == best_h and \
                    (len(nums) == 1 or nums[1][1] - nums[0][1] > 0.03):
                drop = 1
        nz = nums[drop:]
        shifted_lone = set()
        for t, x in nz:
            if any(abs(x - lx) < 0.004 for lx in lone_starts):
                shifted_lone.add(x)
        merged = merge_minutes_lone(nz, gap, shifted_lone)
        ms = []
        for text, x in merged:
            try:
                m = int(text)
                if 0 <= m <= 59:
                    ms.append(m)
            except ValueError:
                pass
        dist = abs(y - (a + b*best_h)) if model else 0.0
        cur = best_rows.get(best_h)
        if cur is None or dist < cur[0]:
            best_rows[best_h] = (dist, y, ms)

    result = {}
    for h, (dist, y, ms) in best_rows.items():
        result[h] = ms
    times = []
    for h in sorted(result):
        if not (0 <= h <= 24):
            continue
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
    ap.add_argument("-l", "--line", required=True)
    ap.add_argument("-g", "--gap", type=float, default=0.022)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-d", "--debug", action="store_true")
    a = ap.parse_args()
    timetables_dir = Path("/Users/wangrunji/Codes/next-train/timetables")
    images = sorted(timetables_dir.glob(f"{a.line}-*.jpg"))
    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])
    out = a.output or f"/Users/wangrunji/Codes/next-train/data/lines/{a.line}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = fail = 0
    fails = []
    with open(out, "w", encoding="utf-8") as fo:
        for img in images:
            r = parse_image(str(img), gap=a.gap, station_list=station_list, debug=a.debug)
            if r is None:
                fail += 1
                fails.append(img.name)
                print(f"FAIL {img.name}")
                continue
            ok += 1
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"line={a.line} ok={ok} fail={fail}")
    if fails:
        print(f"fails: {fails}")
    print(f"output: {out}")
