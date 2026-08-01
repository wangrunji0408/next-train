#!/usr/bin/env python3
"""
Dedicated parser for Beijing Metro lines with split-digit hour columns (8, 13).

Strategy:
1. Detect hour column by scanning candidate x positions; for each x, merge digit
   tokens by row (y) into hour values, then score by count + linear-fit quality.
2. For each row, strip the hour tokens (x within the detected column window),
   then smart-merge the remaining tokens into minutes.

Usage: .venv/bin/python /tmp/run_ocr_dedicated.py <line> [gap]
Output: data/lines/<line>.jsonl
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

from parse_timetables import convert_and_binarize_image
from ocrmac import ocrmac
from timetable_ocr import group_rows, is_num, smart_merge_minutes, extract_metadata

# Some line 8 images are truncated downloads; allow PIL to load them anyway.
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Terminal stations -> pinyin (from English text in the timetable header).
# Used to disambiguate destinations when OCR misreads the Chinese characters.
PINYIN_MAP = {
    "朱辛庄": "zhuxinzhuang",
    "瀛海": "yinghai",
    "金安桥": "jinanqiao",
    "潞城": "lucheng",
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
    "丰台站": "fengtaizhan",
    "劲松": "jingsong",
    "草桥": "caoqiao",
    "国贸": "guomao",
    "六里桥": "liuliqiao",
    "牡丹园": "mudanyuan",
    "角门西": "jiaomenxi",
    "亮马桥": "liangmaqiao",
    "丰台站": "fengtai",
    "潞阳": "luyang",
}


def match_dest_by_pinyin(line_text, station_list):
    """If the direction line contains English pinyin, map it to a station name.
    Picks the LONGEST matching pinyin to be specific."""
    import re as _re
    tl = line_text.lower()
    best, best_len = None, 0
    for st in station_list:
        py = PINYIN_MAP.get(st)
        if py and py in tl and len(py) > best_len:
            best, best_len = st, len(py)
    if best:
        return best
    # fallback: also match standalone pinyin tokens
    eng_tokens = _re.findall(r"[A-Za-z]{2,}", line_text)
    for tok in eng_tokens:
        t = tok.lower()
        for st in station_list:
            py = PINYIN_MAP.get(st)
            if py and (py in t or t in py):
                return st
    return None


def fuzzy_destination(anns_g, station_list):
    """Try harder to find the destination station by fuzzy matching the
    direction line against the known station list."""
    if not station_list:
        return None
    import difflib
    import re as _re
    rows = group_rows(anns_g)
    lines = []
    for y, tokens in rows:
        texts = [tok[0] for tok in tokens if len(tok) >= 2]
        lines.append("".join(texts))
    dir_lines = [l for l in lines if any(k in l for k in ["方向", "开向", "To", "开往", "往", "去往"])]
    for line_text in dir_lines:
        # 0. pinyin match (English text in header disambiguates misread Chinese)
        d = match_dest_by_pinyin(line_text, station_list)
        if d:
            return d
        # 1. exact substring
        for st in station_list:
            if st and st in line_text:
                return st
        # 2. extract Chinese destination fragment from direction line.
        #    Preferred: "往<中文站名>站" (the station right after 往/开往/去).
        cand = None
        m = _re.search(r"[往住注开牙去]([一-鿿]{2,10}?)站", line_text)
        if m:
            cand = m.group(1)
        if not cand:
            for end_marker in ["方向", "开向"]:
                idx = line_text.find(end_marker)
                if idx < 0:
                    continue
                prefix = line_text[:idx]
                m2 = _re.search(r"[一-鿿]{2,12}$", prefix)
                if m2:
                    cand = _re.sub(r"站$", "", m2.group(0))
                    break
        if cand:
            cand = cand.lstrip("往住注开牙去")
            best, best_score = None, 0
            for st in station_list:
                if not st:
                    continue
                ratio = difflib.SequenceMatcher(None, cand, st).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best = st
            if best_score >= 0.32:
                return best
            # ordered-subsequence fallback: station chars appear in order
            # (handles badly misread chars like 朵车庄 vs 朱辛庄)
            for st in station_list:
                if not st:
                    continue
                it = iter(cand)
                if all(c in it for c in st):
                    return st
        # 3. best difflib ratio against full line (2+ char match)
        best, best_score = None, 0
        for st in station_list:
            if not st:
                continue
            ratio = difflib.SequenceMatcher(None, st, line_text).ratio()
            if ratio > best_score:
                best_score = ratio
                best = st
        if best_score >= 0.4:
            return best
    return None


def merge_minutes_robust(tokens):
    """Merge minute digit tokens.

    - Tokens of length >= 2 are kept as-is (already merged minutes).
    - Runs of single-char tokens are paired 2-by-2 (OCR splits a minute like
      "37" into "3","7"). An odd leftover single char is dropped (garbage).
    """
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        text, x = tokens[i]
        if len(text) >= 2:
            result.append((text, x))
            i += 1
        else:
            # collect run of single chars
            j = i
            while j < n and len(tokens[j][0]) == 1:
                j += 1
            run = tokens[i:j]
            k = 0
            while k + 1 < len(run):
                result.append((run[k][0] + run[k + 1][0], run[k][1]))
                k += 2
            # odd leftover single char -> drop (would be a bogus minute)
            i = j
    return result


def detect_hour_column_split(anns, debug=False):
    """Detect {hour: y} robust to split digit hours (e.g. '1','2' for 12)."""
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
    # scan candidate hour-column x positions
    for i in range(80, 260, 1):
        x0 = i / 1000.0
        window = 0.015
        near = [n for n in nums if abs(n[1] - x0) < window]
        if len(near) < 8:
            continue
        # merge tokens by y within window -> hour values
        by_y = defaultdict(list)
        for t, x, y, v in near:
            by_y[round(y, 3)].append((t, x, y, v))
        merged = []  # (y, hour)
        for y, items in by_y.items():
            if y < 0.15:
                continue  # skip footer
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
        # linear fit residual: y = a + b*h (exclude hour 0 which breaks the line)
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
        # score: many hours, monotonic-ish (b < 0 since y decreases as hour increases), low residual
        n_hours = len(merged)
        h_range = max(hs) - min(hs)
        # residual scaled to number of fit points
        resid = resid / max(1, len(fit))
        # monotonic check: hours should be increasing with decreasing y
        sorted_merged = sorted(merged, key=lambda m: m[0], reverse=True)  # top y first
        mono_ok = all(sorted_merged[i][1] < sorted_merged[i+1][1] or
                      (sorted_merged[i][1] == 23 and sorted_merged[i+1][1] == 0)
                      for i in range(len(sorted_merged)-1))
        score = n_hours * 10 + h_range - resid * 5000 + (50 if mono_ok else 0) + (50 if b_ < 0 else 0)
        if score > best_score:
            best_score = score
            best = (x0, {h: y for y, h in merged}, resid, n_hours, b_, mono_ok)

    if best is None or best[3] < 8:
        return None
    x0, col, resid, n_hours, b_, mono_ok = best
    if debug:
        print(f"  hour col x≈{x0:.3f}, {n_hours} hours, resid={resid:.4f}, b={b_:.3f}, mono={mono_ok}")
    return col


def parse_image_dedicated(path, gap=0.022, station_list=None):
    """Parse a single image with the dedicated split-digit hour strategy."""
    try:
        pairs = convert_and_binarize_image(path)
        gray, binary = pairs[0]
    except Exception:
        return None

    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination, operating_time = extract_metadata(anns_g, station_list=station_list)
    # Try to correct destination via fuzzy match against known stations
    if not destination or (station_list and destination not in station_list):
        fd = fuzzy_destination(anns_g, station_list)
        if fd:
            destination = fd

    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    # Prefer the hour map with MORE hours detected (binary usually has hours 7/8/9
    # that gray misses)
    hm_g = detect_hour_column_split(anns_g, debug=False)
    hm_b = detect_hour_column_split(anns_b, debug=False)
    if hm_g and hm_b:
        hour_map = hm_b if len(hm_b) > len(hm_g) else hm_g
        anns_m = anns_b
    elif hm_b:
        hour_map = hm_b
        anns_m = anns_b
    elif hm_g:
        hour_map = hm_g
        anns_m = anns_b
    else:
        return None

    # Build result rows
    result = {h: [] for h in hour_map}
    rows = group_rows(anns_m)
    for y, tokens in rows:
        if not (0.10 < y < 0.85):
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2 and is_num(tok[0]):
                nums.append((tok[0], tok[2][0]))
        if not nums:
            continue
        nums.sort(key=lambda v: v[1])
        # find nearest hour
        best_h, best_d = None, 1e9
        for h, hy in hour_map.items():
            d = abs(y - hy)
            if d < best_d:
                best_d, best_h = d, h
        if best_h is None or best_d > 0.025:
            continue

        # Strip hour FIRST via value matching on raw (pre-merge) tokens.
        # Split hours: '1','2' -> 12, '1','9' -> 19; '00' -> 0.
        tokens2 = list(nums)
        if tokens2:
            # skip leading hour token(s): the value must equal best_h
            # Handle hour "00" (best_h == 0): need to skip TWO '0' tokens.
            if best_h == 0 and len(tokens2) >= 2 and tokens2[0][0] == "0" and tokens2[1][0] == "0":
                tokens2 = tokens2[2:]
            elif int(tokens2[0][0]) == best_h:
                tokens2 = tokens2[1:]
            elif len(tokens2) >= 2:
                try:
                    if int(tokens2[0][0] + tokens2[1][0]) == best_h:
                        tokens2 = tokens2[2:]
                except ValueError:
                    pass

        # Merge remaining as minutes. Robust merge: 2-char tokens kept as-is;
        # runs of single-char digits paired 2-by-2 (handles OCR splitting a
        # minute into two single-char tokens).
        merged = merge_minutes_robust(tokens2)
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
    # Remove spurious 1-minute-apart times (real metro headways are >= 2 min;
    # these are OCR misreads). Keep the first of each such pair.
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
    line = sys.argv[1]
    gap = float(sys.argv[2]) if len(sys.argv) > 2 else 0.022

    timetables_dir = Path("/Users/wangrunji/Codes/next-train/timetables")
    images = sorted(timetables_dir.glob(f"{line}-*.jpg"))
    if not images:
        images = sorted([p for p in timetables_dir.glob("*.jpg") if p.stem.split("-")[0] == line])
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
                    record = parse_image_dedicated(str(img_path), gap=gap, station_list=station_list)
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
