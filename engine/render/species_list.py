#!/usr/bin/env python3
"""渲染**第一份主交付：鸟种清单**。分三档：特有种 / 重点关注 / 其它。

用法:
    python3 -I engine/render/species_list.py --trip trips/<id>

三档怎么分（泛化自原项目的四类）
--------------------------------
原项目分「①特有 ②中国无记录 ③鸮类+亮丽科 ④其它」，
其中 ③ 用的是 **60 个中文科名的硬编码常量**——换个国家全部失效，
这正是原项目无法复用的根因。现在：

| 档 | 判定 | 源 |
|---|---|---|
| **特有种** | eBird 全地区名录倒排，只在本地区出现 | `engine/endemism.py`，纯 eBird |
| **重点关注** | 生涯新种（母语区名录没有）∪ 关注科目 ∪ 用户点名 | eBird + 行程配置 |
| **其它** | 行程点位名录内其余种 | eBird |

三档**互斥**，优先级 特有 > 重点关注 > 其它。

名字的口径
----------
- **英文名为准**，用老牌图鉴常用名（IOC 口径）——要报给当地鸟导的就是这个；
- 中文名来自 IOC 多语种版，**只是显示标签**，不参与任何判定；
- 查不到中文名的**只写英文名**，不编造（实测斯里兰卡 474 种全部有中文名）。

排序
----
一律按 eBird `taxonOrder`，**不按名字排**——
名字排序会让中英文混排的清单在两次构建之间漂移（原项目实测踩过）。

频次列的读法（**最容易误读的一列**）
------------------------------------
`频次` 是「取样窗口内，该点位有多少比例的观鸟日报到了这种鸟」，**自带分母**。
两个陷阱：
  1. **0% 不等于看不到**。远洋海鸟在所有陆基热点上都是 0，
     因为它们是在船上看的——这是结构性盲区，见 `engine/opportunity.py`。
     本清单对这类种标 `盲区` 而不是 0。
  2. **频次 ≠ 难度**。记录数/频次回答「在不在」，不回答「好不好找」。
     原项目实测：斯里兰卡地鸫在 Sinharaja 记录很多，但实测耗了三天才看到；
     斯里兰卡鸡鹑过去极难，建了隐蔽棚后变成「坐着等」。
"""
import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import mdtable as M                                      # noqa: E402
import opportunity as OPP                                # noqa: E402
import taxonomy as T                                     # noqa: E402
from ebird import TripConfig                             # noqa: E402

TIER_ENDEMIC, TIER_KEY, TIER_OTHER = 1, 2, 3
TIER_NAME = {TIER_ENDEMIC: "特有种", TIER_KEY: "重点关注", TIER_OTHER: "其它"}


def load_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


class Catalog:
    """一趟行程的全部鸟种，带分档、频次、机会点位。"""

    def __init__(self, trip_dir):
        self.cfg = cfg = TripConfig(trip_dir)
        d = cfg.data
        self.t = T.load(self._aliases())

        reg = load_json(d / "ebird_region_spplist.json")
        if not reg:
            sys.exit(f"缺 {d}/ebird_region_spplist.json；"
                     f"先跑 engine/sources/ebird.py --step spplist")
        # 只留种级——spplist 会返回亚种群等非种级分类单元
        self.all_codes = [c for c in reg["species"] if c in self.t.sp]
        self.n_nonspecies = len(reg["species"]) - len(self.all_codes)

        self.endemic = set((load_json(d / "endemic.json") or {}).get("endemic", []))
        home = load_json(d / "ebird_home_spplist.json")
        self.home_codes = set(home["species"]) if home else set()
        self.home_region = home["region"] if home else ""

        # 行程涉及的点位，以及哪些是出海点（远洋盲区由它定义）
        self.itin = M.table(cfg.dir / "itinerary.md", "时段表")
        self.sites = [s for s in
                      dict.fromkeys(b["点位"] for b in self.itin)
                      if s and s != "—"]
        pelagic = {b["点位"] for b in self.itin
                   if b["形式"] == "pelagic" and b["点位"] not in ("", "—")}
        self.opp = OPP.load(trip_dir,
                            M.parse_pairs(cfg.meta.get("thresholds", "")),
                            pelagic)

        self.fams = {r["科（eBird familyComName）"]
                     for r in M.table(cfg.dir / "targets.md", "关注科目")}
        self.named, self.named_bad = self._named()
        self.tiers = {c: self._tier(c) for c in self.all_codes}

    def _aliases(self):
        f = self.cfg.dir / "targets.md"
        return ({r["别名"]: r["code"] for r in M.table(f, "别名表")}
                if f.exists() else None)

    def _named(self):
        rows = M.table(self.cfg.dir / "targets.md", "用户点名")
        ok, bad = T.load(self._aliases()).resolve_many([r["名字"] for r in rows])
        return {c for _, c in ok}, bad

    def _tier(self, code):
        if code in self.endemic:
            return TIER_ENDEMIC
        if (self.home_codes and code not in self.home_codes) \
                or self.t.family(code) in self.fams \
                or code in self.named:
            return TIER_KEY
        return TIER_OTHER

    # ---------- 派生信息 ----------

    def is_lifer(self, code):
        """生涯新种：目的地有、母语区名录没有。母语区名录缺失时返回 None。"""
        if not self.home_codes:
            return None
        return code not in self.home_codes

    def best_sites(self, code, limit=3):
        """按频次从高到低列出该种最好的点位。盲区点位单独标。"""
        fam = self.t.family(code)
        out = []
        for s in self.sites:
            if self.opp.blind_spot(code, s, fam):
                out.append((s, None, "盲区"))
                continue
            f = self.opp.freq_at(code, s)
            if f:
                out.append((s, f, ""))
        ranked = sorted([x for x in out if x[1] is not None],
                        key=lambda x: -x[1])[:limit]
        blind = [x for x in out if x[2] == "盲区"]
        return ranked + blind

    def opportunities(self, code):
        return self.opp.opportunities(code, self.sites, self.t.family(code))

    def has_data(self, code):
        return self.opp.has_any_data(code, self.sites)


