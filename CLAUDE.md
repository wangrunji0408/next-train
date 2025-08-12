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
python3 serve_https.py  # HTTPS服务器（定位功能需要）
# 或
python3 -m http.server 8000  # 简单HTTP服务器
```
