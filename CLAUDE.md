# Next Train App - 下班车时间查询

## 项目概述
这是一个基于Web的地铁下班车时间查询应用。

## 核心文件结构

### 主要文件
- `index.html` - 主页面，包含UI布局和样式
- `app.js` - 主应用逻辑（NextTrainApp类）
- `i18n.js` - 国际化支持（I18n类）
- `data/routes.json` - 地铁线路数据和站点坐标
- `data/timetable.jsonl` - 时刻表数据

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
{"station": "站名", "route": "1", "destination": "目的地", "operating_time": "工作日", "schedule_times": ["06:00", "06:05"]}
```

## 开发注意事项

### 国际化
- 所有文本通过 `window.i18n.t(key)` 获取
- 语言切换会触发 `languageChanged` 事件
- 翻译文件在 `i18n.js` 的 `translations` 对象中

### 启动开发服务器
```bash
python3 -m http.server 8000  # 简单HTTP服务器
```

## 更新时刻表数据

### 更新流程

当地铁有新线路或站点开通时，按以下步骤更新数据：

1. **下载时刻表图片**
   ```bash
   python3 scripts/download_timetables.py
   ```
   - 从北京地铁官网、京港地铁、北京轨道运营三个来源下载
   - 图片保存到 `timetables/` 目录，命名格式：`线路-站名-编号.jpg`

2. **解析时刻表**
   ```bash
   python3 scripts/parse_timetables.py
   ```
   - 使用OCR识别时刻表图片中的时间信息
   - 生成 `timetable.jsonl` 文件
   - 注意：脚本默认解析所有图片，如只需更新特定线路，需修改脚本中的文件过滤逻辑

3. **更新站点坐标**
   ```bash
   python3 scripts/fetch_osm_subway.py
   ```
   - 从OpenStreetMap获取最新的地铁站点GPS坐标
   - 自动更新 `data/routes.json`

### 数据源

- **北京地铁**: https://www.bjsubway.com/station/xltcx/
- **京港地铁**: https://www.mtr.bj.cn/service/line/
- **北京轨道运营**: https://www.bjmoa.cn/trainTimeList_363.html
