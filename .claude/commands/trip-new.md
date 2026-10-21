---
description: 新建一趟观鸟行程
---

新建行程：$ARGUMENTS

先问清这几件事（缺一不可）：
1. **eBird 地区码**（如 `LK`、`TH`、`CN-YN`）。可查：
   `curl -H "X-eBirdApiToken: $KEY" "https://api.ebird.org/v2/ref/region/list/country/world?fmt=json"`
2. **日期范围**，以及取样窗口用哪几年
3. **母语区**（判定生涯新种的基准，中国用户一般是 `CN`）
4. **关注类群**：鸟类之外要不要兽类/两栖爬行（它们**没有 eBird 数据**，单独成篇）

然后：
1. `mkdir -p trips/<id>/{materials,data,out}`
2. 照 `trips/sri-lanka-2027-02/` 的格式写 `trip.md`、`sites.md`、`itinerary.md`
3. 全局参考数据若还没有，跑一次（所有行程共用）：
   ```bash
   python3 -I engine/refdata/fetch_taxonomy.py
   python3 -I engine/refdata/fetch_ioc.py
   python3 -I engine/endemism.py --world-cache
   ```
4. `python3 -I engine/build.py --trip trips/<id> --fetch --rate 25`

点位表的 `eBird locId` **务必钉死关键点位**，理由见技能文档。