def site_labels(cfg):
    return {s["id"]: s["名称"] for s in cfg.sites}


def render(cat):
    t, cfg = cat.t, cat.cfg
    labels = site_labels(cfg)
    by_tier = {k: [] for k in TIER_NAME}
    for c in cat.all_codes:
        by_tier[cat.tiers[c]].append(c)
    for k in by_tier:
        by_tier[k].sort(key=t.taxon_order)

    L = []
    A = L.append
    A(f"# {cfg.meta.get('title', cfg.meta.get('id', ''))} · 鸟种清单")
    A("")
    A(f"**{len(cat.all_codes)} 种**："
      + " + ".join(f"{TIER_NAME[k]} {len(by_tier[k])}" for k in sorted(by_tier))
      + f"。地区 `{cfg.region}`，取样窗口 {cfg.meta['ebird_window']} × "
      + "/".join(str(y) for y in cfg.years) + "。")
    A("")
    A("本册只回答**有哪些鸟、怎么叫**。每天在哪找、怎么找见现场手册；"
      "预计能看到多少种见预期产出。")
    A("")

    # ---- 口径说明：这些是最容易被误读的地方，必须写在最前面 ----
    A("## 读这份清单之前")
    A("")
    A("| 列 | 含义 | 陷阱 |")
    A("|---|---|---|")
    A("| **English** | 要**原样报给当地鸟导**的字符串。用老牌图鉴常用名（IOC 口径）|"
      " 错一个字母对方就查不到鸟 |")
    A("| 中文名 | 来自 IOC World Bird List 多语种版，**只是显示标签** |"
      " 不参与任何判定；查不到的只写英文名，**不编造** |")
    A("| 频次 | 取样窗口内，该点位**有多少比例的观鸟日报到了这种鸟**，自带分母 |"
      " **0% ≠ 看不到**；**频次 ≠ 难度** |")
    A("| 盲区 | 该点位对该种**取不到数据**，而不是「没有」 |"
      " 远洋海鸟在陆基热点上全是 0，因为它们是在船上看的 |")
    A("")
    # 这条提醒对任何行程都成立，所以**不要在这里举某一趟的具体鸟种**——
    # 那样泰国的清单里会印着斯里兰卡的例子。具体案例归 docs/方法论.md。
    A("> **频次回答「在不在」，不回答「好不好找」。** "
      "同样的频次，林内靠听声定位的种可能要找几天，"
      "而开阔地有固定停歇点的种可能十分钟就到手。"
      "频次高不等于轻松，频次低也不等于没戏——"
      "要判断难度，得结合生境、行为和现场经验。")
    A("")
    A(f"> **数据源**：物种、分布、频次一律 eBird（`{cfg.region}` 地区名录 "
      f"{len(cat.all_codes)} 种）。中文名来自 IOC 多语种版。"
      f"**第三方数据只用于比对，不覆盖 eBird。**")
    A("")

    # ---- 分档说明 ----
    A("## 分档口径")
    A("")
    A("| 档 | 判定 | 怎么来的 |")
    A("|---|---|---|")
    A(f"| 特有种 {len(by_tier[TIER_ENDEMIC])} 种 | 只在 `{cfg.region}` 出现 |"
      f" eBird 全部 253 个地区名录倒排，**零人工名单** |")
    key_why = ["生涯新种"] if cat.home_codes else []
    key_why += [f"{len(cat.fams)} 个关注科目"]
    if cat.named:
        key_why.append("用户点名")
    A(f"| 重点关注 {len(by_tier[TIER_KEY])} 种 | " + " ∪ ".join(key_why)
      + " | eBird + 行程配置 |")
    A(f"| 其它 {len(by_tier[TIER_OTHER])} 种 | 以上都不是 | eBird 地区名录 |")
    A("")
    if cat.home_codes:
        n_lifer = sum(1 for c in cat.all_codes if cat.is_lifer(c))
        A(f"> **生涯新种 {n_lifer} 种**：`{cfg.region}` 有记录、"
          f"而母语区 `{cat.home_region}`（{len(cat.home_codes)} 种）"
          f"没有记录的种。按 eBird 两份地区名录直接相减得到。")
        A("")
    if cat.n_nonspecies:
        A(f"> 地区名录里另有 {cat.n_nonspecies} 个**非种级分类单元**"
          f"（亚种群等），已排除。")
        A("")

    # ---- 三档表格 ----
    for tier in sorted(TIER_NAME):
        codes = by_tier[tier]
        if not codes:
            continue
        A(f"## {TIER_NAME[tier]}（{len(codes)} 种）")
        A("")
        A("| ☐ | 鸟种 | English | 学名 | 科 | 最好的点位（频次）|")
        A("|:-:|---|---|---|---|---|")
        for c in codes:
            zh = t.zh(c)
            lifer = "✦" if cat.is_lifer(c) else ""
            best = cat.best_sites(c)
            if best:
                cell = "、".join(
                    f"{labels.get(s, s)} {f'{f:.0%}' if f is not None else '盲区'}"
                    for s, f, _ in best)
            else:
                cell = "—（本行程点位无数据）"
            A(f"| ☐ | {zh or '—'}{lifer} | **{t.en(c)}** | *{t.sci(c)}* "
              f"| {t.family(c)} | {cell} |")
        A("")
        if tier == TIER_ENDEMIC:
            A("> `✦` = 生涯新种。特有种天然都是生涯新种，标记省略。")
            A("")
        elif tier == TIER_KEY:
            A("> `✦` = 生涯新种（母语区无记录）。")
            A("")

    # ---- 无数据的种：必须单列，不能当成 0 ----
    nodata = [c for c in cat.all_codes if not cat.has_data(c)]
    if nodata:
        A(f"## 本行程点位无数据的 {len(nodata)} 种")
        A("")
        A("**这些种不是「看不到」，是「没数据」**——两者必须分开。"
          "它们不参与排序，也不计入预期种数的点估计。")
        A("")
        A("常见原因：① 远洋海鸟（在船上看，陆基热点取不到）"
          "② 该种在本地区本就罕见，取样窗口内无人报到"
          "③ 行程点位确实不覆盖它的分布区。")
        A("")
        A("| 鸟种 | English | 科 | 档 |")
        A("|---|---|---|---|")
        for c in sorted(nodata, key=t.taxon_order):
            A(f"| {t.zh(c) or '—'} | {t.en(c)} | {t.family(c)} "
              f"| {TIER_NAME[cat.tiers[c]]} |")
        A("")

    # ---- 未解析的点名 ----
    if cat.named_bad:
        A("## ⚠ 配置里未能解析的名字")
        A("")
        A("这些写在 `targets.md` 里但解析不出 eBird code。"
          "**脚本不猜**——请核对叫法或加别名。")
        A("")
        for nm, why in cat.named_bad:
            A(f"- `{nm}` —— {why}")
        A("")

    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    cat = Catalog(a.trip)
    body = render(cat)
    out = Path(a.out) if a.out else cat.cfg.dir / "out" / "01-鸟种清单.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")

    n = {k: sum(1 for c in cat.all_codes if cat.tiers[c] == k)
         for k in TIER_NAME}
    print(f"写出 {out}  ({len(body.splitlines())} 行)")
    print(f"  {len(cat.all_codes)} 种 = "
          + " + ".join(f"{TIER_NAME[k]} {n[k]}" for k in sorted(n)))
    nodata = sum(1 for c in cat.all_codes if not cat.has_data(c))
    print(f"  无数据 {nodata} 种（单列，不计入点估计）")
    cov = cat.t.zh_coverage(cat.all_codes)
    print(f"  中文名覆盖 {cov['total'] - len(cov['missing'])}/{cov['total']}")
    if cat.named_bad:
        print(f"  ⚠ {len(cat.named_bad)} 个配置名字未解析")


if __name__ == "__main__":
    main()
