#!/usr/bin/env python3
"""
检查时刻表数据的准确性（数据质量门禁）

规则：
1. 字段完整性：filename/route/station/destination/schedule_times 必填
2. 时间格式：HH:MM 合法，分钟 0-59
3. 单调递增：时间必须严格递增（自动处理跨午夜 23:59 -> 00:xx）
4. 间隔下限：相邻间隔 <=1 分钟视为 OCR 重复/误读（地铁实际间隔 >=2 分钟）
5. 间隔上限：时段感知（夜间收班车间隔天然偏大），超过阈值视为漏读

用法:
    .venv/bin/python scripts/check_timetable.py [-f data/timetable.jsonl] [-l 线路号] [-q] [-v]

参数:
    -f, --file       输入文件（默认 data/timetable.jsonl）
    -l, --line       只检查指定线路
    -q, --quiet      只输出汇总，不打印明细
    -v, --verbose    打印全部明细（默认只打印问题最严重的前 30 条）
"""

import json
import argparse
import sys
from collections import Counter, defaultdict

# 各线路正常发车间隔的 P99（来自数据统计），间隔超过 max(线路上限, 时段上限) 视为漏读
# 若线路不在表中，用默认值
ROUTE_MAX_INTERVAL = {
    # 线路: 正常最大发车间隔（分钟）
    "首都机场": 20,   # 机场线收班间隔可达 14-19 分钟
    "大兴机场": 20,
    "S1": 15,
    "11": 15,
    "燕房": 15,
    "14": 12,
    "16": 12,
    "17": 12,
    "13": 12,
    "房山": 12,
    "昌平": 12,
    "亦庄": 12,
    "19": 12,
    "15": 12,
    "8": 11,
    "6": 12,
    "4": 9,
    "1": 10,
    "5": 10,
    "2": 10,
    "3": 10,
    "7": 11,
    "9": 10,
    "10": 9,
    "12": 9,
    "八通": 10,
    "18": 12,
}
DEFAULT_MAX_INTERVAL = 12

# 夜间时段（22:00 - 5:59）允许更大的间隔
NIGHT_MAX_INTERVAL = 40


def parse_time(time_str):
    """解析时间字符串为分钟数（从00:00开始计算）"""
    try:
        h, m = map(int, time_str.split(':'))
        if not (0 <= h <= 24 and 0 <= m <= 59):
            return None
        if h == 24:
            h = 0
        return h * 60 + m
    except (ValueError, AttributeError):
        return None


