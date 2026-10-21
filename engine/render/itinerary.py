#!/usr/bin/env python3
"""渲染**第二份主交付：行程表**——每天在什么地方、关注什么鸟、是否夜探。

用法:
    python3 -I engine/render/itinerary.py --trip trips/<id>

与鸟种清单的分工（**不重叠**）
------------------------------
清单回答「有哪些鸟、怎么叫」，**鸟种详情只在清单里**；
本册回答「什么时候、在哪、找什么」，**只给简单中文名和排序**，
不重复学名、科、频次明细——要报给鸟导的英文名去清单里查。

每个时段算出什么
----------------
1. **本段重点**：该点位有有效机会的种，按频次排序，特有种优先；
2. **错过即无**：全程**只有这一个时段**有机会的种——这是行程表最有价值的一列，
   它直接回答「今天不拼一把，这趟就没了」；
3. **夜探目标**：夜行类群在该点位的机会（夜探时段才列）；
4. **非鸟目标**：safari / 夜探时段附带，**明标无 eBird 数据**。

「错过即无」怎么算（容易算错的地方）
------------------------------------
不是「只有一个点位有机会」，而是「**只有一个时段**有机会」——
同一个点位去两次，就不算错过即无。所以要按**时段**而不是按点位去统计，
`transfer` / `rest` 形式的时段不提供机会（见 `MODE_WEIGHT`）。

活动形式
--------
`形式` 一列驱动三件事：本段是否产出鸟种、概率模型的权重、以及本册的章节口吻。
`rest` 不产出；`transfer` 产出但明确标成「沿途机会，不要硬停」。
"""
import argparse
import sys
from collections import OrderedDict
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
sys.path.insert(0, str(ENGINE / "render"))
import mdtable as M                                      # noqa: E402
from species_list import Catalog, TIER_ENDEMIC, TIER_KEY, TIER_NAME  # noqa: E402

# 夜行类群（eBird familyComName）。判断：这些科主要在夜间活动。
NIGHT_FAMILIES = {
    "Owls", "Barn-Owls", "Frogmouths", "Nightjars and Allies",
    "Owlet-nightjars", "Potoos",
}

# 不产出观鸟机会的形式。`transfer` 产出但很弱，不在这里。
NO_YIELD_MODES = {"rest"}

MODE_DESC = {
    "birding": "常规观鸟",
    "safari": "车上观察（覆盖广、停留少）",
    "hike": "徒步（以赶路为主）",
    "pelagic": "出海",
    "night-walk": "夜探（步行）",
    "night-drive": "夜探（车行）",
    "transfer": "转场，沿途机会",
    "rest": "休息",
}


def blocks_of(cat):
    """把 itinerary.md 读成按日期分组的时段列表。"""
    days = OrderedDict()
    for b in cat.itin:
        days.setdefault(b["日期"], []).append(b)
    return days


def yielding(b):
    """这个时段是否产出观鸟机会。"""
    return (b["点位"] not in ("", "—")
            and b["形式"] not in NO_YIELD_MODES)


def is_night(b):
    """这个时段是不是夜间活动。"""
    return bool(b["夜探"].strip()) or b["形式"].startswith("night")


def block_targets(cat, b):
    """该时段有有效机会的种，按（档，频次）排序。

    **夜间时段只算夜行类群**
    ------------------------
    eBird 的频次是**按点位算的，不含时段信息**——
    一份 2 月的清单里绝大多数是白天提交的。
    所以把它原样套到夜探时段上，会把当天白天的全部种重复列一遍
    （实测 Yala 的夜探段曾原样重复了白天的 132 种），
    既无用又会让人误以为夜里真能看到这些。

    诚实的做法：**夜间时段只列夜行类群**，并在文档里说明
    「这不是说夜里只有这些鸟，而是数据只支持对这些鸟下结论」。
    白天时段**不**反过来排除夜行类群——鸮类白天在 roost 被定点是常规操作。
    """
    if not yielding(b):
        return []
    site = b["点位"]
    night = is_night(b)
    out = []
    for c in cat.all_codes:
        if night and cat.t.family(c) not in NIGHT_FAMILIES:
            continue
        if site not in cat.opportunities(c):
            continue
        f = cat.opp.freq_at(c, site)
        out.append((c, f if f is not None else 0.0))
    out.sort(key=lambda x: (cat.tiers[x[0]], -x[1]))
    return out


def only_chance(cat, days):
    """全程**只有一个时段**有机会的种 -> 那个时段的 key。

    按时段算而不是按点位算：同一个点位去两次就不算错过即无。
    """
    where = {}
    for date, bs in days.items():
        for i, b in enumerate(bs):
            if not yielding(b):
                continue
            for c in cat.opportunities_cache.get((date, i), ()):
                where.setdefault(c, []).append((date, i))
    return {c: v[0] for c, v in where.items() if len(v) == 1}


