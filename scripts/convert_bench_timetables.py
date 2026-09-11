#!/usr/bin/env python3
"""把 timetable-bench 的解析结果转换为本项目 data/timetable.jsonl 格式。

来源: ../timetable-bench/output/timetables.jsonl

字段映射:
    id/source            -> filename   (取 source 的文件名，去掉 #panel 后缀)
    line                 -> route
    station              -> station
    direction            -> destination
    service              -> operating_time
    times[{hour,minute}] -> schedule_times ["HH:MM", ...]

service -> operating_time:
    weekday           -> 工作日   (大兴机场线图面写的是"平日")
    weekend           -> 双休日
    mon-thu_weekend   -> 平日     (首都机场线)
    friday            -> 星期五
    key_guaranteed    -> 星期五   (大兴机场线"重点保障(星期五及重点保障时期)")

额外处理:
  * 一张图两个面板的记录 (id 带 #0/#1): 18 号线是"工作日/双休日"两块表，各自成条；
    大兴机场-大兴新城-2 的两块表同为平日，合并去重。
  * bench 在终点站会套用"后缀默认方向/时段"（-1=往该站、-2=往对端），与图面
    "开往X站方向 + 工作日/双休日"不符。CORRECTIONS 按图面逐张修正（已人工核对图片）。
  * schedule_times 为空的记录直接丢弃（图面解析失败，保留会在前端遮住正常时刻表）。

用法:
    .venv/bin/python scripts/convert_bench_timetables.py \
        -i ../timetable-bench/output/timetables.jsonl -o data/timetable.jsonl
"""
import argparse
import json
import os
import sys
from collections import defaultdict

# filename -> (destination, operating_time)，按图片上"开往X站方向 / 工作日|双休日"人工核对
CORRECTIONS = {
    # 6 号线终点站
    "6-金安桥-1.jpg": ("潞阳", "工作日"),
    "6-金安桥-2.jpg": ("潞阳", "双休日"),
    "6-潞阳-1.jpg": ("金安桥", "工作日"),
    "6-潞阳-2.jpg": ("金安桥", "双休日"),
    # 7 号线终点站
    "7-北京西站-1.jpg": ("环球度假区", "工作日"),
    "7-北京西站-2.jpg": ("环球度假区", "双休日"),
    "7-环球度假区-1.jpg": ("北京西站", "工作日"),
    "7-环球度假区-2.jpg": ("北京西站", "双休日"),
    # 8 号线终点站
    "8-朱辛庄-1.jpg": ("瀛海", "工作日"),
    "8-朱辛庄-2.jpg": ("瀛海", "双休日"),
    "8-瀛海-1.jpg": ("朱辛庄", "工作日"),
    "8-瀛海-2.jpg": ("朱辛庄", "双休日"),
    # 9 号线终点站（工作日贯通房山线至阎村东）
    "9-国家图书馆-1.jpg": ("郭公庄、阎村东", "工作日"),
    "9-国家图书馆-2.jpg": ("郭公庄、阎村东", "双休日"),
    "9-郭公庄-1.jpg": ("国家图书馆", "工作日"),
    "9-郭公庄-2.jpg": ("国家图书馆", "双休日"),
    # 14 号线终点站
    "14-善各庄-1.jpg": ("张郭庄", "工作日"),
    "14-善各庄-2.jpg": ("张郭庄", "双休日"),
    "14-张郭庄-1.jpg": ("善各庄", "工作日"),
    "14-张郭庄-2.jpg": ("善各庄", "双休日"),
    # 15 号线终点站
    "15-俸伯-1.jpg": ("清华东路西口", "工作日"),
    "15-俸伯-2.jpg": ("清华东路西口", "双休日"),
    "15-清华东路西口-1.jpg": ("俸伯", "工作日"),
    "15-清华东路西口-2.jpg": ("俸伯", "双休日"),
    # 13 号线 西二旗/清河站 的 -1/-2 方向约定与其它站相反（bench 只对清河站套用了）
    "13-西二旗-1.jpg": ("西直门", "工作日"),
    "13-西二旗-2.jpg": ("东直门", "工作日"),
    "13-西二旗-3.jpg": ("西直门", "双休日"),
    "13-西二旗-4.jpg": ("东直门", "双休日"),
}


