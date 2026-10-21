# 已退役：旧流水线

**这里的东西不再执行，也不再维护。** 保留它们只有两个用途：
① 作为「这些数字当初是从哪来的」的证据；② 回归比对的基准。

退役日期：2026-10-21。退役依据见下。

## 退役前跑过的回归比对

```bash
python3 -I engine/regress.py --trip trips/sri-lanka-2027-02 \
    --old legacy/data/targets.json
```

结果：

| 项 | 结果 |
|---|---|
| **旧有、新无** | **0 种** —— 旧流水线的结论一条没丢 |
| **特有种** | 旧 35 / 新 35，**完全一致** |
| 旧产出解析不出 eBird code | 2 条（`Corvus levaillantii`、`Curruca althaea`）|
| 新有、旧无 | 195 种（口径差异：旧的是人工筛过的目标清单，新的是完整地区名录分三档）|

两条解析失败的裁决记在 `trips/sri-lanka-2027-02/checks.md`。

## 目录

| 路径 | 原用途 | 现在 |
|---|---|---|
| `scripts/` | 旧流水线（抓取、解析、渲染、校验）| 不执行。判断表已迁进 `trips/<id>/*.md` |
| `raw/` | 旧流水线的页面与 API 缓存（49 MB）| 无任何引用，可删 |
| `data/sri-lanka.json` | 第三方地区名录 | **仍在用**——`trip.md` 声明它为第三方比对源 |
| `data/targets.json` | 旧的 259 种目标清单 | **仍在用**——`engine/regress.py` 的回归基准 |
| `data/` 其余 | 旧流水线的中间产物 | 无引用 |

## 为什么不直接删

`data/sri-lanka.json` 与 `data/targets.json` 还被引用（见上表）。
其余（尤其 49 MB 的 `raw/`）已经没有任何引用，确认不需要后可以删。

## 旧流水线的哪些东西被保住了

迁移**不是重写**，旧流水线里真正值钱的是踩出来的结论，它们都有了新家：

| 旧的东西 | 新家 |
|---|---|
| 14 张现场经验/判断表 | `trips/<id>/` 下的 Markdown 配置表 |
| 四层待办结构 | `trips/<id>/todos.md` |
| 「有效机会」判定的三版演化 | `engine/opportunity.py` 的模块文档 |
| 热点钉死机制与串点事故 | `engine/sources/ebird.py` + `verify.py` 的专项检查 |
| 远洋海鸟的结构性盲区 | `engine/opportunity.py` 的 `blind_spot()` |
| 「频次 ≠ 难度」等方法论 | `docs/方法论.md` |
| 防编造、防漂移、防口径分裂 | `engine/verify.py` |
