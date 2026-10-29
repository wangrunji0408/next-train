# CLAUDE.md — 下班车时间（Next Train）

给 AI coding agent 的项目说明书。面向用户的介绍见 `README-CN.md` / `README.md`，这里只写**动手改代码必须知道的东西**。

## 一句话

纯静态前端（`index.html` + `app.js` + `i18n.js`）+ 一条「官网海报 → OCR → `data/timetable.jsonl`」的数据管线，覆盖北京地铁 27 条线、1991 张时刻表。

## 关键事实

- 前端无构建：`fetch('data/routes.json')`、`fetch('data/timetable.jsonl')`，必须用 HTTP 服务打开（`file://` 会被 CORS 拦）。
- 数据按「线路 × 车站 × 方向 × 运营时段」一行一条，`schedule_times` 严格递增。
- 解析入口只有一个：`scripts/parse_ocr.py`；燕房线/大兴机场线自动切到 `scripts/ocr/legacy/` 的兜底解析器。
- `timetables/`（约 2 GB 海报）和 `work/`（解析中间产物）都**不进 git**。
- Python 一律用 `.venv`（3.14）：`.venv/bin/python`。OCR 需要 `tesseract`（eng + snum）。

## 目录

```
index.html app.js i18n.js icon.png    前端
data/routes.json                      线路颜色 + 站点坐标（405 站）
data/timetable.jsonl                  最终数据集（27 线，1991 条）
data/lines/<线路>.jsonl                解析中间结果（gitignored，merge 的输入）
timetables/<线路>-<站名>-<编号>.jpg/png  官方海报（gitignored）
scripts/
  parse_ocr.py                        解析入口：prep → OCR → export
  ocr/prep.py                         图片归一化（彩色小时格白字→黑字、>2400px 缩放）
  ocr/parse_line.py                   行切分 + 逐行重绘 + tesseract 识数
  ocr/{common,checker,compact}.py     字形提取、间隔校验、紧凑 JSONL
  ocr/export.py                       导出 app 格式（幻影分钟/图例误读清理）
  ocr/meta/<线路>/meta.json            人工核对的方向/时段（★ 最重要的资产）
  ocr/legacy/{airport,preprocess,vision_ocr}.py  方形版式兜底（燕房/大兴机场）
  download_timetables.py              三个运营方官网下载
  check_timetable.py                  数据质量检查
  check_line_updates.py               查北京地铁官网各线「YYYY年MM月更新」
  merge_lines.py                      合并 data/lines → data/timetable.jsonl
  fetch_osm_subway.py                 从 OSM 刷新站点坐标
  serve_https.py                      本地 HTTPS 服务（手机定位测试）
work/ocr/<线路>.jsonl + report.json    原始解析结果与质检报告（gitignored）
```

## 常用命令

```bash
.venv/bin/python scripts/parse_ocr.py -l 14          # 单线
.venv/bin/python scripts/parse_ocr.py --lines 14,17  # 多线
.venv/bin/python scripts/parse_ocr.py --all          # 全量（约 2800 张图，20+ 分钟）
.venv/bin/python scripts/merge_lines.py -k -o data/timetable.jsonl
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl
.venv/bin/python scripts/check_timetable.py -f data/lines/1.jsonl -l 1
```

## 数据约定

```json
{"filename":"1-万寿路-1.jpg","route":"1","station":"万寿路",
 "destination":"环球度假区","operating_time":"工作日",
 "schedule_times":["05:11","05:15","05:19"]}
```

- `route`：`1`…`19`、`S1`、`亦庄`、`八通`、`大兴机场`、`房山`、`昌平`、`燕房`、`首都机场`（27 个）
- `operating_time`：`工作日` / `双休日` / `平日` / `星期五`
  - 大兴机场线：`平日`（周一至周五及重点保障）、`双休日`
  - 首都机场线：`平日`（周一至周四）、`星期五`
- `schedule_times`：`HH:MM`，严格递增，正常 2–11 分钟一班，夜间放宽
- `filename`：对应 `timetables/` 里的原图，用于追溯；改名会让 `meta.json` 的 `_images` 失效

**不要手改 `data/timetable.jsonl`**：改 `scripts/ocr/meta/*` 或解析器，然后重跑管线。若必须临时修补，同时更新对应 `data/lines/<线路>.jsonl`，否则下次 merge 会被覆盖。

## 更新流程

1. **下载**：`scripts/download_timetables.py -l <线路>`（`--force` 跳过更新月份检查）
   - 京港地铁对 python-requests 默认 UA 返回 403 → 必须带浏览器 UA
   - 北京轨道运营：`?sline=16` = 19 号线、`24` = 燕房线、`26` = 大兴机场线；图在 `div.mod-roads`，`<img alt>` 就是站名
2. **解析**：`scripts/parse_ocr.py --lines …`
   - 主引擎：`prep.py` 归一化 → 行切分 → 逐行重绘 → tesseract（`snum`）
   - 方向/时段**不靠 OCR**，按文件名后缀 1–4 查 `ocr/meta/<线路>/meta.json`；终点站例外写在 `_images`。**新增车站/新后缀要补 meta**
   - 燕房线、大兴机场线：`ocr/legacy/airport.py`（macOS Vision），它的 `_fix_service()` 负责大兴机场线的「星期六和星期日 / 星期一至星期五」表头
3. **合并**：`merge_lines.py -k`（`-k` = 只替换 `data/lines/` 里存在的线路）
4. **校验**：`check_timetable.py`；最好再抽 3–5 张图人工对一遍首末班和某一行分钟

## 2026 版海报的坑（改解析器前必读）

- 小时列从「深色数字」变成「彩色胶囊 + 白字」，`prep.py` 必须先把它们改成黑字，否则整个小时列读不出来（表现为时刻表从早上 8 点才开始，或出现 00:xx/01:xx 的幽灵行）
- 19 号线海报宽 5107px，`prep.py` 统一缩到 2400px；不缩会触发引擎的「双面板」误判，把一张表切成两条记录
- 燕房线小时列是一整条竖条（不是独立色块），`prep.py` 里单独走 `tall strip` 分支
- 大兴机场线把分钟装在蓝框里，主引擎会把框线当墨迹 → 用兜底解析器
- 图例里的「5 20 表示5点20分」会被读成 05:20，`export.py` 的 `drop_isolated_leading` 负责丢掉这类离群时间
- 1 分钟间隔基本是「前一位数字」幻影（03 被读成 02,03），`export.py` 的 `drop_phantom_minutes` 负责清理

## 前端约定

- 所有文案走 `window.i18n.t(key)`，翻译在 `i18n.js` 的 `translations`；切语言会触发 `languageChanged`
- 线路颜色来自 `routes.json` 的 `lineColor`（DB11/T 657.2 标准色）
- 新增/改名车站：同步 `data/routes.json` 的 `coordinates`（`fetch_osm_subway.py` 可批量刷新）

## 已知问题

- `www.bjsubway.com` 2026-10 起服务器级宕机（A 记录在、80/443 超时），它承载的 20 条线暂时无法下载；`check_line_updates.py` 此时会把缓存写成 null，注意别误提交 `timetables/line_updates.json`
- 燕房线、大兴机场线仍是「主引擎 + 兜底」两套代码，长期应把方形版式并进 `prep.py`
- 14/17 号线个别记录仍可能有漏班（表现为固定站点同时缺同一班车）；质检报告在 `work/ocr/<线路>/report.json`

## 提交前

```bash
.venv/bin/python scripts/check_timetable.py -f data/timetable.jsonl   # 必须 100%
git status --short          # 不要提交 timetables/、work/、data/lines/、.DS_Store
```
