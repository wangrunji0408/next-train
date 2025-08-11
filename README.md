## 自动下载列车时刻表图

### 北京地铁

https://www.bjsubway.com/station/xltcx/

这个页面里有每条线每个站的链接，例如：
https://www.bjsubway.com/station/xltcx/line1/2013-08-19/4.html?sk=1（古城）

点开后，每个页面有2/4张图：
https://www.bjsubway.com/d/file/station/xltcx/line1/2023-12-30/1号线-古城站-环球度假区站方向-工作日.jpg?=1
https://www.bjsubway.com/d/file/station/xltcx/line1/2023-12-30/1号线-古城站-环球度假区站方向-双休日.jpg?=1


将其下载下来，保存为"线路-站名-编号.png"，例如：
1-古城-1.png
1-古城-2.png
...

### 京港地铁

对以下每个网页：
https://www.mtr.bj.cn/service/line/line-4.html
https://www.mtr.bj.cn/service/line/line-14.html
https://www.mtr.bj.cn/service/line/line-16.html
https://www.mtr.bj.cn/service/line/line-17.html

每个网页中都有每个站的链接，例如：
https://www.mtr.bj.cn/service/line/station/5d5a18eeb1ea0278b8fffd5d.html

加上 #schedule 后缀访问，例如：
https://www.mtr.bj.cn/service/line/station/5d5a18eeb1ea0278b8fffd5d.html#schedule

会看到“时刻表”下面有两个图（终点站）/四个图，例如：
https://cdnwww.mtr.bj.cn/bjmtr/station/U5za1h-MCsXvTZWwQmCE5.jpg

将其下载下来，保存为"线路-站名-编号.png"，例如：
4-安河桥北-1.png
4-安河桥北-2.png
...

### 北京轨道运营

对以下每个网页：
https://www.bjmoa.cn/trainTimeList_363.html?sline=24
https://www.bjmoa.cn/trainTimeList_363.html?sline=26
https://www.bjmoa.cn/trainTimeList_363.html?sline=16

每个网页中有每个站的图，例如：
https://www.bii.com.cn/file/2024/08/08/1723129123089.png

将其下载下来，保存为"线路-站名-编号.png"，例如：
燕房线-燕山-1.png
燕房线-燕山-2.png

## 解析列车时刻表

timetables 里面有若干张图片（.jpg/.png），每张一个站的列车时刻表。请使用 OCR 解析时间。

```python
from ocrmac import ocrmac
annotations = ocrmac.OCR('timetables/1号-八宝山站-1.jpg', framework="livetext").recognize()
print(annotations)
# Output (Text, Confidence, BoundingBox):
# [("GitHub: Let's build from here - X", 0.5, [0.16, 0.91, 0.17, 0.01]),
# ('github.com', 0.5, [0.174, 0.87, 0.06, 0.01]),
# ('Qi &0 O M #O', 0.30, [0.65, 0.87, 0.23, 0.02]),
# [...]
# ('P&G U TELUS', 0.5, [0.64, 0.16, 0.22, 0.03])]
```

首先按行对字符分组

然后提取：
- 终点站：匹配 “开往XXX方向”，提取 XXX
- 运营时间：匹配 “工作日” 或 “双休日”
- 具体时刻：