def render(cat):
    cfg = cat.cfg
    t = cat.t
    labels = {s["id"]: s["名称"] for s in cfg.sites}
    days = blocks_of(cat)

    # 预先算好每个时段的机会集合，供「错过即无」复用
    cat.opportunities_cache = {}
    tgt = {}
    for date, bs in days.items():
        for i, b in enumerate(bs):
            rows = block_targets(cat, b)
            tgt[(date, i)] = rows
            cat.opportunities_cache[(date, i)] = {c for c, _ in rows}
    once = only_chance(cat, days)

    L = []
    A = L.append
    A(f"# {cfg.meta.get('title', cfg.meta.get('id', ''))} · 行程表")
    A("")
    n_block = sum(len(v) for v in days.values())
    A(f"{len(days)} 天 / {n_block} 个时段。"
      f"每天在什么地方、关注什么鸟、是否夜探。")
    A("")
    A("本册**只给简单中文名和排序**。要报给当地鸟导的英文名、学名、"
      "科、各点位频次明细，去 [鸟种清单](01-鸟种清单.md) 查——两册不重叠。")
    A("")

    A("## 怎么用这份表")
    A("")
    A("| 栏 | 含义 |")
    A("|---|---|")
    A("| **错过即无** | 全程**只有这一个时段**有机会的种。这是本表最该先看的一栏——"
      "它回答「今天不拼，这趟就没了」|")
    A("| 本段重点 | 该点位有有效机会的种，特有种优先，其余按频次排 |")
    A("| 夜探目标 | 夜行类群在该点位的机会 |")
    A("| 形式 | 决定这一段怎么走：车上、徒步、出海、还是纯休息 |")
    A("")
    A("> **「有效机会」的口径只有一处**：`engine/opportunity.py`。"
      "简述：eBird 频次达标，或 GBIF 记录达标且未被 eBird 的零记录否决。"
      "远洋海鸟在陆基热点上是**结构性盲区**，不按 0 处理。")
    A("")

    # ---- 全程「错过即无」总览：放在最前面，因为它最该先看 ----
    if once:
        A(f"## 全程「错过即无」总览（{len(once)} 种）")
        A("")
        A("| 日期 | 时段 | 地点 | 种数 | 其中特有种 |")
        A("|---|---|---|---:|---|")
        by_block = {}
        for c, k in once.items():
            by_block.setdefault(k, []).append(c)
        for date, bs in days.items():
            for i, b in enumerate(bs):
                cs = by_block.get((date, i))
                if not cs:
                    continue
                ends = [c for c in cs if cat.tiers[c] == TIER_ENDEMIC]
                A(f"| {date} | {b['时段']} | {b['地点']} | {len(cs)} "
                  f"| {'、'.join(t.zh(c) or t.en(c) for c in sorted(ends, key=t.taxon_order)) or '—'} |")
        A("")

    # ---- 逐日 ----
    for date, bs in days.items():
        night = any(b["夜探"].strip() for b in bs)
        A(f"## {date}" + ("　🌙 有夜探" if night else ""))
        A("")
        for i, b in enumerate(bs):
            mode = b["形式"]
            site = b["点位"]
            head = f"### {b['时段']}　{b['地点']}"
            A(head)
            A("")
            meta = [f"**形式** {mode}（{MODE_DESC.get(mode, '')}）"]
            if site not in ("", "—"):
                meta.append(f"**点位** {labels.get(site, site)}")
            if b["带队"] not in ("", "—"):
                meta.append(f"**带队** {b['带队']}")
            if b["夜探"].strip():
                meta.append("**夜探**")
            A("　｜　".join(meta))
            A("")
            if b.get("说明"):
                A(f"> {b['说明']}")
                A("")

            rows = tgt[(date, i)]
            if not yielding(b):
                A("_本段不安排观鸟产出。_")
                A("")
                continue
            if not rows:
                A("_该点位在取样窗口内没有达标的机会种。_")
                A("")
                continue

            mine = [c for c, _ in rows if once.get(c) == (date, i)]
            if mine:
                A(f"**⚠ 错过即无（{len(mine)} 种）**　"
                  + "、".join(f"**{t.zh(c) or t.en(c)}**"
                              for c in sorted(mine, key=t.taxon_order)))
                A("")

            if is_night(b):
                A(f"**夜探目标（{len(rows)} 种夜行类群有机会）**")
                A("")
                A("| 鸟种 | 档 | 频次 |")
                A("|---|---|---:|")
                for c, f in rows:
                    star = "✦" if cat.is_lifer(c) else ""
                    A(f"| {t.zh(c) or t.en(c)}{star} "
                      f"| {TIER_NAME[cat.tiers[c]]} | {f:.0%} |")
                A("")
                A("> 本段**只列夜行类群**：eBird 的频次按点位统计、"
                  "**不含时段信息**，无法支持对夜间看到白天那些鸟下结论。"
                  "不是说夜里只有这些——是数据只够说这些。")
                A("")
            else:
                top = rows[:12]
                A(f"**本段重点（共 {len(rows)} 种有机会，列前 {len(top)}）**")
                A("")
                A("| 鸟种 | 档 | 频次 |")
                A("|---|---|---:|")
                for c, f in top:
                    star = "✦" if cat.is_lifer(c) else ""
                    A(f"| {t.zh(c) or t.en(c)}{star} "
                      f"| {TIER_NAME[cat.tiers[c]]} | {f:.0%} |")
                A("")

    A("---")
    A("")
    A("> `✦` = 生涯新种（母语区无记录）。")
    A("> 频次 = 取样窗口内该点位报到此种的观鸟日比例，**自带分母**。"
      "**频次回答「在不在」，不回答「好不好找」。**")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    cat = Catalog(a.trip)
    body = render(cat)
    out = Path(a.out) if a.out else cat.cfg.dir / "out" / "02-行程表.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    days = blocks_of(cat)
    print(f"写出 {out}  ({len(body.splitlines())} 行)")
    print(f"  {len(days)} 天 / {sum(len(v) for v in days.values())} 个时段")


if __name__ == "__main__":
    main()
