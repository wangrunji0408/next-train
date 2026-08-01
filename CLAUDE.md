# Next Train App - 下班车时间查询

## 项目概述
这是一个基于Web的地铁下班车时间查询应用。

## 核心文件结构

### 前端主要文件
- `index.html` - 主页面，包含UI布局和样式
- `app.js` - 主应用逻辑（NextTrainApp类）
- `i18n.js` - 国际化支持（I18n类）

### 数据文件
- `data/routes.json` - 地铁线路数据和站点坐标
- `data/timetable.jsonl` - 时刻表数据（所有线路合并后的最终数据）
- `timetables/` - 各线路时刻表原始图片（`.jpg`/`.png`，命名 `线路-站名-编号`）

### 脚本目录（scripts/）
- `scripts/parse_timetables.py` - 通用解析器（基线，含图片预处理函数）
- `scripts/timetable_ocr.py` - 坐标法核心库（小时列检测、分钟合并、metadata提取）
- `scripts/parse_line_ocr.py` - 通用单线路解析入口
- `scripts/check_timetable.py` - 质量检查（时段感知间隔、字段完整性）
- `scripts/merge_lines.py` - 合并 `data/lines/*.jsonl` 为最终 `data/timetable.jsonl`
- `scripts/ocr_layout.py` - OCR 布局分析工具（查看图片文本结构）
- `scripts/download_timetables.py` - 下载时刻表图片
- `scripts/fetch_osm_subway.py` - 获取站点坐标
- `scripts/parsers/` - **27 条线路的专用解析器**（`parse_lines_<描述>.py` / `parse_line<数字>.py`），针对各线路图片格式定制，正确率可达 100%
- `scripts/SUBAGENT_OCR_GUIDE.md` - OCR 解析 subagent 工作指南（含难点总结）

### 核心功能
1. **定位服务** - 自动获取用户位置找到最近地铁站
2. **站点搜索** - 手动输入站名搜索
3. **时刻表查询** - 显示下班车时间和倒计时
4. **多方向支持** - 选择不同方向的线路

## 数据格式

### routes.json
```json
{
  "lines": [
    {
      "lineName": "1",
      "lineColor": "#E53935"
    }
  ],
  "coordinates": {
    "站名": [纬度, 经度]
  }
}
```

### timetable.jsonl
每行一个JSON对象：
```json
{"filename": "1-万寿路-1.jpg", "route": "1", "station": "万寿路", "destination": "环球度假区", "operating_time": "工作日", "schedule_times": ["06:00", "06:05"]}
```
字段说明：
- `filename` - 来源图片文件名（用于追溯）
- `route` - 线路号
- `station` - 站名
- `destination` - 终点站（方向）
- `operating_time` - 运营时段（工作日/双休日/平日/星期五）
- `schedule_times` - 发车时刻列表（HH:MM，严格递增）

## 开发注意事项

### 国际化
- 所有文本通过 `window.i18n.t(key)` 获取
- 语言切换会触发 `languageChanged` 事件
- 翻译文件在 `i18n.js` 的 `translations` 对象中

### Python 虚拟环境
项目使用 `.venv` 虚拟环境（Python 3.14），所有 Python 脚本需通过虚拟环境运行：
```bash
.venv/bin/python scripts/download_timetables.py
.venv/bin/python scripts/parse_timetables.py
# 或先激活: source .venv/bin/activate
```

OCR 依赖 `ocrmac`（macOS Vision 框架）、`PIL`、`numpy`、`thefuzz`。

### 数据质量检查
解析完成后用 `check_timetable.py` 校验数据质量：
```bash
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl   # 检查最终数据
.venv/bin/python scripts/check_timetable.py -f data/lines/1.jsonl -l 1  # 检查单条线路
```
检查规则：时间严格递增、相邻间隔合理（2-11 分钟正常，夜间放宽）、字段完整。

### 启动开发服务器
```bash
python3 -m http.server 8000  # 简单HTTP服务器
```

## 更新时刻表数据

### 更新流程

当地铁有新线路或站点开通时，按以下步骤更新数据：

1. **下载时刻表图片**
   ```bash
   .venv/bin/python scripts/download_timetables.py
   ```
   - 从北京地铁官网、京港地铁、北京轨道运营三个来源下载
   - 图片保存到 `timetables/` 目录，命名格式：`线路-站名-编号.jpg`（部分线路为 `.png`）
   - 每个站的图片通常为 4 张（两个方向 × 工作日/双休日），编号 1-4

2. **解析时刻表**
   ```bash
   .venv/bin/python scripts/parse_timetables.py   # 通用解析器（基线）
   .venv/bin/python scripts/parse_line_ocr.py -l 10   # 坐标法通用入口
   ```
   - 项目已为 27 条线路开发了**专用解析器**（`scripts/parsers/`），针对各线路图片格式定制，正确率可达 100%
   - 专用解析器命名：`parse_lines_<描述>.py` / `parse_line<数字>.py`
   - 各线路解析结果先输出到 `data/lines/{线路}.jsonl`，再合并为 `data/timetable.jsonl`

3. **合并各线路数据**
   ```bash
   .venv/bin/python scripts/merge_lines.py -o data/timetable.jsonl
   ```

4. **校验数据质量**
   ```bash
   .venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl
   ```

5. **更新站点坐标**
   ```bash
   .venv/bin/python scripts/fetch_osm_subway.py
   ```
   - 从OpenStreetMap获取最新的地铁站点GPS坐标
   - 自动更新 `data/routes.json`

### 数据源

- **北京地铁**: https://www.bjsubway.com/station/xltcx/
  - 站点页格式：`.../line{线路}/{日期}/{编号}.html?sk=1`
  - 图片格式：`.../d/file/station/xltcx/line{线路}/{日期}/{线路}号线-{站名}-{方向}-{工作日/双休日}.jpg`
- **京港地铁**: https://www.mtr.bj.cn/service/line/
  - 线路页：`.../line/line-{线路}.html`（4/14/16/17 号线）
  - 站点页：`.../line/station/{id}.html#schedule`，时刻表图在 `#schedule` 锚点下
- **北京轨道运营**: https://www.bjmoa.cn/trainTimeList_363.html
  - 线路参数：`?sline={线路编号}`（如 24=燕房线、26=19号线、16=大兴机场线）
  - 图片格式：`https://www.bii.com.cn/file/...png`

### OCR 解析原理

时刻表图片用 macOS Vision 框架（`ocrmac`，framework=`livetext`）做 OCR，返回 `(text, confidence, bbox)` 三元组：

```python
from ocrmac import ocrmac
annotations = ocrmac.OCR('timetables/1-八宝山-1.jpg', framework="livetext").recognize()
```

解析要点：
- **按行分组**：BoundingBox 的 y 坐标（第二个坐标）与上一个字符相差不超过 `eps≈2e-2` 视为同一行
- **终点站**：匹配 `开往XXX方向`，提取 XXX
- **运营时间**：匹配 `工作日` / `双休日` / `平日` / `星期五`（OCR 常乱序，需宽松匹配）
- **具体时刻**：每行第一个数字为小时（4-23），其后数字为分钟，如行 `5 03 06` → `5:03` `5:06`
- **线路/站名**：从文件名 `线路-站名-*` 提取

已知的 OCR 难点及解决方案见 `scripts/SUBAGENT_OCR_GUIDE.md`（小时列丢失、分钟拆散、圆圈/带圈数字干扰等）。
