#!/usr/bin/env python3
"""「有效机会」的**单一来源**：某种鸟在某个点位，到底算不算一次机会。

为什么必须收口到一个模块
------------------------
这条规则被四处消费：现场手册的渲染、交叉比对、逐段核验、全链路校验。
原先每处各写一遍，**口径一旦改动必然漂移**；
而它在 2026-10-19 被迫改过一版，当时正是因为有四份副本才险些漏改。
`verify` 有一项专门检查：消费方必须 import 本模块，不许自己硬写阈值。

规则的演化（三版，别再退回去）
------------------------------
**第一版**：只看 GBIF ≥20 条。
  问题：GBIF 分类骨干没收录近年新拆分的学名，于是
  斯里兰卡鹊鸲与白喉啄花鸟**全岛 0 条**，被判成「没机会」。

**第二版（2026-10-16）**：GBIF ≥20 条 **或** eBird ≥15%，取并集。
  问题：GBIF 按半径圈，**半径里的邻近生境会被算进来**。
  扩到全部目标种后立刻暴雷——**瘤鸭**在 Mirissa 的 GBIF 有 55 条、
  eBird 在 19 个观鸟日里零报到。瘤鸭是淡水湿地的鸭，而去 Mirissa 是**出海看鲸**；
  那 55 条来自 30 km 半径里的内陆水体。并集让 GBIF 把人指向了错误的地点。

**第三版（现行）**：并集 + **零记录否决**。
  `eBird 在该点有足够样本却一次都没报到` → 否决 GBIF 在该点的主张。

  关键区分（第二版踩的坑就在这）：
  - **低频 ≠ 不存在**。38 天里报到 2 次是「少见但确实有」，**保留**；
  - **零记录 + 足够样本 = 有证据的不存在**，**否决**。

两个源的分工
------------
| 源 | 角色 |
|---|---|
| **eBird** | **唯一权威**。排序、分档、机会判定的依据；**零记录可否决 GBIF** |
| **GBIF** | 仅 ① double check ② eBird 完全无数据时的弱信号兜底 ③ 历史纵深 |

eBird 当权威的理由：它**钉死了具体热点，是点位级的**；
而 GBIF 按半径圈，点位之间半径会互相重叠
（实测最极端的一对中心只隔 2.3 km，半径却是 12 km 与 10 km），
所以 GBIF 的「某点多少条」根本不是点位级的数字。eBird 还自带分母。

⚠ 结构性盲区：远洋海鸟（**两个源都盲，不要拿 0 去删它们**）
-----------------------------------------------------------
实测 18 种远洋海鸟在 eBird 与 GBIF 里**都是 0**。不是「那儿没有」，而是：
  - eBird 的出海点热点是**港口与陆地点位**，海鸟是在**船上**看的，
    船上的记录不会落进那些热点的清单；
  - GBIF 的记录多在远海，不在我们圈的半径内。

所以 **「频次 0% = 看不到」这个推论对海鸟是错的**。
本模块用 `blind_spot()` 把这类点位标出来：
**`pelagic` 形式的时段，其点位对远洋科目一律视为「无数据」而非「没机会」**，
由调用方单独成段列出，不参与排序、也不参与概率模型的点估计。

数据与判断
----------
- **数据**：eBird 频次与分母、GBIF 条数，均原样读取，不改写。
- **判断**：三个阈值、「零记录可以否决 GBIF」这条推论、以及上面那张分工表
  和盲区定义。阈值在 `trips/<id>/trip.md` 里，**本模块零硬编码**。
"""
import json
from pathlib import Path

# 远洋科目（eBird familyComName）。这些科在陆基热点上天然取不到数据。
# 是**判断**：按「主要在远海活动、不会被港口清单覆盖」来选。
PELAGIC_FAMILIES = {
    "Shearwaters and Petrels",
    "Northern Storm-Petrels",
    "Southern Storm-Petrels",
    "Albatrosses",
    "Tropicbirds",
    "Frigatebirds",
    "Boobies and Gannets",
    "Skuas and Jaegers",
}

# 哪些活动形式的点位，对远洋科目属于「取不到数据」而非「没有」
PELAGIC_MODES = {"pelagic"}


