#!/usr/bin/env python3
"""概率模型：**这趟预计能看到多少种**，给点估计 + 80% 区间。

用法:
    python3 -I engine/estimate.py --trip trips/<id>
    python3 -I engine/estimate.py --trip trips/<id> --calibrate <参考行程.md>

模型
----
对每个种 `s`、每个时段 `j`（点位 `k`）：

    e[j]   = clamp(时长h / ref_hours, 0.25, E_CAP) × guide_mult × mode_mult
    p[s,j] = 1 - (1 - f[s,k]) ** e[j]
    P[s]   = 1 - Π_j (1 - p[s,j])

    E[总数] = Σ P[s]
    Var     = Σ P[s]·(1 - P[s])
    80% 区间 = E ± 1.2816·√Var

`f[s,k]` 是 eBird 频次（**数据**：取样窗口内该点位报到此种的观鸟日比例，自带分母）。
`e[j]` 是「有效观鸟日当量」——把一个时段折算成多少个「标准 eBird 观鸟日」。
**所有乘数都是判断**，全部在 `trips/<id>/trip.md` 里，且会被原样印进输出文档。

三条纪律（都是防自欺的）
------------------------
1. **无数据的种不按 0 计。**
   没有 eBird 数据 ≠ 看不到。这些种单列成一节，**不进点估计**。
   最典型的是远洋海鸟：它们在所有陆基热点上都是 0，
   因为是在船上看的（见 `engine/opportunity.py` 的盲区一节）。

2. **独立性假设必须声明。**
   `P[s] = 1 - Π(1-p)` 假设各时段相互独立。现实里不独立：
   下雨会同时毁掉所有时段，鸟导水平会同时影响全程。
   这种相关性**不进方差**（否则区间会假装自己涵盖了它），
   改用**敏感性表**单独表达：「某点泡汤 → 少多少种」。

3. **校准要留痕，不静默调参。**
   `--calibrate` 拿一份有实测总数的参考行程喂进同一模型，
   比对预测 vs 实际，把偏差报出来。
   **偏差不会被自动用来修正参数**——要改就人工改 `trip.md` 并写明理由。

为什么是「观鸟日当量」而不是直接按小时
--------------------------------------
eBird 的频次分母是「观鸟日」，不是小时。一份清单可能是 1 小时也可能是 8 小时。
所以唯一自洽的做法是把时段折算成「相当于几个这样的观鸟日」，
`ref_hours` 就是「一个典型观鸟日折合几小时」这个判断。

⚠ 当量为什么**封顶在 1.0**（2026-10-20 修，这是个真实的高估 bug）
----------------------------------------------------------------
`f[s,k]` 的定义是「该点位有多少比例的**观鸟日**报到此种」，而一个「观鸟日」
是**那天该点位所有观察者、所有热点的清单并集**——不是一个人的一次外出。

原先当量封顶在 2.0，于是一个 6 小时的鸟导时段被折算成 `6/4 × 1.35 = 2.02`
个观鸟日，意思是「我们两个人半天的发现量，是全站所有人一整天的两倍」。
这显然不成立。

**暴露它的是泰国 2 天 demo：3 个时段预测出 231 种。**
斯里兰卡 10 天预测 215 种看着合理，把这个偏差完全掩盖了——
所以通用性验收不只是验证「换国家能跑」，它还会抓出被单一样本掩盖的模型错误。

现在封顶 `E_CAP = 1.0`：**一次外出最多等于一个观鸟日，不可能超过。**
实际上通常更低（我们是一队人，而观鸟日是所有人的并集），
这部分由 `party_factor` 表达，它是一个显式的判断参数。
"""
import argparse
import json
import math
import re
import sys
from collections import OrderedDict
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
sys.path.insert(0, str(ENGINE / "render"))
import mdtable as M                                      # noqa: E402
from species_list import (Catalog, TIER_ENDEMIC, TIER_KEY,   # noqa: E402
                          TIER_OTHER, TIER_NAME)

Z80 = 1.2815515655446004      # 标准正态 90% 分位，用于 80% 双侧区间

