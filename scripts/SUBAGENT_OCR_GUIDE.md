# 时刻表 OCR 解析 — subagent 工作指南

本指南用于指导处理时刻表图片的 OCR 解析任务。项目中 27 条线路已全部完成解析（正确率 100%），本指南用于**复现**、**更新**某条线路数据，或为新增线路开发解析器。

## 线路数据格式

输出到 `data/lines/{线路}.jsonl`，每条记录格式：
```json
{"filename": "亦庄-荣京东街-1.jpg", "route": "亦庄", "station": "荣京东街",
 "destination": "亦庄火车站", "operating_time": "工作日",
 "schedule_times": ["06:00", "06:05", ...]}
```

- `data/timetable.jsonl` = 所有线路合并后的最终数据
- 合并命令：`.venv/bin/python scripts/merge_lines.py -o data/timetable.jsonl`

## 脚本结构

### 核心库（scripts/ 根目录，勿修改）
| 脚本 | 用途 |
|------|------|
| `timetable_ocr.py` | 坐标法核心库：小时列检测、分钟合并、metadata 提取 |
| `parse_timetables.py` | 原有解析器（图片预处理 `convert_and_binarize_image` 等基础函数）|
| `parse_line_ocr.py` | 通用单线路解析入口（基于核心库，参数化 method/gap）|
| `check_timetable.py` | 质量检查（时段感知间隔、字段完整性、按线路过滤）|
| `merge_lines.py` | 合并 data/lines/*.jsonl 为最终 timetable.jsonl |
| `ocr_layout.py` | OCR 布局分析工具（查看图片文本结构）|

### 线路专用解析器（scripts/parsers/）

各线路已用专用解析器完成，命名风格 `parse_lines_<描述>.py` / `parse_line<数字>.py`：

| 脚本 | 线路 |
|------|------|
| `parse_lines_standard.py` | 1, 2, 5, 7, 9（北京地铁标准横排）|
| `parse_lines_jinggang.py` | 4, 14, 16, 17（京港竖条，分钟密集）|
| `parse_lines_split_hour.py` | 6, 8, 12, 13（小时列拆散）|
| `parse_lines_chinese.py` | 亦庄, 八通, 房山, 昌平, S1（中文线路名）|
| `parse_lines_airport.py` | 19, 首都机场, 燕房, 大兴机场, S1, 房山, 昌平 |
| `parse_lines.py` | 3, 15, 18（含 18 号线左右分栏）|
| `parse_line10.py` | 10（专门处理圆圈标记干扰）|
| `parse_line11.py` | 11 |

### 驱动脚本（scripts/parsers/）
| 脚本 | 用途 |
|------|------|
| `run_line.py` | 基于 parse_lines_standard 的批量驱动（3 worker）|
| `drive_mgh.py` | 京港线路批量驱动（每图子进程 + 断点续跑）|
| `parse_one_mgh.py` | drive_mgh 的单图 worker |
| `run_ocr_line.py` | 基于核心库的通用批量驱动 |
| `batch_parse.sh` | 分批驱动 parse_lines.py（规避 Vision 崩溃）|

### 后处理工具（scripts/parsers/）
| 脚本 | 用途 |
|------|------|
| `clean_1min_gaps.py` | 移除 1 分钟间隔的幻影分钟（真实间隔 >=2 分钟）|
| `fix_destinations.py` | 修复缺失/误识目的地 |
| `fix_operating_time.py` | 修复缺失运营时段 |
| `fixup_severe_gaps.py` | 串行重解析严重大间隔的记录 |

## 复现某条线路数据

以 1 号线为例（使用专用解析器）：
```bash
.venv/bin/python -c "
import sys, os
sys.path.insert(0, 'scripts/parsers'); sys.path.insert(0, 'scripts')
from parse_lines_standard import parse_image, STATIONS
import json
station_list = STATIONS.get('1', [])
records = []
for img in sorted(__import__('glob').glob('timetables/1-*.jpg')):
    r = parse_image(img, station_list=station_list)
    if r: records.append(r)
with open('data/lines/1.jsonl', 'w') as f:
    for r in records: f.write(json.dumps(r, ensure_ascii=False) + '\n')
"
```

或使用通用入口（质量可能低于专用解析器）：
```bash
.venv/bin/python scripts/parse_line_ocr.py -l 亦庄 -m rowlead -g 0.022
```

## 质量检查

```bash
# 检查单条线路
.venv/bin/python scripts/check_timetable.py -f data/lines/1.jsonl -v
# 检查最终数据
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl -q
```

检查规则：
- 时间格式、单调递增（自动处理跨午夜）
- 相邻间隔 <=1 分钟 = 误读（OCR 重复/错位）
- 相邻间隔 >= 线路上限 = 漏读（整小时丢失），夜间时段放宽阈值
- 字段完整性（station/destination/operating_time）

## 已总结的 OCR 解析难点

### 1. 二值化图丢失小时列（12-23点）
- 表现：大间隔漏读（如 08:57 -> 10:03 间隔66分钟）
- 原因：浅色小时字被二值化阈值过滤
- 解决：用灰度图检测小时列；`-m rowlead` 行首合并更稳健

### 2. OCR 拆散分钟数字（08 -> '0','8'）
- 表现：间隔过小（如 07:01 -> 07:02）或分钟乱序
- 解决：全单字符行两两配对；混合行按阅读顺序贪心配对（2字符token独立，1字符token与下一个配对）

### 3. 小时列位置不固定 / 小时被拆散
- 表现：小时 `10` 被读成 `1`,`0` 两个 token
- 解决：按小时列 x 边界剥离，或用"值匹配"（int(首token)==h）决定剥离几个 token

### 4. 目的地/运营时段提取失败
- 表现：destination=None 或 operating_time=None
- 原因：OCR 把"开往亦庄火车站方向"读成"往亦庄火车站方开向"（字符乱序）
- 解决：按线路站名列表模糊匹配（编辑距离+子序列）+ 英文 "To XXX" 兜底 + 文件名后缀启发式

### 5. 圆圈/带圈数字干扰（10号线关键）
- **带圈数字 ①-⑨ 是真实分钟的十位数字**（如 ④2 = 分钟 42），`is_num('④')=False` 会丢弃导致配对错位
- **圆圈符号 ◎○●◆□▲△** 是车次标记，其后数字应作为独立分钟
- **圆圈误读 `）()•`** 会打断数字配对
- 解决：`replace_circle_number` 把 ①-⑨ 转数字参与配对；追踪圆圈为 block 标记；灰度+二值化双 OCR 并集合并
- 参考：`parse_line10.py`

### 6. macOS Vision OCR 崩溃
- 并行 OCR（>3 worker）会导致 mediaanalysisd 服务崩溃
- 解决：固定 3 worker + 空结果重试；或每图子进程 + 断点续跑（见 drive_mgh.py）

### 7. 首末班车汇总卡片
- 检测到 2 条方向行（工作日+双休日叠在一张图）即判定为汇总卡片，应排除

## 新增线路的开发流程

1. 用 `ocr_layout.py` 查看 1-2 张图，理解布局：
   ```bash
   .venv/bin/python scripts/ocr_layout.py timetables/新线-站-1.jpg
   ```
2. 用通用入口跑基线：`parse_line_ocr.py -l 新线 -m auto`
3. 若质量 <85%，参考最接近的专用解析器写专用解析器，放到 `scripts/parsers/`
4. 用 check_timetable.py 验证，迭代到 >85%

## 注意

- 所有 Python 脚本用 `.venv/bin/python` 运行（项目虚拟环境）
- 不要修改 `scripts/timetable_ocr.py`、`scripts/parse_timetables.py` 等共享库
- 各线路解析器互不冲突，可并行开发
- 新增/修改解析器后，记得用 `merge_lines.py` 重新合并生成最终数据
