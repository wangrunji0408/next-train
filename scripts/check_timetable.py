#!/usr/bin/env python3
"""
检查时刻表数据的准确性
规则：
1. schedule_times 必须单调递增
2. 相邻时间间隔不能小于等于1分钟
3. 相邻时间间隔不能大于等于12分钟
"""

import json
from datetime import datetime, timedelta

def parse_time(time_str):
    """解析时间字符串为分钟数（从00:00开始计算）"""
    try:
        h, m = map(int, time_str.split(':'))
        return h * 60 + m
    except:
        return None

def check_schedule(station, route, destination, operating_time, schedule_times):
    """检查单个时刻表的schedule_times"""
    errors = []

    if not schedule_times or len(schedule_times) == 0:
        errors.append("时间列表为空")
        return errors

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
            # 检查间隔是否太小（<=1分钟）
            elif diff <= 1:
                errors.append(f"时间间隔过小({diff}分钟): {schedule_times[i-1]} -> {time_str}")
            # 检查间隔是否太大（>=12分钟）
            elif diff >= 12:
                errors.append(f"时间间隔过大({diff}分钟): {schedule_times[i-1]} -> {time_str}")

        prev_minutes = minutes

    return errors

def main():
    error_count = 0
    total_count = 0

    print("=" * 80)
    print("开始检查时刻表数据...")
    print("=" * 80)

    with open('data/timetable.jsonl', 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                total_count += 1

                station = data.get('station', '')
                route = data.get('route', '')
                destination = data.get('destination', '')
                operating_time = data.get('operating_time', '')
                schedule_times = data.get('schedule_times', [])

                errors = check_schedule(station, route, destination, operating_time, schedule_times)

                if errors:
                    error_count += 1
                    print(f"\n❌ 第{line_num}行发现问题:")
                    print(f"   站点: {station}")
                    print(f"   线路: {route}")
                    print(f"   方向: {destination}")
                    print(f"   运营时间: {operating_time}")
                    print(f"   时间数量: {len(schedule_times)}")
                    for error in errors:
                        print(f"   - {error}")

            except json.JSONDecodeError as e:
                error_count += 1
                print(f"\n❌ 第{line_num}行JSON解析错误: {e}")
            except Exception as e:
                error_count += 1
                print(f"\n❌ 第{line_num}行处理错误: {e}")

    print("\n" + "=" * 80)
    print(f"检查完成！")
    print(f"总计: {total_count} 条时刻表")
    print(f"错误: {error_count} 条")
    print(f"正确: {total_count - error_count} 条")
    print(f"准确率: {(total_count - error_count) / total_count * 100:.2f}%" if total_count > 0 else "N/A")
    print("=" * 80)

if __name__ == '__main__':
    main()