# 时段文字解析不出时长时，按形式给的兜底时长（判断）。
# **每次用到兜底都会被列进输出文档**，不静默使用。
MODE_FALLBACK_HOURS = {
    "birding": 3.0, "safari": 8.0, "hike": 5.0, "pelagic": 4.0,
    "night-walk": 2.0, "night-drive": 2.0, "transfer": 3.0, "rest": 0.0,
}

# 单个时段的当量上限。见模块文档：一次外出最多等于一个 eBird 观鸟日。
E_CAP = 1.0

_HHMM = re.compile(r"(\d{1,2}):(\d{2})\s*[–\-~至]\s*(\d{1,2}):(\d{2})")
_NH = re.compile(r"(\d+(?:\.\d+)?)\s*[–\-~]\s*(\d+(?:\.\d+)?)\s*h")
_1H = re.compile(r"(\d+(?:\.\d+)?)\s*h")


def parse_hours(text, mode):
    """把时段文字解析成小时数。返回 `(小时, 来源)`。

    能解析的写法：`05:00–17:00`、`晚上 1–2h`、`19:30–21:00`。
    解析不出的（`上午`、`下午`、`05:30–全天`）走形式兜底，
    **并在 `来源` 里标明是兜底**——调用方必须把它列出来给人看。
    """
    s = (text or "").strip()
    m = _HHMM.search(s)
    if m:
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        if b < a:                     # 跨午夜
            b += 24 * 60
        return (b - a) / 60.0, "时段文字"
    m = _NH.search(s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0, "时段文字"
    m = _1H.search(s)
    if m:
        return float(m.group(1)), "时段文字"
    return MODE_FALLBACK_HOURS.get(mode, 3.0), "形式兜底"


def guide_weight(text, table):
    """带队文字 -> 乘数。按 `trip.md` 的 `guide_mult` 表做**子串匹配**。

    子串匹配而不是精确匹配：`带队` 一列的写法很随意
    （`鸟导（Seg1）`、`酒店专业鸟导（核心）`、`鸟导兼司机（打包内）`），
    不可能穷举。匹配不上就取 1.0 并报出来。
    """
    s = (text or "").strip()
    best, key = None, None
    for k, v in table.items():
        if k and k in s:
            # 命中多个时取乘数最大的（`顶级` 比 `鸟导` 更具体）
            if best is None or v > best:
                best, key = v, k
    return (best, key) if best is not None else (1.0, None)


class Model:
    def __init__(self, cat):
        self.cat = cat
        meta = cat.cfg.meta
        self.ref_hours = float(meta.get("ref_hours", "4.0"))
        # 「我们一队人」相对「该点位当天所有观察者的并集」的发现率折扣。
        # 判断参数：1.0 表示不折扣（偏乐观）。会被印进输出文档。
        self.party_factor = float(meta.get("party_factor", "1.0"))
        self.guide_mult = {k: float(v) for k, v in
                           M.parse_pairs(meta.get("guide_mult", "")).items()}
        self.mode_mult = {k: float(v) for k, v in
                          M.parse_pairs(meta.get("mode_mult", "")).items()}
        self.blocks = self._blocks()

    def _blocks(self):
        """把行程时段算成 `[(日期, 时段文字, 点位, e, 诊断)]`。"""
        out = []
        for b in self.cat.itin:
            mode = b["形式"]
            site = b["点位"]
            hours, hsrc = parse_hours(b["时段"], mode)
            gm, gkey = guide_weight(b["带队"], self.guide_mult)
            mm = self.mode_mult.get(mode, 1.0)
            # 封顶作用在**最终当量**上：不论谁带队、什么形式，
            # 一次外出都不可能超过「该点位当天所有观察者的清单并集」。
            # 曾经把封顶加在时长折算上、再乘鸟导系数，
            # 结果 6h 鸟导时段的当量是 1.35——又越过了上限。
            eff = min(max(hours / self.ref_hours, 0.25) * gm * mm,
                      E_CAP) * self.party_factor
            if site in ("", "—") or mm == 0:
                eff = 0.0
            out.append({
                "date": b["日期"], "time": b["时段"], "place": b["地点"],
                "site": site, "mode": mode, "guide": b["带队"],
                "hours": hours, "hours_src": hsrc,
                "guide_mult": gm, "guide_key": gkey, "mode_mult": mm,
                "e": eff, "night": bool(b["夜探"].strip()),
            })
        return out

    # ---------- 核心 ----------

    def p_species(self, code, blocks=None):
        """该种在整趟行程里被看到的概率。无任何数据返回 `None`。"""
        cat = self.cat
        fam = cat.t.family(code)
        miss = 1.0
        saw_data = False
        for b in (blocks if blocks is not None else self.blocks):
            if b["e"] <= 0 or b["site"] in ("", "—"):
                continue
            if cat.opp.blind_spot(code, b["site"], fam):
                continue
            f = cat.opp.freq_at(code, b["site"])
            if f is None:
                continue
            saw_data = True
            if f <= 0:
                continue
            miss *= (1.0 - f) ** b["e"]
        return (1.0 - miss) if saw_data else None

    def run(self, blocks=None):
        """跑一遍模型。返回 `(每种概率, 分档统计, 无数据的种)`。"""
        probs, nodata = {}, []
        for c in self.cat.all_codes:
            p = self.p_species(c, blocks)
            if p is None:
                nodata.append(c)
            else:
                probs[c] = p
        per_tier = {}
        for tier in (TIER_ENDEMIC, TIER_KEY, TIER_OTHER):
            cs = [c for c in probs if self.cat.tiers[c] == tier]
            e = sum(probs[c] for c in cs)
            v = sum(probs[c] * (1 - probs[c]) for c in cs)
            per_tier[tier] = {"n": len(cs), "E": e, "sd": math.sqrt(v)}
        e = sum(probs.values())
        v = sum(p * (1 - p) for p in probs.values())
        return probs, {"per_tier": per_tier, "n": len(probs), "E": e,
                       "sd": math.sqrt(v),
                       "lo": e - Z80 * math.sqrt(v),
                       "hi": e + Z80 * math.sqrt(v)}, nodata

    def ceiling(self):
        """每个点位「一个观鸟日的期望种数」= Σ freq。

        这是**模型的天花板诊断**，也是判断预测可信度的关键一问：
        `Σfreq` 的含义是「该点位当天**所有观察者、所有热点的清单并集**
        平均记录多少种」。当量封顶 1.0 意味着
        **我们一队人最多拿到这个数**——拿不到更多。

        为什么必须把它印出来：各地区的 eBird 数据密度差异极大。
        实测 Sinharaja 的 Σfreq 只有 32（林内难看、清单短），
        而泰国 Kaeng Krachan 是 156（点位极富、被观鸟人密集覆盖）。
        同一个模型在前者偏保守、在后者偏乐观——
        **不把这个数摆出来，用户无法判断预测该打几折。**
        """
        rows = []
        for s in self.cat.sites:
            tot = n = 0.0
            cnt = 0
            for c in self.cat.all_codes:
                f = self.cat.opp.freq_at(c, s)
                if f is not None:
                    tot += f
                    cnt += 1
            blocks = [b for b in self.blocks if b["site"] == s]
            rows.append({"site": s, "sum_freq": tot, "n_species": cnt,
                         "denom": self.cat.opp.denom.get(s, 0),
                         "e_total": sum(b["e"] for b in blocks),
                         "n_blocks": len(blocks)})
        return rows

    # ---------- 敏感性 ----------

    def sensitivity(self):
        """逐点位「泡汤」与关键参数扰动的影响。

        这是表达**相关性风险**的地方——相关性不进方差（见模块文档纪律 2），
        所以必须用场景表单独说。

        **为什么同时给总种数和特有种数**
        --------------------------------
        只看总种数会误导。实测这趟：按总种数算 Bundala 的影响（-26）
        几乎是 Sinharaja（-14）的两倍，因为 Bundala 有二十多种
        只在那儿能见到的滨鹬。但**这趟真正的命脉是 35 种特有种**，
        而特有种几乎全在 Sinharaja 一侧——
        丢掉 Bundala 损失的是「数量」，丢掉 Sinharaja 损失的是「目标」。
        所以两列必须一起看，不能只排总数。
        """
        _, b0, _ = self.run()
        base, base_end = b0["E"], b0["per_tier"][TIER_ENDEMIC]["E"]

        def delta(blocks):
            _, st, _ = self.run(blocks)
            return (st["E"] - base,
                    st["per_tier"][TIER_ENDEMIC]["E"] - base_end)

        rows = []
        for s in self.cat.sites:
            kept = [b for b in self.blocks if b["site"] != s]
            rows.append((f"{s} 完全泡汤",) + delta(kept))
        rows.append(("全程效率减半（连日大雨/身体不适）",)
                    + delta([dict(b, e=b["e"] * 0.5) for b in self.blocks]))
        rows.append(("完全没有鸟导（全部按自助算）",)
                    + delta([dict(b, e=b["e"] / max(b["guide_mult"], 1e-9))
                             for b in self.blocks]))
        for rh in (3.0, 6.0):
            save = self.ref_hours
            self.ref_hours = rh
            rows.append((f"ref_hours 取 {rh}（现 {save:g}）",)
                        + delta(self._blocks()))
            self.ref_hours = save
        return (base, base_end), rows


def render(model, probs, stat, nodata):
    cat = model.cat
    t, cfg = cat.t, cat.cfg
    labels = {s["id"]: s["名称"] for s in cfg.sites}
    L, A = [], None
    L = []
    A = L.append

    A(f"# {cfg.meta.get('title', cfg.meta.get('id', ''))} · 预期产出")
    A("")
    A(f"## 预计 **{stat['E']:.0f} 种**"
      f"（80% 区间 **{max(0, stat['lo']):.0f}–{stat['hi']:.0f}**）")
    A("")
    A("| 档 | 目标种数 | 预期命中 | 命中率 |")
    A("|---|---:|---:|---:|")
    for tier in (TIER_ENDEMIC, TIER_KEY, TIER_OTHER):
        d = stat["per_tier"][tier]
        if not d["n"]:
            continue
        A(f"| {TIER_NAME[tier]} | {d['n']} | **{d['E']:.0f}** "
          f"| {d['E'] / d['n']:.0%} |")
    A(f"| **合计** | **{stat['n']}** | **{stat['E']:.0f}** "
      f"| {stat['E'] / max(stat['n'], 1):.0%} |")
    A("")
    A(f"> 另有 **{len(nodata)} 种无 eBird 数据**，"
      f"**不计入上表**——见文末。它们不是「看不到」，是「没数据」。")
    A("")

    # ---- 假设表：必须和数字一起出现 ----
    A("## 这个数字建立在什么假设上")
    A("")
    A("**模型**")
    A("")
    A("```")
    A("e[j]   = clamp(时长h / ref_hours, 0.25, 2.0) × guide_mult × mode_mult")
    A("p[s,j] = 1 - (1 - f[s,k]) ** e[j]        # f = eBird 频次（数据）")
    A("P[s]   = 1 - Π_j (1 - p[s,j])")
    A("E      = Σ P[s]    Var = Σ P[s](1-P[s])    80% 区间 = E ± 1.2816√Var")
    A("```")
    A("")
    A(f"**判断参数**（全部在 `trip.md` 里，改那里即可）")
    A("")
    A(f"- `ref_hours` = **{model.ref_hours}** —— 一个「标准 eBird 观鸟日」"
      f"折合几小时。eBird 的频次分母是观鸟日而不是小时，必须有这个折算。"
      f"取大则预测偏低。")
    A(f"- **当量上限 `E_CAP` = {E_CAP}** —— 一次外出**最多等于一个观鸟日**。"
      f"而一个「观鸟日」是该点位当天**所有观察者、所有热点的清单并集**，"
      f"所以我们一队人不可能超过它。"
      f"（这里原先封顶 2.0，被泰国 2 天 demo 抓出来："
      f"3 个时段预测出 231 种。）")
    A(f"- `party_factor` = **{model.party_factor}** —— 我们一队人相对"
      f"「所有观察者并集」的发现率折扣。取 1.0 是**偏乐观**的，"
      f"真实值应当更低；要更保守就在 `trip.md` 里下调。")
    A(f"- `guide_mult` = "
      + "、".join(f"{k} {v}" for k, v in sorted(model.guide_mult.items())))
    A(f"- `mode_mult` = "
      + "、".join(f"{k} {v}" for k, v in sorted(model.mode_mult.items())))
    A("")
    A("**独立性假设（最大的那个）**")
    A("")
    A("`P[s] = 1 - Π(1-p)` 假设各时段相互独立。**现实里不独立**："
      "连日大雨会同时毁掉所有时段，鸟导水平会同时影响全程。")
    A("")
    A("这种相关性**刻意不进方差**——否则 80% 区间会假装自己涵盖了它。"
      "改用下面的敏感性表单独表达。所以：**区间表达的是运气，"
      "敏感性表表达的是风险，两个要一起看。**")
    A("")

    # ---- 逐时段的权重，含兜底标记 ----
    A("## 各时段的有效当量")
    A("")
    fb = [b for b in model.blocks if b["hours_src"] == "形式兜底"]
    A("| 日期 | 时段 | 点位 | 形式 | 时长h | 鸟导× | 形式× | **当量 e** |")
    A("|---|---|---|---|---:|---:|---:|---:|")
    for b in model.blocks:
        mark = "ᶠ" if b["hours_src"] == "形式兜底" else ""
        gk = f"{b['guide_mult']:g}" + (f"({b['guide_key']})" if b["guide_key"] else "ᵘ")
        A(f"| {b['date']} | {b['time']} | {labels.get(b['site'], b['site'] or '—')} "
          f"| {b['mode']} | {b['hours']:g}{mark} | {gk} "
          f"| {b['mode_mult']:g} | **{b['e']:.2f}** |")
    A("")
    if fb:
        A(f"> `ᶠ` = **时长是按形式兜底的**（{len(fb)} 处）："
          f"时段文字里没有可解析的起止时刻。"
          f"要精确控制就在 `itinerary.md` 的 `时段` 列写成 `HH:MM–HH:MM`，"
          f"或写 `1–2h` 这样的时长。")
    A("> `ᵘ` = 带队文字没匹配上 `guide_mult` 表里任何一项，按 1.0 算。")
    A("")

    # ---- 天花板诊断：让高估/低估可见 ----
    A("## 模型天花板：这个预测该打几折")
    A("")
    A("`Σfreq` = 该点位**一个观鸟日的期望种数**，而「一个观鸟日」是"
      "**那天所有观察者、所有热点的清单并集**。")
    A("")
    A(f"当量封顶 `E_CAP = {E_CAP}` 意味着：**我们一队人在一个点位"
      f"最多拿到这个数，拿不到更多。** 所以 `Σfreq` 直接告诉你"
      f"预测的上限在哪。")
    A("")
    A("| 点位 | 有数据种数 | 观鸟日分母 | **Σfreq**（一个观鸟日期望种数）| 本行程时段数 | 当量合计 |")
    A("|---|---:|---:|---:|---:|---:|")
    for r in model.ceiling():
        A(f"| {labels.get(r['site'], r['site'])} | {r['n_species']} "
          f"| {r['denom']} | **{r['sum_freq']:.0f}** "
          f"| {r['n_blocks']} | {r['e_total']:.2f} |")
    A("")
    A("**怎么用这张表判断可信度：**")
    A("")
    A("- 某点位 `Σfreq` 很高而你只去半天 → 预测对该点位**偏乐观**，"
      "因为你一队人半天不可能顶全站一天；")
    A("- 某点位 `Σfreq` 很低（林内难看、清单短）→ 预测**偏保守**，"
      "有经验的鸟导能明显超出；")
    A("- `观鸟日分母` 很小（< 10）→ 频次本身统计噪声大，整段结论都要打问号。")
    A("")
    A(f"> **各地区的 eBird 数据密度差异极大**，所以同一个模型"
      f"在不同地区的偏向不同。实测对比：某低地雨林点 Σfreq 只有 32"
      f"（林内难看、清单短），而某被密集覆盖的山地国家公园是 156。"
      f"要整体调节就改 `trip.md` 的 `party_factor`"
      f"（现为 **{model.party_factor}**，1.0 是偏乐观的上限情形）。")
    A("")

    # ---- 敏感性 ----
    (base, base_end), rows = model.sensitivity()
    A("## 敏感性：什么情况下会少看多少种")
    A("")
    A("这张表表达的是**相关性风险**（上面的 80% 区间不含它）。")
    A("")
    A("**两列必须一起看。** 只排总种数会误导：丢掉滨海湿地损失的是「数量」，"
      "丢掉雨林损失的是「目标」——而这趟的命脉是特有种，不是总数。")
    A("")
    A("| 情景 | 总种数变化 | **特有种变化** |")
    A("|---|---:|---:|")
    for name, d, de in sorted(rows, key=lambda x: x[2]):
        A(f"| {name} | {d:+.0f} | **{de:+.1f}** |")
    A("")
    A(f"> 基准：总 {base:.0f} 种、特有种 {base_end:.1f}/35。")
    A("")

    # ---- 最该拼的种 ----
    A("## 概率最低的 25 种重点目标")
    A("")
    A("「重点」= 特有种 + 重点关注档。概率低的才是真正需要专门安排的——"
      "**高概率的不用操心，低概率的才决定这趟的上限**。")
    A("")
    key = [(c, probs[c]) for c in probs
           if cat.tiers[c] in (TIER_ENDEMIC, TIER_KEY)]
    key.sort(key=lambda x: x[1])
    A("| 鸟种 | English | 档 | 概率 | 最好的点位 |")
    A("|---|---|---|---:|---|")
    for c, p in key[:25]:
        best = cat.best_sites(c, 2)
        cell = "、".join(f"{labels.get(s, s)} {f:.0%}"
                         for s, f, _ in best if f is not None) or "—"
        A(f"| {t.zh(c) or '—'} | {t.en(c)} | {TIER_NAME[cat.tiers[c]]} "
          f"| **{p:.0%}** | {cell} |")
    A("")

    # ---- 几乎必中的 ----
    sure = [c for c in probs if probs[c] >= 0.99]
    A(f"> 另有 **{len(sure)} 种概率 ≥99%**，基本不用操心。")
    A("")

    # ---- 无数据 ----
    A(f"## 无 eBird 数据的 {len(nodata)} 种（不计入点估计）")
    A("")
    A("**「没数据」和「看不到」是两件事**，混淆它们会让预测凭空变低。")
    A("")
    A("三类原因：① **远洋海鸟**——在船上看，陆基热点取不到，"
      "是结构性盲区；② 该种在本地区本就罕见，取样窗口内无人报到；"
      "③ 行程点位确实不覆盖它的分布区。")
    A("")
    byfam = {}
    for c in nodata:
        byfam.setdefault(t.family(c), []).append(c)
    A("| 科 | 种数 | 鸟种 |")
    A("|---|---:|---|")
    for fam, cs in sorted(byfam.items(), key=lambda x: -len(x[1])):
        names = "、".join(t.zh(c) or t.en(c)
                          for c in sorted(cs, key=t.taxon_order))
        A(f"| {fam} | {len(cs)} | {names} |")
    A("")
    A(f"> **数据源**：频次一律 eBird（`{cfg.region}`，"
      f"{cfg.meta['ebird_window']} × "
      + "/".join(str(y) for y in cfg.years) + "）。")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    cat = Catalog(a.trip)
    model = Model(cat)
    probs, stat, nodata = model.run()
    body = render(model, probs, stat, nodata)
    out = Path(a.out) if a.out else cat.cfg.dir / "out" / "04-预期产出.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")

    print(f"写出 {out}  ({len(body.splitlines())} 行)")
    print(f"  预计 {stat['E']:.0f} 种"
          f"（80% 区间 {max(0, stat['lo']):.0f}–{stat['hi']:.0f}）")
    for tier in (TIER_ENDEMIC, TIER_KEY, TIER_OTHER):
        d = stat["per_tier"][tier]
        if d["n"]:
            print(f"    {TIER_NAME[tier]:6s} {d['E']:5.1f} / {d['n']:3d}"
                  f"  = {d['E'] / d['n']:.0%}")
    print(f"  无数据 {len(nodata)} 种，不计入")
    fb = sum(1 for b in model.blocks if b["hours_src"] == "形式兜底")
    if fb:
        print(f"  ⚠ {fb}/{len(model.blocks)} 个时段的时长按形式兜底"
              f"（时段文字无可解析的起止时刻）")


if __name__ == "__main__":
    main()