class Opportunity:
    """一次行程的机会判定。阈值与盲区都由行程配置决定。"""

    def __init__(self, freq, gbif=None, thresholds=None, pelagic_sites=None):
        """
        `freq`   —— `data/ebird_freq.json` 的内容（含 `_meta`）
        `gbif`   —— 可选的第三方 GBIF 点位计数，`{code: {"sites": {sid: n}}}`
        `thresholds` —— `{"gbif_min":…, "freq_min":…, "veto_min_days":…}`
        `pelagic_sites` —— 哪些点位是出海点（由行程的 `形式` 列推出）
        """
        self.meta = freq.get("_meta", {})
        self.freq = {k: v for k, v in freq.items() if k != "_meta"}
        self.gbif = gbif or {}
        th = thresholds or {}
        self.gbif_min = int(th.get("gbif_min", 20))
        self.freq_min = float(th.get("freq_min", 0.15))
        self.veto_min_days = int(th.get("veto_min_days", 15))
        self.pelagic_sites = set(pelagic_sites or ())
        # 分母：该点位在取样窗口内有数据的观鸟日数
        self.denom = dict(self.meta.get("denominators", {}))
        if not self.denom:
            for v in self.freq.values():
                for sid, r in v.get("sites", {}).items():
                    self.denom[sid] = max(self.denom.get(sid, 0), r["of"])

    # ---------- 基础读数（全部原样，不加工）----------

    def freq_at(self, code, site):
        """该种在该点的频次；无数据返回 `None`（**不是 0**）。"""
        r = self.freq.get(code, {}).get("sites", {}).get(site)
        return r["freq"] if r else None

    def days_at(self, code, site):
        r = self.freq.get(code, {}).get("sites", {}).get(site)
        return (r["days"], r["of"]) if r else (0, self.denom.get(site, 0))

    def gbif_at(self, code, site):
        return self.gbif.get(code, {}).get("sites", {}).get(site, 0)

    # ---------- 判定 ----------

    def blind_spot(self, code, site, family):
        """该点位对该种是否属于**结构性盲区**（取不到数据，而非没有）。

        目前只有一种：远洋科目 × 出海点位。
        盲区里的 0 **没有信息量**，既不能用来否决，也不能计进概率模型。
        """
        return site in self.pelagic_sites and family in PELAGIC_FAMILIES

    def vetoed(self, code, site):
        """eBird 是否「有证据地」否决了 GBIF 在该点的主张。

        三个条件同时成立才算否决：
          1. 该种在本线路上**确实被 eBird 记录过**（说明观察者认得它、会报它，
             否则零记录可能只是没人报这个类群）；
          2. 该点在它的记录里**没有条目**——零报到；
          3. 该点的观鸟日 **≥ veto_min_days**——样本够，零才有意义。
        """
        ev = self.freq.get(code, {}).get("sites", {})
        return (bool(ev) and site not in ev
                and self.denom.get(site, 0) >= self.veto_min_days)

    def opportunities(self, code, sites, family=""):
        """该种在给定点位集合中的「有效机会」点位。

        并集 + 零记录否决，理由见模块文档。盲区点位**不计入也不否决**。
        """
        out = set()
        for s in sites:
            if self.blind_spot(code, s, family):
                continue
            f = self.freq_at(code, s)
            if f is not None and f >= self.freq_min:
                out.add(s)
                continue
            if self.gbif_at(code, s) >= self.gbif_min and not self.vetoed(code, s):
                out.add(s)
        return out

    def has_any_data(self, code, sites=None):
        """该种在本行程点位上**有没有任何数据**。

        用来区分「有数据且很低」与「根本没数据」——
        后者绝不能当成 0 计进概率模型的点估计。
        """
        ev = self.freq.get(code, {}).get("sites", {})
        if sites is None:
            return bool(ev) or bool(self.gbif.get(code, {}).get("sites"))
        return any(s in ev for s in sites) or any(
            self.gbif_at(code, s) > 0 for s in sites)


def load(trip_dir, thresholds=None, pelagic_sites=None):
    """从行程目录读数据并构造。GBIF 不存在时自动降级为仅 eBird。"""
    d = Path(trip_dir) / "data"
    f = d / "ebird_freq.json"
    if not f.exists():
        raise SystemExit(
            f"缺 {f}\n  先跑: python3 -I engine/sources/ebird.py --trip {trip_dir}")
    freq = json.loads(f.read_text(encoding="utf-8"))
    g = d / "gbif_sites.json"
    gbif = json.loads(g.read_text(encoding="utf-8")) if g.exists() else None
    return Opportunity(freq, gbif, thresholds, pelagic_sites)
