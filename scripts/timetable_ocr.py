#!/usr/bin/env python3
"""
稳健的时刻表 OCR 核心库（坐标法）

解决的问题（相比 parse_timetables.py 的字符串拼接法）：
1. 二值化图丢失小时列（12-23 点浅色小时）→ 用灰度图检测小时列 + 插值补齐
2. OCR 把两位分钟拆成单字符 token → 按行内 x 坐标聚类合并
3. 不同线路布局/间距不同 → 提供可配置参数 + 自动检测

核心流程：
1. 灰度图 OCR → 检测小时列（多策略），得到 {hour: y}
2. 二值化图 OCR → 提取分钟（行内 x 聚类合并）
3. 按 y 坐标对齐，生成 {hour: [minutes]}

线路配置参数：
- hour_x_range: 小时列 x 搜索范围
- minute_gap: 分钟合并间距（仅手动模式用）
- 自动模式：根据 token 长度/间距自适应
"""

import os
import re
import sys
from typing import List, Tuple, Dict, Optional

import numpy as np
from PIL import Image
from ocrmac import ocrmac

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def is_num(t: str) -> bool:
    return bool(re.match(r'^[0-9]+$', t))


def group_rows(anns: List[Tuple], eps: float = 0.02) -> List[Tuple[float, List]]:
    """按 y 聚类成行。返回 [(y_avg, [annotations])]"""
    if not anns:
        return []
    anns = sorted(anns, key=lambda a: -a[2][1])
    rows = []
    cur = [anns[0]]
    cur_y = anns[0][2][1]
    for a in anns[1:]:
        if abs(a[2][1] - cur_y) <= eps:
            cur.append(a)
        else:
            rows.append((cur_y, cur))
            cur = [a]
            cur_y = a[2][1]
    if cur:
        rows.append((cur_y, cur))
    return rows


def row_digits(rows, ymin=0.10, ymax=0.85) -> Dict[float, List[Tuple[str, float]]]:
    """从行分组提取 {y: [(text, x)]}，只保留数字 token"""
    out = {}
    for y, tokens in rows:
        if not (ymin < y < ymax):
            continue
        nums = []
        for tok in tokens:
            if len(tok) >= 2 and is_num(tok[0]):
                nums.append((tok[0], tok[2][0]))
        if nums:
            nums.sort(key=lambda v: v[1])
            out[y] = nums
    return out


def merge_tokens(tokens: List[Tuple[str, float]], gap: float) -> List[Tuple[str, float]]:
    """tokens: [(text, x)] 按x排序。合并 x 距离 < gap 的相邻 token。返回 [(merged, x_start)]"""
    result = []
    for text, x in tokens:
        if result and x - result[-1][1] < gap:
            pt, px = result[-1]
            result[-1] = (pt + text, px)
        else:
            result.append((text, x))
    return result


def smart_merge_minutes(tokens: List[Tuple[str, float]], gap: float) -> List[Tuple[str, float]]:
    """
    智能分钟合并。
    - 若所有 token 均为单字符且数量为偶数：两两合并（适合京港密排格式）
    - 否则：按 x 距离合并
    """
    if not tokens:
        return []
    if all(len(t) == 1 for t, _ in tokens) and len(tokens) >= 2:
        # 两两合并
        result = []
        for i in range(0, len(tokens) - 1, 2):
            result.append((tokens[i][0] + tokens[i+1][0], tokens[i][1]))
        if len(tokens) % 2 == 1:
            result.append(tokens[-1])
        return result
    return merge_tokens(tokens, gap)


# ---------------------------------------------------------------------------
# 小时列检测
# ---------------------------------------------------------------------------

