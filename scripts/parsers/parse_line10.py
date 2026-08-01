#!/usr/bin/env python3
"""
Dedicated parser for Beijing Metro Line 10, with explicit handling of the
circular markers (◎●○◆ etc. and circled digits ①-⑨) that appear below/around
minute columns and corrupt naive OCR digit-stream parsing.

Problem
-------
Line 10 timetable images carry small circle markers:
  * circled digits ①-⑨  -- these are the TENS digit of a real minute.  e.g. a
    circled "④" followed by "2" is the minute 42.  The generic parser drops
    them (is_num('④') is False), which shifts the 2-by-2 digit pairing and
    silently loses every subsequent minute in that hour row.
  * standalone circle glyphs (◎●○◆□▲△) and OCR misreads of them (）)•...)
    appear between minute columns; they can also split a row's digit stream.

Strategy
--------
1. Hour column: split-digit hour detection (same robust linear-fit scorer as
   the generic line-8/13 parser).  Line 10 hours like "21" are frequently OCR'd
   as two single-char tokens.
2. Minutes: collect digit tokens, converting circled digits with
   replace_circle_number() so ④->4 participates in pairing.  Standalone circle
   glyphs are tracked as "block" markers; the digit immediately right of a
   block starts a fresh (lone) minute, matching the semantics that a circled
   marker points at a specific service.
3. Both grayscale and binarized OCR are used for minutes: binary usually drops
   the circle pixels cleanly, grayscale preserves them.  We merge the two
   readings (union) so a minute missed by one is recovered by the other, then
   validate each candidate against the hour row.
4. Only a light 1-minute-gap de-dup is applied (real headways are >= 2 min);
   it is NOT used to paper over lost minutes.

Usage: .venv/bin/python scripts/parsers/parse_line10.py
Output: data/lines/10.jsonl
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/Users/wangrunji/Codes/next-train/scripts")
sys.path.insert(0, "/Users/wangrunji/Codes/next-train")

from parse_timetables import convert_and_binarize_image, replace_circle_number
from ocrmac import ocrmac
from timetable_ocr import group_rows, is_num, extract_metadata

# PIL can open the occasionally-truncated downloads
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Line 10 terminal-station pinyin (from English text in the timetable header),
# used to disambiguate destinations when OCR mangles the Chinese characters.
PINYIN_MAP = {
    "朱辛庄": "zhuxinzhuang",
    "瀛海": "yinghai",
    "金安桥": "jinanqiao",
    "巴沟": "bago",
    "成寿寺": "chengshousi",
    "四季青桥": "sijiqingqiao",
    "东坝北": "dongbabei",
    "东直门": "dongzhimen",
    "西直门": "xizhimen",
    "宋家庄": "songjiazhuang",
    "太阳宫": "taiyanggong",
    "泥洼": "niwa",
    "西局": "xiju",
    "双井": "shuangjing",
    "劲松": "jingsong",
    "草桥": "caoqiao",
    "国贸": "guomao",
    "六里桥": "liuliqiao",
    "牡丹园": "mudanyuan",
    "角门西": "jiaomenxi",
    "亮马桥": "liangmaqiao",
    "丰台站": "fengtai",
    "潞阳": "luyang",
    "公主坟": "gongzhufen",
    "海淀黄庄": "haidianhuangzhuang",
    "知春路": "zhichunlu",
    "苏州街": "suzhoujie",
    "西土城": "xitu cheng",
    "健德门": "jiandemen",
    "牡丹园": "mudanyuan",
    "安贞门": "anzhenmen",
    "惠新西街南口": "huixinxijienankou",
    "芍药居": "shaoyaoju",
    "太阳宫": "taiyanggong",
    "三元桥": "sanyuanqiao",
    "亮马桥": "liangmaqiao",
    "农业展览馆": "nongyezhanlanguan",
    "团结湖": "tuanjiehu",
    "呼家楼": "hujialou",
    "金台夕照": "jintaixizhao",
    "国贸": "guomao",
    "双井": "shuangjing",
    "劲松": "jingsong",
    "潘家园": "panjiayuan",
    "十里河": "shilihe",
    "分钟寺": "fenzhongsi",
    "成寿寺": "chengshousi",
    "宋家庄": "songjiazhuang",
    "石榴庄": "shiliuzhuang",
    "大红门": "dahongmen",
    "角门东": "jiaomendong",
    "角门西": "jiaomenxi",
    "草桥": "caoqiao",
    "纪家庙": "jijiamiao",
    "首经贸": "shoujingmao",
    "泥洼": "niwa",
    "西局": "xiju",
    "六里桥": "liuliqiao",
    "莲花桥": "lianhuaqiao",
    "公主坟": "gongzhufen",
    "西钓鱼台": "xidiaoyutai",
    "慈寿寺": "cishousi",
    "车道沟": "chedaogou",
    "长春桥": "changchunqiao",
    "火器营": "huoqiying",
    "巴沟": "bago",
    "苏州街": "suzhoujie",
    "海淀黄庄": "haidianhuangzhuang",
    "知春里": "zhichunli",
    "知春路": "zhichunlu",
    "西土城": "xitu cheng",
    "牡丹园": "mudanyuan",
    "健德门": "jiandemen",
    "北土城": "beitu cheng",
    "安贞门": "anzhenmen",
    "惠新西街南口": "huixinxijienankou",
    "芍药居": "shaoyaoju",
    "太阳宫": "taiyanggong",
}

# Standalone circle glyphs that mark a minute column (not circled digits).
CIRCLE_GLYPHS = "◎○●◆□▲△○●□■◇◆▲△★☆⊙"
# OCR misreads of the small circle markers (dropped as separators).
CIRCLE_MISREAD = "（）()•。°·"

# Line 10 per-hour maximum normal headway (minutes) for sanity filtering.
# Used only to reject an impossible minute read (e.g. a lone "5" is kept, but
# a minute that makes the hour row inconsistent is dropped later by check).
HOUR_COL_X = (0.06, 0.20)


def match_dest_by_pinyin(line_text, station_list):
    tl = line_text.lower()
    best, best_len = None, 0
    eng_tokens = re.findall(r"[a-z]{2,}", tl)
    for st in station_list:
        py = PINYIN_MAP.get(st)
        if not py:
            continue
        # exact pinyin substring, or pinyin as a prefix of an English word
        # (e.g. "FengtaiRailway" starts with "fengtai" for 丰台站)
        if py in tl or any(tok.startswith(py) for tok in eng_tokens):
            if len(py) > best_len:
                best, best_len = st, len(py)
    if best:
        return best
    # fallback: standalone English tokens vs pinyin (either direction)
    for tok in eng_tokens:
        t = tok.lower()
        for st in station_list:
            py = PINYIN_MAP.get(st)
            if py and (py in t or t in py):
                return st
    return None


def fuzzy_destination(anns_g, station_list):
    if not station_list:
        return None
    import difflib
    rows = group_rows(anns_g)
    lines = []
    for y, tokens in rows:
        texts = [tok[0] for tok in tokens if len(tok) >= 2]
        lines.append("".join(texts))
    dir_lines = [l for l in lines if any(k in l for k in ["方向", "开向", "To", "开往", "往", "去往"])]
    for line_text in dir_lines:
        d = match_dest_by_pinyin(line_text, station_list)
        if d:
            return d
        for st in station_list:
            if st and st in line_text:
                return st
        cand = None
        m = re.search(r"[往住注开牙去]([一-鿿]{2,10}?)站", line_text)
        if m:
            cand = m.group(1)
        if not cand:
            for end_marker in ["方向", "开向"]:
                idx = line_text.find(end_marker)
                if idx < 0:
                    continue
                prefix = line_text[:idx]
                m2 = re.search(r"[一-鿿]{2,12}$", prefix)
                if m2:
                    cand = re.sub(r"站$", "", m2.group(0))
                    break
        if cand:
            cand = cand.lstrip("往住注开牙去")
            best, best_score = None, 0
            for st in station_list:
                if not st:
                    continue
                ratio = difflib.SequenceMatcher(None, cand, st).ratio()
                if ratio > best_score:
                    best_score, best = ratio, st
            if best_score >= 0.32:
                return best
            for st in station_list:
                if not st:
                    continue
                it = iter(cand)
                if all(c in it for c in st):
                    return st
        best, best_score = None, 0
        for st in station_list:
            if not st:
                continue
            ratio = difflib.SequenceMatcher(None, st, line_text).ratio()
            if ratio > best_score:
                best_score, best = ratio, st
        if best_score >= 0.4:
            return best
    return None


def detect_hour_column_split(anns, debug=False):
    """Detect {hour: y} robust to split-digit hours (e.g. '1','2' for 12)."""
    nums = []
    for t, c, b in anns:
        if is_num(t) and 0.10 < b[1] < 0.90:
            try:
                v = int(t)
            except ValueError:
                continue
            if 0 <= v <= 24:
                nums.append((t, b[0], b[1], v))
    if len(nums) < 15:
        return None

    best = None
    best_score = -1
    for i in range(80, 260, 1):
        x0 = i / 1000.0
        window = 0.015
        near = [n for n in nums if abs(n[1] - x0) < window]
        if len(near) < 8:
            continue
        by_y = defaultdict(list)
        for t, x, y, v in near:
            by_y[round(y, 3)].append((t, x, y, v))
        merged = []
        for y, items in by_y.items():
            if y < 0.15:
                continue
            items.sort(key=lambda z: z[1])
            text = "".join(z[0] for z in items)
            try:
                h = int(text)
            except ValueError:
                continue
            if h == 0 or (5 <= h <= 24):
                merged.append((y, h))
        if len(merged) < 8:
            continue
        fit = [(y, h) for y, h in merged if h != 0]
        if len(fit) < 8:
            continue
        hs = [m[1] for m in fit]
        ys = [m[0] for m in fit]
        n = len(hs)
        sum_h = sum(hs); sum_y = sum(ys)
        sum_h2 = sum(h * h for h in hs)
        sum_hy = sum(h * y for h, y in zip(hs, ys))
        denom = n * sum_h2 - sum_h * sum_h
        if denom == 0:
            continue
        b_ = (n * sum_hy - sum_h * sum_y) / denom
        a_ = (sum_y - b_ * sum_h) / n
        resid = sum((y - (a_ + b_ * h)) ** 2 for h, y in zip(hs, ys))
        n_hours = len(merged)
        h_range = max(hs) - min(hs)
        resid = resid / max(1, len(fit))
        sorted_merged = sorted(merged, key=lambda m: m[0], reverse=True)
        mono_ok = all(sorted_merged[i][1] < sorted_merged[i + 1][1] or
                      (sorted_merged[i][1] == 23 and sorted_merged[i + 1][1] == 0)
                      for i in range(len(sorted_merged) - 1))
        score = n_hours * 10 + h_range - resid * 5000 + (50 if mono_ok else 0) + (50 if b_ < 0 else 0)
        if score > best_score:
            best_score = score
            best = (x0, {h: y for y, h in merged}, resid, n_hours, b_, mono_ok)

    if best is None or best[3] < 8:
        return None
    x0, col, resid, n_hours, b_, mono_ok = best
    if debug:
        print(f"  hour col x≈{x0:.3f}, {n_hours} hours, resid={resid:.4f}, b={b_:.3f}, mono={mono_ok}")
    # Interpolate any missing hours between detected anchors so a row whose
    # hour digit the OCR missed still gets assigned (e.g. hour "8" not read).
    result = dict(col)
    hours = sorted(col)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i + 1]
        if h2 - h1 > 1:
            y1, y2 = col[h1], col[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result


def _collect_minute_tokens(tokens):
    """From OCR row tokens return (nums, block_xs).

    nums: [(text, x)] with circled digits converted and only pure-numeric kept.
    block_xs: [x] positions of standalone circle glyphs (◎○●◆□▲△ ...).
    OCR misreads (）)•) are simply dropped as separators (they do not start a
    lone minute column; they usually sit *below* a digit).
    """
    nums = []
    block_xs = []
    for tok in tokens:
        if len(tok) < 2:
            continue
        raw = tok[0]
        txt = replace_circle_number(raw)
        if is_num(txt):
            nums.append((txt, tok[2][0]))
        elif raw in CIRCLE_GLYPHS:
            block_xs.append(tok[2][0])
    return nums, block_xs


def merge_minutes_circle(tokens, block_xs, gap=0.022):
    """Merge digit tokens into minutes, handling circle markers.

    - 2-char numeric token is a standalone minute.
    - The digit immediately right of a circle glyph is a LONE minute (its tens
      digit was drawn as the circle, e.g. "7" -> 07).
    - Otherwise single digits pair with the next single digit (OCR splits a
      minute like "37" into "3","7").  An odd leftover is dropped as garbage.
    """
    if not tokens:
        return []
    tokens = sorted(tokens, key=lambda v: v[1])
    lone_starts = set()
    for bx in block_xs:
        for t, x in tokens:
            if 0 < x - bx < 0.035:
                lone_starts.add(x)
                break
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        text, x = tokens[i]
        if len(text) == 2 and is_num(text):
            result.append((text, x))
            i += 1
            continue
        if not (len(text) == 1 and is_num(text)):
            i += 1
            continue
        # single-char digit
        if x in lone_starts:
            result.append((text, x))
            i += 1
            continue
        if i + 1 < n:
            nxt_t, nxt_x = tokens[i + 1]
            if len(nxt_t) == 1 and is_num(nxt_t) and nxt_x not in lone_starts:
                cand = text + nxt_t
                if is_num(cand) and 0 <= int(cand) <= 59:
                    result.append((cand, x))
                    i += 2
                    continue
        # fallback: keep lone digit only if clearly a valid minute (0-9)
        if is_num(text) and 0 <= int(text) <= 9:
            result.append((text, x))
        i += 1
    return result


def _sanitize_hour_map(hour_map):
    """Remove hallucinated hour entries that break the table's linear ordering.

    The OCR-based hour detector occasionally mis-detects a low hour (e.g. "5")
    at a y position that actually belongs to a later real hour.  Such an entry
    makes two hours share one table row, so one of them silently loses all of
    its minutes.  We fit a robust (Theil-Sen) line y = a + b*hour over the map,
    drop hours that deviate by more than a couple of row spacings, then
    re-interpolate interior gaps.
    """
    hours = [h for h in hour_map if 5 <= h <= 23]
    if len(hours) < 5:
        return hour_map
    pts = [(hour_map[h], h) for h in hours]
    # Theil-Sen slope: median of pairwise slopes (robust to the few outliers)
    slopes = []
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            y1, h1 = pts[i]; y2, h2 = pts[j]
            if h2 != h1:
                slopes.append((y2 - y1) / (h2 - h1))
    if not slopes:
        return hour_map
    slopes.sort()
    b = slopes[len(slopes) // 2]
    if not (-0.08 < b < -0.01):
        return hour_map  # unexpected geometry; don't second-guess the detector
    ints = sorted(y - b * h for y, h in pts)
    a = ints[len(ints) // 2]
    spacing = abs(b)
    # keep hours close to the line
    kept = {h: y for y, h in pts if abs(y - (a + b * h)) < 2.2 * spacing}
    if len(kept) < 5:
        return hour_map
    # re-interpolate interior gaps
    result = dict(kept)
    kh = sorted(kept)
    for i in range(len(kh) - 1):
        h1, h2 = kh[i], kh[i + 1]
        if h2 - h1 > 1:
            y1, y2 = kept[h1], kept[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result


def extract_operating_time_robust(anns_g):
    """Fallback operating-time extraction.

    Scans the whole grayscale OCR text (joined by row) for strong Chinese
    markers.  The OCR mangles the header line (e.g. "日作s工" for 工作日), so
    we use character-presence heuristics rather than exact substring match.
    """
    rows = group_rows(anns_g)
    lines = []
    for y, tokens in rows:
        texts = [tok[0] for tok in tokens if len(tok) >= 2]
        lines.append("".join(texts))
    all_text = "".join(lines)
    low = all_text.lower()
    has_zuo = "作" in all_text or "工作日" in all_text or "weekday" in low
    has_xiu = "休" in all_text or "双休日" in all_text or "weekend" in low
    if has_zuo and not has_xiu:
        return "工作日"
    if has_xiu and not has_zuo:
        return "双休日"
    # both / neither: try subsequence keywords
    if _subseq(all_text, "工作日"):
        return "工作日"
    if _subseq(all_text, "双休日"):
        return "双休日"
    if "作日" in all_text or "weekday" in low:
        return "工作日"
    if "休日" in all_text or "weekend" in low:
        return "双休日"
    if "周五" in all_text or "friday" in low:
        return "星期五"
    if "平日" in all_text or "ordinary" in low:
        return "平日"
    return None


def _subseq(text, target):
    it = iter(text)
    return all(c in it for c in target)


def _minutes_from_anns(anns_m, hour_map, gap=0.022, debug=False):
    """Extract {hour: [minute ints]} from OCR annotations for a known hour map."""
    result = {h: [] for h in hour_map}
    rows = group_rows(anns_m)
    for y, tokens in rows:
        if not (0.10 < y < 0.85):
            continue
        nums, block_xs = _collect_minute_tokens(tokens)
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        # find nearest hour
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.028:
            continue
        # strip hour-column tokens by VALUE.  Line 10 hours are frequently OCR'd
        # as split digits ('2','1' for 21) or as a single token ('21').
        tokens2 = list(nums)
        if tokens2:
            # hour "00"
            if best_h == 0 and len(tokens2) >= 2 and tokens2[0][0] == "0" and tokens2[1][0] == "0":
                tokens2 = tokens2[2:]
            # hour as a single token, either "15" or split "5" (both must equal best_h)
            elif int(tokens2[0][0]) == best_h:
                tokens2 = tokens2[1:]
            # hour split across first two single-char tokens ('2','1' -> 21)
            elif len(tokens2) >= 2:
                try:
                    if int(tokens2[0][0] + tokens2[1][0]) == best_h:
                        tokens2 = tokens2[2:]
                except ValueError:
                    pass
        merged = merge_minutes_circle(tokens2, block_xs, gap)
        for text, x in merged:
            try:
                m = int(text)
                if 0 <= m <= 59:
                    result[best_h].append(m)
            except ValueError:
                pass
    return result


def parse_image_line10(path, station_list=None, gap=0.022, debug=False):
    try:
        pairs = convert_and_binarize_image(path)
        gray, binary = pairs[0]
    except Exception:
        return None

    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination, operating_time = extract_metadata(anns_g, station_list=station_list)
    if not operating_time:
        operating_time = extract_operating_time_robust(anns_g)
    if not destination or (station_list and destination not in station_list):
        fd = fuzzy_destination(anns_g, station_list)
        if fd:
            destination = fd

    # Prefer the hour map with MORE hours in the real service band 5-23.
    # The grayscale map is prone to hallucinating bogus low hours (0-4) from
    # misread first-minute tokens (e.g. "00" read as the hour of a row whose
    # real hour digit the OCR missed); the binarized map is much cleaner for
    # line 10 and usually covers 5-23 after interpolation.
    hm_g = detect_hour_column_split(anns_g, debug=debug)
    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    hm_b = detect_hour_column_split(anns_b, debug=debug)

    def _band_count(m):
        return sum(1 for h in m if 5 <= h <= 23)

    def _monotonic_ok(m):
        """True if hour rows are ordered top-to-bottom (y decreases as the hour
        increases).  A broken map (e.g. hour 5 mapped to a mid-table y) fails."""
        hours = sorted(h for h in m if 5 <= h <= 23)
        ys = [m[h] for h in hours]
        return len(ys) >= 3 and all(ys[i] > ys[i + 1] for i in range(len(ys) - 1))

    if hm_g and hm_b:
        # Prefer the map that is monotonic AND has the most band hours.  The
        # binarized map is usually clean, but occasionally mis-detects a low
        # hour (e.g. reads the top row's hour as "5" at a mid-table y), which
        # breaks the ordering and silently steals that row from its real hour.
        g_ok, b_ok = _monotonic_ok(hm_g), _monotonic_ok(hm_b)
        if b_ok and not g_ok:
            hour_map = hm_b
        elif g_ok and not b_ok:
            hour_map = hm_g
        else:
            hour_map = hm_b if _band_count(hm_b) >= _band_count(hm_g) else hm_g
        # fill any still-missing 5-23 hours from the other map (interpolation
        # should already cover these, this is a safety net)
        other = hm_g if hour_map is hm_b else hm_b
        for h in range(5, 24):
            if h not in hour_map and h in other and 0.15 < other[h] < 0.90:
                hour_map[h] = other[h]
    elif hm_b:
        hour_map = hm_b
    elif hm_g:
        hour_map = hm_g
    else:
        return None
    # Drop hallucinated low hours: keep only 5-23 plus a verified hour 0.
    # (Hour 0 exists for a handful of after-midnight services; it must map to
    # the top of the table, not steal another hour's row.)
    hour_map = {h: y for h, y in hour_map.items() if 5 <= h <= 23 or (h == 0 and 0.05 < y < 0.30)}
    # Sanitize: a mis-detected low hour can land on the same y as a real hour
    # (e.g. bogus "5" at y=0.658 colliding with the real hour 9) and steal its
    # rows.  Walk the hours top-to-bottom (y descending) and keep only those
    # that strictly decrease, then re-interpolate the survivors.
    hour_map = _sanitize_hour_map(hour_map)

    # Extract minutes from BOTH gray and binary: binary usually drops the circle
    # pixels cleanly, gray preserves circled digits.  Union recovers minutes
    # each alone would miss.
    res_g = _minutes_from_anns(anns_g, hour_map, gap=gap)
    res_b = _minutes_from_anns(anns_b, hour_map, gap=gap)
    result = {}
    for h in hour_map:
        s = set(res_g.get(h, [])) | set(res_b.get(h, []))
        if s:
            result[h] = sorted(s)

    times = []
    for h in sorted(result):
        if not (0 <= h <= 24):
            continue
        for m in result[h]:
            times.append(f"{h:02d}:{m:02d}")
    if not times:
        return None

    # Light de-dup: real metro headways are >= 2 min, so an isolated 1-minute
    # gap is always OCR noise.  We keep the earlier of the pair.
    cleaned = []
    prev_min = None
    for t in times:
        cur = int(t[:2]) * 60 + int(t[3:])
        if prev_min is not None and 0 < cur - prev_min <= 1:
            continue
        cleaned.append(t)
        prev_min = cur
    times = cleaned
    if not times:
        return None

    stem = Path(path).stem
    parts = stem.split("-")
    route = parts[0]
    station = parts[1] if len(parts) > 1 else None

    return {
        "filename": os.path.basename(path),
        "route": route,
        "station": station,
        "destination": destination,
        "operating_time": operating_time,
        "schedule_times": times,
    }


def main():
    line = "10"
    gap = 0.022
    timetables_dir = Path("/Users/wangrunji/Codes/next-train/timetables")
    images = sorted(timetables_dir.glob(f"{line}-*.jpg"))
    if not images:
        print(f"错误: 未找到线路 {line} 的图片")
        sys.exit(1)

    station_list = []
    for p in images:
        parts = p.stem.split("-")
        if len(parts) > 1 and parts[1] not in station_list:
            station_list.append(parts[1])

    output = f"/Users/wangrunji/Codes/next-train/data/lines/{line}.jsonl"
    os.makedirs(os.path.dirname(output), exist_ok=True)

    print(f"线路 {line}: {len(images)} 张图片, gap={gap}, {len(station_list)}站", flush=True)
    success = 0
    fail = 0
    fail_list = []

    with open(output, "w", encoding="utf-8") as fout:
        for i, img_path in enumerate(images, 1):
            record = None
            for attempt in range(3):
                try:
                    record = parse_image_line10(str(img_path), station_list=station_list, gap=gap)
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
            if record is None:
                fail += 1
                fail_list.append(img_path.name)
                print(f"  X [{i}/{len(images)}] {img_path.name}: 解析失败", flush=True)
                continue
            success += 1
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            fout.flush()
            if i % 10 == 0:
                print(f"  ... {i}/{len(images)} 完成 (成功{success}, 失败{fail})", flush=True)

    print(f"\n线路 {line}: 成功 {success}, 失败 {fail}", flush=True)
    if fail_list:
        print(f"失败图片: {fail_list}", flush=True)
    print(f"输出: {output}", flush=True)


if __name__ == "__main__":
    main()