def format_time(minutes):
    """分钟数转 HH:MM（支持超过24h，用于跨午夜显示）"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def check_schedule(route, station, destination, operating_time, schedule_times):
    """
    检查单个时刻表的 schedule_times
    返回 (errors, warnings) 列表
    """
    errors = []
    warnings = []

    if not schedule_times or len(schedule_times) == 0:
        return ["时间列表为空"], []

    # 线路的最大正常间隔
    max_interval = ROUTE_MAX_INTERVAL.get(route, DEFAULT_MAX_INTERVAL)

    prev_minutes = None
    for i, time_str in enumerate(schedule_times):
        minutes = parse_time(time_str)

        if minutes is None:
            errors.append(f"第{i+1}个时间格式错误: {time_str}")
            continue

        if prev_minutes is not None:
            diff = minutes - prev_minutes

            # 处理跨午夜的情况（例如 23:50 -> 00:10）
            if diff < 0:
                diff += 24 * 60

            # 检查是否单调递增
            if diff <= 0:
                errors.append(f"时间不是单调递增: {schedule_times[i-1]} -> {time_str}")

            # 检查间隔是否太小（OCR 重复/误读）
            elif diff <= 1:
                errors.append(f"时间间隔过小({diff}分钟,疑似误读): {schedule_times[i-1]} -> {time_str}")

            # 检查间隔是否太大（可能漏读）
            else:
                # 根据前一个时间判断是否夜间（22:00后或5:59前）
                hour = prev_minutes // 60
                is_night = hour >= 22 or hour <= 5
                limit = NIGHT_MAX_INTERVAL if is_night else max_interval

                if diff >= limit:
                    warnings.append(
                        f"时间间隔过大({diff}分钟,可能漏读): {schedule_times[i-1]} -> {time_str}"
                    )

        prev_minutes = minutes

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="检查时刻表数据准确性")
    parser.add_argument("-f", "--file", default="data/timetable.jsonl", help="输入文件")
    parser.add_argument("-l", "--line", type=str, help="只检查指定线路")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出汇总")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印全部明细")
    args = parser.parse_args()

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            lines = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        print(f"错误: 找不到文件 {args.file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: 文件 {args.file} 第{e.lineno}行 JSON 解析失败: {e.msg}")
        sys.exit(1)

    if args.line:
        lines = [d for d in lines if d.get('route') == args.line]
        print(f"（仅检查线路 {args.line}）")

    total = 0
    error_records = []
    err_types = Counter()
    route_stats = defaultdict(lambda: {'total': 0, 'errors': 0, 'warnings': 0})
    field_issues = []

    print("=" * 80)
    print(f"开始检查时刻表数据: {args.file}")
    print("=" * 80)

    for line_num, data in enumerate(lines, 1):
        total += 1
        route = data.get('route', '')
        station = data.get('station', '')
        destination = data.get('destination', '')
        operating_time = data.get('operating_time', '')
        schedule_times = data.get('schedule_times', [])
        filename = data.get('filename', '')

        route_stats[route]['total'] += 1
        all_errors = []
        all_warnings = []

        # 1. 字段完整性检查
        current_field_issues = []
        if not filename:
            current_field_issues.append("缺少filename")
        if not route:
            current_field_issues.append("缺少route")
        if not station:
            current_field_issues.append(f"{filename} 缺少station")
        if not destination:
            current_field_issues.append(f"{filename} 缺少destination")
        if not operating_time:
            current_field_issues.append(f"{filename} 缺少operating_time")
        for issue in current_field_issues:
            field_issues.append((line_num, issue))
            err_types["字段缺失"] += 1

        # 2. 时刻表检查
        errors, warnings = check_schedule(
            route, station, destination, operating_time, schedule_times
        )
        all_errors.extend(errors)
        all_warnings.extend(warnings)

        # 3. 小时覆盖检查（6:00-23:00 不应缺整小时）
        if schedule_times:
            hours_covered = set()
            for t in schedule_times:
                m = parse_time(t)
                if m is not None:
                    hours_covered.add(m // 60)
            # 检查 6-23 点是否覆盖（允许缺 1-2 个非高峰小时）
            missing = [h for h in range(6, 24) if h not in hours_covered]
            if len(missing) > 3:
                all_warnings.append(
                    f"缺失整小时: {missing[0]:02d}:00 ~ {missing[-1]:02d}:00 等{len(missing)}个时段"
                )

        # 汇总
        for e in all_errors:
            if e.startswith("时间不是单调递增"):
                err_types["非单调"] += 1
            elif e.startswith("时间间隔过小"):
                err_types["间隔过小(误读)"] += 1
            elif e.startswith("时间列表为空"):
                err_types["空列表"] += 1
            elif e.startswith("第") and "格式错误" in e:
                err_types["格式错误"] += 1
            else:
                err_types[e] += 1

        if all_errors or all_warnings or current_field_issues:
            route_stats[route]['errors'] += len(all_errors)
            route_stats[route]['warnings'] += len(all_warnings)
            if all_errors or current_field_issues:
                error_records.append({
                    'line_num': line_num, 'data': data,
                    'errors': all_errors, 'warnings': all_warnings
                })

    # 输出汇总
    print(f"\n总计: {total} 条时刻表")
    print(f"有问题的记录: {len(error_records)} 条")
    print(f"错误类型统计: {dict(err_types.most_common())}")

    if not args.quiet:
        # 按线路统计
        print("\n--- 按线路问题分布 ---")
        for route in sorted(route_stats, key=lambda r: -(route_stats[r]['errors'] + route_stats[r]['warnings'])):
            s = route_stats[route]
            if s['errors'] or s['warnings']:
                print(f"  {route:6s}: {s['total']:4d}条 | 错误{s['errors']:4d} 警告{s['warnings']:4d}")

        # 打印明细
        if error_records:
            print("\n--- 问题明细 ---")
            show = error_records if args.verbose else error_records[:30]
            for rec in show:
                d = rec['data']
                print(f"\n❌ 第{rec['line_num']}行: {d.get('filename')}")
                print(f"   {d.get('route')}线-{d.get('station')} 开往{d.get('destination')} ({d.get('operating_time')}) 时间数:{len(d.get('schedule_times', []))}")
                for e in rec['errors'][:10]:
                    print(f"   - [错误] {e}")
                for w in rec['warnings'][:5]:
                    print(f"   - [警告] {w}")
            if not args.verbose and len(error_records) > 30:
                print(f"\n... 还有 {len(error_records) - 30} 条问题记录（用 -v 查看全部）")

    error_count = sum(1 for r in error_records if r['errors'])
    print("\n" + "=" * 80)
    print(f"检查完成！总计 {total} 条，错误记录 {error_count} 条，警告记录 {len(error_records) - error_count} 条")
    if total > 0:
        print(f"正确率: {(total - error_count) / total * 100:.2f}%")
    print("=" * 80)
    return 0 if error_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