def detect_hour_column_scan(anns, debug=False, x_min=0.02, x_max=0.50):
    """
    策略1：扫描 x 位置，找"形成 5-24 连续递增序列"的最佳列。
    适合小时列 x 位置固定的线路（亦庄、10 号线等）。
    返回 {hour: y} 或 None
    """
    nums = []
    for t, c, b in anns:
        if is_num(t) and 0.05 < b[1] < 0.90:
            try:
                v = int(t)
            except ValueError:
                continue
            if 1 <= v <= 24:
                nums.append((t, b[0], b[1], v))
    if len(nums) < 20:
        return None

    best = None
    best_score = 0
    xs = sorted(set(round(n[1], 2) for n in nums))
    for x0 in xs:
        near = [n for n in nums if abs(n[1] - x0) < 0.015]
        hours = sorted(set(n[3] for n in near))
        # 覆盖的 hour 范围
        if not hours:
            continue
        span = max(hours) - min(hours)
        n_hours = len(hours)
        # 均匀性：y 与 hour 的线性拟合残差（小时列 y 应均匀分布）
        ys = []
        for t, x, y, v in near:
            ys.append(y)
        if len(ys) >= 3:
            h_vals = [v for _, _, _, v in near]
            ys_ = [y for _, _, y, _ in near]
            # 简单线性拟合 y = a + b*hour
            n = len(h_vals)
            sum_h = sum(h_vals); sum_y = sum(ys_)
            sum_h2 = sum(h*h for h in h_vals); sum_hy = sum(h*y for h, y in zip(h_vals, ys_))
            denom = n * sum_h2 - sum_h * sum_h
            if denom != 0:
                b_ = (n * sum_hy - sum_h * sum_y) / denom
                a_ = (sum_y - b_ * sum_h) / n
                # 计算残差
                resid = sum((y - (a_ + b_*h))**2 for h, y in zip(h_vals, ys_))
                avg_gap = abs(b_)  # 每小时的 y 间距
            else:
                resid = 1e9
                avg_gap = 0
        else:
            resid = 1e9
            avg_gap = 0
        # 评分：小时覆盖范围大 + 数量多 + 残差小 + 间距合理(0.01-0.06)
        good_gap = 0.01 < avg_gap < 0.06 if avg_gap else False
        score = span * 10 + n_hours * 5 - resid * 1000
        if good_gap:
            score += 50
        if score > best_score:
            best_score = score
            best = (x0, near, span, n_hours, resid, avg_gap)

    if best is None:
        return None
    x0, near, span, n_hours, resid, avg_gap = best
    if n_hours < 5:
        return None
    if debug:
        print(f"  小时列 x≈{x0:.3f}, 覆盖{span}小时({n_hours}个), 间距{avg_gap:.4f}")

    col = {}
    for t, x, y, v in near:
        col[v] = y
    # 插值补齐
    hours = sorted(col)
    result = dict(col)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i+1]
        if h2 - h1 > 1:
            y1, y2 = col[h1], col[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result


def detect_hour_column_rowlead(anns, debug=False, hour_gap=0.030):
    """
    策略2：行首合并检测小时列（适合小时被 OCR 拆散成 '1','0' 的线路）。
    每行取合并后第一个数字，x 聚类，插值补齐。
    返回 {hour: y} 或 None
    """
    rows = group_rows(anns)
    candidates = []  # (y, hour, x)
    for y, tokens in rows:
        if not (0.10 < y < 0.90):
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
        if 5 <= hv <= 24 and 0.02 < x < 0.50:
            candidates.append((y, hv, x))

    if len(candidates) < 6:
        return None

    xs = sorted(c[2] for c in candidates)
    best_center, best_count = None, 0
    for cx in xs:
        count = sum(1 for _, _, x in candidates if abs(x - cx) < 0.015)
        if count > best_count:
            best_count = count
            best_center = cx
    if best_center is None or best_count < 6:
        return None

    col = {}
    for y, hv, x in candidates:
        if abs(x - best_center) < 0.015:
            col[hv] = y
    if debug:
        print(f"  小时列x={best_center:.3f} 检测到{len(col)}个: {sorted(col)}")
    if len(col) < 5:
        return None

    hours = sorted(col)
    result = dict(col)
    for i in range(len(hours) - 1):
        h1, h2 = hours[i], hours[i+1]
        if h2 - h1 > 1:
            y1, y2 = col[h1], col[h2]
            for h in range(h1 + 1, h2):
                result[h] = y1 + (y2 - y1) * (h - h1) / (h2 - h1)
    return result


def detect_hour_column(anns, debug=False, method="auto"):
    """综合小时列检测。method: auto / scan / rowlead"""
    if method == "scan":
        return detect_hour_column_scan(anns, debug)
    if method == "rowlead":
        return detect_hour_column_rowlead(anns, debug)
    # auto: 先 scan 后 rowlead
    r = detect_hour_column_scan(anns, debug)
    if r is not None:
        return r
    return detect_hour_column_rowlead(anns, debug)


# ---------------------------------------------------------------------------
# 时刻表提取主流程
# ---------------------------------------------------------------------------

# 目的地/运营时段正则（从灰度图文本提取）
DEST_PATTERNS = [
    r"[开牙去][往住注]?(.+?)站?(?:方向|To)",
    r"[往住注](.+?)站?(?:方向|开向|向)",
    r"(?:方向|To)\s*(.+)",
]
OP_TIME_KEYWORDS = [
    ("工作日", ["作日", "Weekdays"]),
    ("双休日", ["双休日", "Weekends"]),
    ("平日", ["平日", "Ordinary"]),
    ("星期五", ["星期五", "周五", "Friday"]),
]


def _substr_match(text, target):
    """
    宽松子串匹配：target 的字符按顺序出现在 text 中（允许中间夹杂其它字符）。
    如 text="双s休日" 能匹配 "双休日"。
    """
    it = iter(text)
    return all(c in it for c in target)


def extract_metadata(gray_anns, station_list=None):
    """
    从灰度图 OCR annotations 提取 destination 和 operating_time。
    OCR 常把字符顺序打乱（如"开往"读成"往...开"），因此采用宽松匹配。

    目的地提取策略：
    1. 若提供 station_list：在方向行文本中找出现的站点名（字符连续，最可靠）
    2. 否则：正则提取

    返回 (destination, operating_time)
    """
    # 按行重组文本（行内按 x 排序）
    rows = group_rows(gray_anns)
    lines = []
    for y, tokens in rows:
        texts = [tok[0] for tok in tokens if len(tok) >= 2]
        lines.append("".join(texts))

    destination = None
    operating_time = None

    # 找出包含方向标记的行
    for line_text in lines:
        if not line_text:
            continue

        # 运营时段（整行搜索，宽松匹配允许字符穿插）
        if operating_time is None:
            for label, keywords in OP_TIME_KEYWORDS:
                if any(k in line_text for k in keywords) or \
                   any(_substr_match(line_text, k) for k in keywords):
                    operating_time = label
                    break

        # 目的地
        if destination is None:
            is_dir_line = any(k in line_text for k in ["方向", "开向", "To", "开往", "往", "去往"])
            if not is_dir_line:
                continue
            if station_list:
                # 在方向行中找连续出现的站点名
                for st in station_list:
                    if st and st in line_text:
                        destination = st
                        break
                if destination is None:
                    # 站点名可能被拆分，尝试去掉"站"后再匹配
                    clean = line_text.replace("站", "")
                    for st in station_list:
                        if st and st in clean:
                            destination = st
                            break
            else:
                cand = extract_destination_candidate(line_text)
                if cand and not cand.isdigit() and len(cand) <= 12:
                    destination = cand
            if destination:
                break

    return destination, operating_time


def extract_destination_candidate(line_text):
    """
    从单行文本提取目的地候选（含方向标记）。
    返回字符串或 None
    """
    # 英文 To XXX Station
    m = re.search(r'To\s+([A-Za-z]{2,40}?)\s*(?:Station|Railway|$)', line_text)
    if m:
        return m.group(1)

    # 中文：找"方向/开向/To"作为结束标记，向前取中文片段
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
    return None


def extract_schedule(path, debug=False, method="auto",
                     hour_x_range=(0.02, 0.50), minute_gap=0.022):
    """
    从单张时刻表图片提取 {hour: [minutes]}。
    """
    # 用 convert_and_binarize_image 相同的预处理逻辑（内联以避免循环依赖）
    from parse_timetables import convert_and_binarize_image

    try:
        pairs = convert_and_binarize_image(path)
        gray, binary = pairs[0]
    except Exception:
        return None

    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    hour_map = detect_hour_column(anns_g, debug=debug, method=method)
    if not hour_map:
        return None

    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    result = {h: [] for h in hour_map}

    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (0.10 < y < 0.85):
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

        # 跳过行首的小时 token：x 最小且值接近该小时
        # （二值化图可能把小时拆成多个单字符，需全部跳过）
        merged = smart_merge_minutes(nums, minute_gap)
        # 过滤掉属于小时列的 token（x 最小，且合并后值在 0-24 之间且是行首）
        minutes_tokens = []
        for i, (text, x) in enumerate(merged):
            if i == 0:
                continue  # 行首第一个通常是小时
            try:
                m = int(text)
                if 0 <= m <= 59:
                    minutes_tokens.append(m)
            except ValueError:
                pass
        for m in minutes_tokens:
            result[best_h].append(m)

    final = {}
    for h, mins in result.items():
        mins = sorted(set(mins))
        if mins:
            final[h] = mins
    return final


def parse_image_full(path, debug=False, method="auto", minute_gap=0.022, station_list=None):
    """
    完整解析单张图片，返回完整记录 dict（含 destination/operating_time）。
    失败返回 None。
    """
    from parse_timetables import convert_and_binarize_image
    from pathlib import Path

    try:
        pairs = convert_and_binarize_image(path)
        gray, binary = pairs[0]
    except Exception:
        return None

    anns_g = ocrmac.OCR(gray, framework="livetext").recognize()
    destination, operating_time = extract_metadata(anns_g, station_list=station_list)

    hour_map = detect_hour_column(anns_g, debug=debug, method=method)
    if not hour_map:
        return None

    anns_b = ocrmac.OCR(binary, framework="livetext").recognize()
    result = {h: [] for h in hour_map}
    rows_b = group_rows(anns_b)
    for y, tokens in rows_b:
        if not (0.10 < y < 0.85):
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
        merged = smart_merge_minutes(nums[1:], minute_gap)
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


if __name__ == "__main__":
    for f in sys.argv[1:] or ['timetables/亦庄-肖村-3.jpg']:
        print("=" * 50)
        print(os.path.basename(f))
        r = extract_schedule(f, debug=True)
        if r is None:
            print("  解析失败")
            continue
        for h in sorted(r):
            mins = r[h]
            issues = [mins[i+1]-mins[i] for i in range(len(mins)-1)
                      if mins[i+1]-mins[i] <= 1 or mins[i+1]-mins[i] >= 12]
            flag = " <--异常" if issues else ""
            print(f"  {h:02d}:xx ({len(mins)}): {mins}{flag}")
