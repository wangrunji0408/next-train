# 下班车时间 · Next Train

一个纯静态的网页应用：定位到最近的地铁站，告诉你下一班车还有几分钟。
数据来自北京地铁、京港地铁、北京轨道运营公开发布的**站内时刻表海报**，经 OCR 解析成结构化时刻。

## 功能

- 📍 自动定位最近车站（也支持手动搜索站名）
- 🕐 显示下一班车时间与倒计时
- ↔️ 按方向切换（同一车站多个终点站）
- 🌗 浅色/深色主题、多语言（中/英）
- 📊 覆盖 27 条线、1991 张时刻表（工作日 / 双休日 / 平日 / 星期五）

## 快速开始

```bash
python3 -m http.server 8000
# 打开 http://localhost:8000/
```

页面是纯静态的，直接用 `file://` 打开 `index.html` 会因 `fetch` 跨域失败，需要起一个本地 HTTP 服务。
要在手机上测试定位（HTTPS 才能拿到地理位置），可以跑：

```bash
.venv/bin/python scripts/serve_https.py 8443
```

## 项目结构

```
.
├── index.html / app.js / i18n.js   # 前端（无构建步骤）
├── icon.png
├── data/
│   ├── routes.json                 # 线路颜色 + 站点坐标
│   └── timetable.jsonl             # 时刻表数据集（27 条线）
├── timetables/                     # 官方时刻表海报原图（gitignored，约 2 GB）
├── scripts/
│   ├── parse_ocr.py                # ★ 解析入口：图片 → data/lines/*.jsonl
│   ├── ocr/                        # OCR 引擎
│   │   ├── prep.py                 # 图片归一化（彩色小时格白字→黑字、超大图缩放）
│   │   ├── parse_line.py           # 行切分 + 逐行重绘 + tesseract 识数
│   │   ├── common.py / checker.py / compact.py
│   │   ├── export.py               # 导出 app 格式，清理幻影分钟
│   │   ├── meta/<线路>/meta.json    # 人工核对的方向/运营时段
│   │   └── legacy/                 # 燕房线/大兴机场线兜底解析器（方形版式）
│   ├── download_timetables.py      # 从三个运营方官网下载海报
│   ├── check_timetable.py          # 数据质量检查
│   ├── check_line_updates.py       # 查北京地铁官网各线更新月份
│   ├── merge_lines.py              # 合并 data/lines → data/timetable.jsonl
│   ├── fetch_osm_subway.py         # 从 OSM 更新站点坐标
│   └── serve_https.py              # 本地 HTTPS 静态服务（手机定位测试用）
├── work/                           # 解析中间产物（gitignored）
└── requirements.txt
```

## 数据格式

`data/timetable.jsonl` 每行一条时刻表：

```json
{
  "filename": "1-万寿路-1.jpg",
  "route": "1",
  "station": "万寿路",
  "destination": "环球度假区",
  "operating_time": "工作日",
  "schedule_times": ["05:11", "05:15", "05:19"]
}
```

- `route` 为线路名（`1`、`S1`、`八通`、`昌平`、`燕房`、`大兴机场`…）
- `operating_time` 取 `工作日` / `双休日` / `平日` / `星期五`
- `schedule_times` 严格递增的 `HH:MM`
- `filename` 指向 `timetables/` 里的原图，用于追溯

前端通过 `fetch('data/routes.json')` 和 `fetch('data/timetable.jsonl')` 读取，无需构建。

## 更新时刻表

```bash
# 1. 下载（可按线路）
.venv/bin/python scripts/download_timetables.py            # 全部
.venv/bin/python scripts/download_timetables.py -l 14      # 单条

# 2. 解析（燕房线/大兴机场线会自动走兜底解析器）
.venv/bin/python scripts/parse_ocr.py --lines 14,17,19

# 3. 合并（-k 只替换这次解析过的线路）
.venv/bin/python scripts/merge_lines.py -k -o data/timetable.jsonl

# 4. 校验
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl
```

首次使用需要装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
brew install tesseract            # OCR 引擎，需要 eng/snum 语言包
```

## 数据来源

| 运营方 | 线路 | 站点 |
|---|---|---|
| [北京地铁](https://www.bjsubway.com/station/xltcx/) | 1、2、3、5、6、7、8、9、10、11、12、13、15、18、S1、八通、昌平、房山、亦庄、首都机场 | 站内海报 |
| [京港地铁](https://www.mtr.bj.cn/service/line/) | 4/大兴线、14、16、17 | 站内海报 |
| [北京轨道运营](https://www.bjmoa.cn/trainTimeList_363.html) | 19、燕房、大兴机场 | 站内海报 |

线路颜色取自维基百科「北京地铁颜色」模板（依据 DB11/T 657.2 标准色）。

## 已知限制

- 时刻表是静态表，节假日/临时调整不体现。
- 北京地铁官网 2026-10 起服务器级故障，那 20 条线的海报暂时无法更新。
- 燕房线、大兴机场线的方形版式由兜底解析器处理，与主引擎是两套代码。
