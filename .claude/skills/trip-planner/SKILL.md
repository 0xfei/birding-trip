---
name: trip-planner
description: 观鸟/观兽行程规划工具包。投入任意物料（网页、PDF、文字），产出鸟种清单、行程表、预期产出、物流手册。数据以 eBird 为唯一权威。当用户要新建行程、投入新材料、修改行程/酒店/鸟导安排、重算预期种数、或问「这趟能看到多少种」时使用。
---

# 观鸟行程规划工具包

把任意物料变成四份可执行的文档。**所有物种数据以 eBird 为唯一权威。**

## 最高原则（违反这些会毁掉产出的可信度）

1. **eBird 是唯一权威源。** 物种在不在名录、分布、季节、频次、是否特有——
   一律以 eBird 为准。雀跃、GBIF、别人的行程报告都是第三方，
   **只能进分歧报告，不能覆盖 eBird**。

2. **任何鸟名进配置前必须过闸门。**
   ```bash
   python3 -I engine/materials.py --trip <trip> --resolve "名字1" "名字2"
   ```
   解析不出的**绝不猜**——列给用户裁决，或让用户确认后加进别名表。
   错一个字母，当地鸟导就查不到这只鸟。

3. **逐字符保真的值不经自然语言转述。**
   eBird `locId`、`speciesCode`、经纬度、报价数字、日期时刻——
   这些一律由脚本读写。**不要凭印象写 code**：
   实测连 `srlgrp1`、`whiter3` 这样看着很合理的 code 都是错的。

4. **改配置前先展示 diff，由用户确认后才落盘。**

5. **判断必须写明理由。** 配置文件里每张判断表都要能回答「为什么这么定」。

## 目录

```
engine/          通用引擎，零行程硬编码
trips/<id>/
  trip.md        行程元信息（地区码、日期、母语区、阈值、模型参数）
  sites.md       点位（坐标、半径、钉死的 eBird locId）
  itinerary.md   逐日时段（日期/时段/点位/形式/带队/夜探/说明）
  targets.md     别名表、关注科目、用户点名
  todos.md       四层待办
  logistics.md   汇率与服务项目报价
  materials/     物料原件 + 抽取结果，按 sha256 去重
  data/          取数结果（机器层）
  out/           五份交付文档
```

配置全是 **Markdown 表格**，零依赖解析（`engine/mdtable.py`）。
配置即文档——表格外可以写满解释和踩坑记录，解析器会忽略。

## 常用流程

### 投入新物料并更新文档

```bash
# 1. 收材料（落盘、算 sha256、去重登记）
python3 -I engine/materials.py --trip trips/<id> --add <url|路径>
python3 -I engine/materials.py --trip trips/<id> --add-text "..." --label "..."

# 2. 读材料，把抽取结果写进 materials/<id>/extract.md
#    （PDF 直接用 Read 工具读；网页读下载下来的 html）

# 3. 材料里出现的每个鸟名都过闸门
python3 -I engine/materials.py --trip trips/<id> --resolve "名字…"

# 4. 改配置（展示 diff 让用户确认），然后重建
python3 -I engine/build.py --trip trips/<id>
```

### 只重建文档（不取数，秒级）

```bash
python3 -I engine/build.py --trip trips/<id>
```

### 重新取数（会被 eBird 限流，慢）

```bash
python3 -I engine/build.py --trip trips/<id> --fetch --rate 25
```

### 新建一趟行程

1. `mkdir -p trips/<id>/{materials,data,out}`
2. 照着 `trips/sri-lanka-2027-02/` 写 `trip.md` / `sites.md` / `itinerary.md`
3. 一次性的全局参考数据（所有行程共用，只需跑一次）：
   ```bash
   python3 -I engine/refdata/fetch_taxonomy.py   # eBird 分类骨干
   python3 -I engine/refdata/fetch_ioc.py        # IOC 中文名字典
   python3 -I engine/endemism.py --world-cache   # 253 个地区名录（特有种判定）
   ```
4. `python3 -I engine/build.py --trip trips/<id> --fetch`

## 配置要点

### `itinerary.md` 的 `形式` 一列

它同时驱动三件事：本段是否产出鸟种、概率模型的权重、文档的章节组织。

| 形式 | 含义 | 模型权重 |
|---|---|---|
| `birding` | 常规步行观鸟 | 1.0 |
| `pelagic` | 出海 | 1.0 |
| `hike` | 长距离徒步，以赶路为主 | 0.9 |
| `safari` | 车上观察，覆盖广但停留少 | 0.8 |
| `night-walk` / `night-drive` | 夜探 | 0.7 |
| `transfer` | 转场，沿途机会 | 0.3 |
| `rest` | 休息，不计产出 | 0 |

`时段` 列写成 `HH:MM–HH:MM` 或 `1–2h` 才能解析出时长；
写 `上午`、`全天` 会走形式兜底，并在预期产出里用 `ᶠ` 标出来。

### `sites.md` 的 `eBird locId`

**关键点位一定要钉死 locId。** 留空会退回按半径搜热点，
而半径搜对相邻点位会返回**完全相同的热点**——
实测出过「市区公园的频次其实是整个镇区的」「取到了保护区错误一侧的热点」。

## 已知的坑（都踩过，别再踩）

| 坑 | 现象 | 对策 |
|---|---|---|
| eBird 限流 | 返回 `Too Many Requests`，**纯文本不是 JSON** | 已内建退避重试；`--rate` 控制速率。当成空数据会在频次里留**看不见的空洞** |
| 地区级 `historic` 看着能降量 27 倍 | 返回里带 `locId`，很诱人 | **死路**：每种只返回一条记录，还原不出各点位频次 |
| eBird barchart 接口 | 一个请求返回整张频次表 | **不可用**：被 bot 检测挡住 |
| 频次分母 | 空清单日若算进分母，频次被系统性低估 | 只数「真的有人观鸟的日子」 |
| `python3 -I` 下 urllib | DNS 失败 | 隔离模式不读代理环境变量，**一律用 curl** |
| 只跑渲染器不跑 build.py | 生成器崩了而文档停在旧版本 | 用 `build.py`，任一步非零退出立即停 |
| 遍历 set | 两次构建产出不同 | 一律 `sorted()` |

## 方法论（这些结论是踩出来的，不要退回去）

- **数据与判断分离。** 每张表都要标明哪些是数据（原样读取）、
  哪些是判断（可以争论）。判断必须写理由。
- **频次 ≠ 难度。** 频次回答「在不在」，不回答「好不好找」。
  实测：某地鸫记录很多但要找三天；某鸡鹑过去极难，建了隐蔽棚后变成坐着等。
- **「没数据」≠「看不到」。** 远洋海鸟在陆基热点上全是 0，
  因为是在船上看的。把它们当 0 会让预测凭空变低——单列成节，不进点估计。
- **总种数会误导。** 实测这趟：丢掉滨海湿地损失 26 种但**零特有种**，
  丢掉雨林只损失 14 种却**丢掉 8 种特有种**。两个指标必须一起看。
- **区间表达运气，敏感性表表达风险。** 概率模型的 80% 区间只含独立随机性；
  天气、鸟导水平这类相关性**不进方差**，用场景表单独说。
