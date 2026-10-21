# 观鸟行程规划工具包

投入任意物料（网页、PDF、一句话），产出五份可执行的文档。
**所有物种数据以 eBird 为唯一权威。**

```bash
python3 -I engine/build.py --trip trips/sri-lanka-2027-02
```

1.4 秒重建全部产出。

## 它解决什么问题

规划一趟观鸟行程要回答三个问题，而它们分别卡在不同的地方：

| 问题 | 卡在哪 |
|---|---|
| 有哪些鸟、怎么叫 | 鸟名有中文名/英文名/学名三套，各平台叫法还不一样；**报错一个字母当地鸟导就查不到** |
| 每天去哪、找什么 | 名录只说「这个地区有这种鸟」，不说「2 月那天在那个点看不看得到」 |
| 这趟能看到多少 | 没有可复现的算法，全凭感觉 |

这套工具把三者串起来：eBird 取数 → 分档与机会判定 → 渲染成文档 → 校验防编造。

## 五份产出

| 文档 | 只回答 |
|---|---|
| `01-鸟种清单.md` | 有哪些鸟、怎么叫（特有种/重点关注/其它三档）|
| `02-行程表.md` | 每天在哪、关注什么鸟、什么形式、是否夜探；**「错过即无」是最该先看的一栏** |
| `03-第三方分歧.md` | 第三方与 eBird 不一致之处，待人裁决 |
| `04-预期产出.md` | 预计多少种、80% 区间、敏感性、模型天花板 |
| `05-行前与物流.md` | 带队分段、报价核算、四层待办 |

**五份不重叠**：鸟种详情只在 01，找鸟只在 02，物流完全不碰鸟种数据。

## 最高原则

**eBird 是唯一权威源。** 物种在不在名录、分布、季节、频次、是否特有，
一律以 eBird 为准。雀跃、GBIF、别人的行程报告都是第三方，
**只能进分歧报告，不能覆盖 eBird**。

唯一例外是**鸟名翻译**：中文名来自 IOC World Bird List 多语种版，
英文名用 IOC 的老牌图鉴常用名（当地鸟导用的是图鉴）。
但它们**只是显示标签**——所有匹配、统计、分档的键都是 eBird `speciesCode`。

## 为什么中文名要靠 IOC

eBird 的 `zh_SIM` **只给「中国有记录的种」中文名**，
中国没有的种直接沿用英文名——所以它结构性地覆盖不到任何境外特有种。

实测：eBird zh_SIM 全球覆盖 1,666/11,167；
**斯里兰卡 35 种特有种一个中文名都没有**。
换成 IOC 多语种版后，11,227 种里 11,204 种有中文名（99.8%），
对 eBird 学名直接匹配 99%，加英文名兜底 99.7%，
**35 种特有种 35/35 全中**。

## 快速上手

```bash
# 一次性：全局参考数据（所有行程共用）
python3 -I engine/refdata/fetch_taxonomy.py    # eBird 分类骨干 11,167 种
python3 -I engine/refdata/fetch_ioc.py         # IOC 中文名 11,227 种
python3 -I engine/endemism.py --world-cache    # 253 个地区名录（特有种判定）

# 每趟行程
python3 -I engine/build.py --trip trips/<id> --fetch --rate 25   # 首次，含取数
python3 -I engine/build.py --trip trips/<id>                     # 之后，秒级重建
python3 -I engine/verify.py --trip trips/<id>                    # 校验
python3 -I engine/doctor.py --trip trips/<id> --net              # 出问题先跑这个
```

新建行程、投物料、改行程都有斜杠命令：
`/trip-new`、`/trip-ingest`、`/trip-build`、`/trip-update`、`/trip-estimate`。

## 目录

```
engine/              通用引擎，零行程硬编码
  mdtable.py         Markdown 配置解析（只解析不解释）
  taxonomy.py        ★ 名字闸门：全项目唯一能把名字变成物种的地方
  opportunity.py     ★ 「有效机会」判定的单一来源
  endemism.py        特有种：253 个地区名录倒排
  estimate.py        概率模型 + 天花板诊断 + 敏感性
  materials.py       物料登记（sha256 去重）+ 名字闸门 CLI
  build.py           一键重建，任一步非零退出立即停
  verify.py          防编造 / 防漂移 / 防口径分裂
  doctor.py          排障自检
  refdata/           全局参考数据（分类、中文名、地区名录）
  sources/           eBird（权威）+ thirdparty/（只比对）
  render/            五份文档的渲染器
trips/<id>/          一趟行程：配置 + 物料 + 数据 + 产出
tools/               一次性迁移脚本
docs/                本目录
```

## 配置：Markdown 表格

本机 Python 3.9 **只有标准库**（无 PyYAML / bs4 / requests / pdftotext），
所以配置用 Markdown 表格 + 三十行解析器。

好处不只是零依赖——**配置即文档**：表格外可以写满理由和踩坑记录，
解析器会忽略。判断必须写明为什么，这是本项目的硬规矩。

格式见 [配置格式.md](配置格式.md)。

## 延伸阅读

- [配置格式.md](配置格式.md) —— 每个配置文件写什么
- [脚本使用.md](脚本使用.md) —— 每个脚本干什么、怎么跑
- [排障.md](排障.md) —— 真实踩过的坑与处方
- [方法论.md](方法论.md) —— 那些反直觉但正确的结论