def map_service(line, service):
    if service == "weekday":
        return "平日" if line == "大兴机场" else "工作日"
    if service == "weekend":
        return "双休日"
    if service == "mon-thu_weekend":
        return "平日"
    if service in ("friday", "key_guaranteed"):
        return "星期五"
    if service == "sunday_extension":
        return "平日"
    raise ValueError(f"未知 service: {service!r} (line={line})")


def fmt_time(t):
    hour, minute = t["hour"], t["minute"]
    return f"{hour:02d}:{minute:02d}"


def to_minutes(t):
    hour, minute = map(int, t.split(":"))
    return hour * 60 + minute


def drop_phantom_minutes(times):
    """移除造成 1 分钟间隔的 OCR 幻影分钟（真实发车间隔 >= 2 分钟）。

    bench 的幻影分钟总是一个真实分钟的前一位（如真值 03/12/15 被读成 02,03 /
    11,12 / 14,15）。规则：
      * 连续 >=3 个分钟：保留首尾，删除中间（如 41,42,43 -> 41,43）；
      * 连续 2 个分钟 (a, a+1)：保留靠后的 a+1。
    核对过 6-呼家楼-2 的 8 点行等图面，清理后与图面完全一致。
    """
    mins = [to_minutes(t) for t in times]
    n = len(mins)
    keep = [True] * n
    i = 0
    while i < n - 1:
        if mins[i + 1] - mins[i] != 1:
            i += 1
            continue
        start = i
        while i + 1 < n and mins[i + 1] - mins[i] == 1:
            i += 1
        end = i
        if end - start + 1 >= 3:
            for k in range(start + 1, end):
                keep[k] = False
        else:
            keep[start] = False
        i += 1
    return [t for k, t in enumerate(times) if keep[k]]


def main():
    parser = argparse.ArgumentParser(description="转换 timetable-bench 解析结果")
    parser.add_argument("-i", "--input", default="../timetable-bench/output/timetables.jsonl")
    parser.add_argument("-o", "--output", default="data/timetable.jsonl")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"错误: 找不到输入文件 {args.input}")

    # (filename, destination, operating_time) -> 记录（用于合并同图多面板）
    merged = {}
    order = []
    dropped_empty = []
    n_in = 0

    with open(args.input, encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            n_in += 1

            filename = os.path.basename(o["source"])
            times = sorted({fmt_time(t) for t in o.get("times") or []})

            if filename in CORRECTIONS:
                destination, operating_time = CORRECTIONS[filename]
            else:
                destination = o["direction"]
                operating_time = map_service(o["line"], o["service"])

            if not times:
                dropped_empty.append(filename)
                continue

            key = (filename, destination, operating_time)
            if key in merged:
                # 同图的另一面板：并入（去重后仍保持递增）
                prev = merged[key]["schedule_times"]
                merged[key]["schedule_times"] = sorted(set(prev) | set(times))
            else:
                merged[key] = {
                    "filename": filename,
                    "route": o["line"],
                    "station": o["station"],
                    "destination": destination,
                    "operating_time": operating_time,
                    "schedule_times": times,
                }
                order.append(key)

    records = [merged[k] for k in order]

    removed = 0
    for r in records:
        before = len(r["schedule_times"])
        r["schedule_times"] = drop_phantom_minutes(r["schedule_times"])
        removed += before - len(r["schedule_times"])

    def safe(v):
        return v if isinstance(v, str) else ""

    records.sort(key=lambda r: (
        safe(r["route"]), safe(r["station"]),
        safe(r["destination"]), safe(r["operating_time"]),
    ))

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fout:
        for r in records:
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_route = defaultdict(int)
    for r in records:
        by_route[r["route"]] += 1
    print(f"输入 {n_in} 条 -> 输出 {len(records)} 条 ({len(by_route)} 条线路)")
    print(f"剔除 1 分钟幻影分钟: {removed} 个")
    print(f"按图面修正方向/时段的记录: {len(CORRECTIONS)} 张图片")
    if dropped_empty:
        print("丢弃空时刻表记录:")
        for fn in dropped_empty:
            print(f"  - {fn}")


if __name__ == "__main__":
    main()
