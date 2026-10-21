#!/usr/bin/env python3
"""渲染**行前与物流**：租车/鸟导确认、报价核算、四层待办。

用法:
    python3 -I engine/render/logistics.py --trip trips/<id>

本册与另外两册**不重叠**
------------------------
鸟种详情只在鸟种清单里，每天找什么只在行程表里，
**本册完全不碰鸟种数据**——它回答的是「钱花得值不值、哪些事必须出发前办完」。

鸟导分段怎么来
--------------
不手写。从 `itinerary.md` 的 `带队` 一列**自动切分**：
连续若干个时段由同一方带队，就是一「段」。
这样行程一改，分段跟着变，不会出现「改了行程忘了改鸟导表」。

四层待办
--------
来自 `todos.md`，是这个项目最有价值的经验结构之一：

  ① 一次性，出发前办完
  ② 每位鸟导都走一遍（**模板**，按实际分段展开，不用对每位重想一遍）
  ③ 每个观鸟时段都做（**模板**，自助同样适用）
  ④ 某一段专属（渲染在行程表对应时段，不在本册重复）

**①②③ 在本册渲染，④ 在行程表渲染——两边不重复。**
④ 的 key 必须与 `itinerary.md` 的时段逐字对得上，由 verify 反向校验：
对不上的待办永远不会被渲染出来，等于丢了。

报价
----
`logistics.md` 的服务项目表给的是**市场行情量级的经验判断，不是报价**。
本模块只做算术（按人/按车/按次展开、折算汇率、给区间），
**不替任何数字背书**，并把免责声明原样印在最前面。
"""
import argparse
import sys
from collections import OrderedDict
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import mdtable as M                                      # noqa: E402
from ebird import TripConfig                             # noqa: E402

SELF_GUIDED = {"自助", "—", ""}

# 「指代上一位」的写法。实测行程表里会这么写：
#   `同上`、`同一位鸟导`、`续用同一位鸟导`
# 如果按字面当成不同的带队方，Yala 的日/夜会被拆成两段、
# Sinharaja 会被拆成四段——而 ② 层待办是「每位带队方走一遍」的模板，
# 段数翻倍就等于让人把同一件事对同一个人重复确认好几遍。
CONTINUATION_HINTS = ("同上", "同一位", "同一个", "续用", "同前")


def clean_guide(s):
    """去掉带队文字里的 Markdown 强调符。

    源行程表里有人写 `**高原鸟导**` 以示重要，渲染时我们还会再加一层粗体，
    结果变成 `****高原鸟导****`。强调归渲染管，数据里不留标记。
    """
    return (s or "").replace("*", "").strip()


def is_continuation(s):
    return any(h in s for h in CONTINUATION_HINTS)


def segments(itin):
    """按 `带队` 把时段切成连续的「段」。

    三条规则：
      1. 相邻时段的带队方相同 -> 并入同一段；
      2. 带队文字是「同上」这类**指代上一位**的 -> 也并入同一段；
      3. `自助`/`—` 不成段——那是自管项，没有要跟对方确认的东西，
         **但它不打断前后两段的连续性**（中间插一个自助时段，
         前后仍是同一位鸟导的话，应当还是一段）。
    """
    segs, cur = [], None
    for b in itin:
        g = clean_guide(b["带队"])
        if g in SELF_GUIDED:
            continue                      # 自管项：跳过，但不清空 cur
        if cur and (g == cur["guide"] or is_continuation(g)):
            cur["blocks"].append(b)
            continue
        cur = {"guide": g, "blocks": [b]}
        segs.append(cur)
    return segs


def money(cfg_rows, pax):
    """展开报价：按计价方式算出每项的低/高总价。"""
    out, lo_t, hi_t = [], 0.0, 0.0
    for r in cfg_rows:
        try:
            lo, hi = float(r["低USD"]), float(r["高USD"])
        except ValueError:
            continue
        mult = pax if r["计价"].strip() == "pax" else 1
        lo, hi = lo * mult, hi * mult
        lo_t += lo
        hi_t += hi
        out.append((r["项目"], lo, hi, r["计价"], r.get("说明", "")))
    return out, lo_t, hi_t


def render(cfg):
    itin = M.table(cfg.dir / "itinerary.md", "时段表")
    td = cfg.dir / "todos.md"
    lg = cfg.dir / "logistics.md"
    labels = {s["id"]: s["名称"] for s in cfg.sites}

    L, A = [], None
    L = []
    A = L.append
    A(f"# {cfg.meta.get('title', cfg.meta.get('id', ''))} · 行前与物流")
    A("")
    A("本册回答**风险在哪、钱花得值不值、哪些事必须出发前办完**。")
    A("")
    A("**不含任何鸟种数据**——要找鸟去 [行程表](02-行程表.md)，"
      "要报给鸟导的英文名去 [鸟种清单](01-鸟种清单.md)。三册不重叠。")
    A("")

    # ---------- 带队分段 ----------
    segs = segments(itin)
    A(f"## 带队分段（{len(segs)} 段）")
    A("")
    A("从行程表的 `带队` 一列**自动切分**：连续若干时段由同一方带队即为一段。"
      "行程一改，分段跟着变——不会出现「改了行程忘了改鸟导表」。")
    A("")
    A("| # | 带队方 | 时段数 | 起 | 止 | 涉及点位 |")
    A("|---:|---|---:|---|---|---|")
    for i, s in enumerate(segs, 1):
        bs = s["blocks"]
        sites = [labels.get(b["点位"], b["点位"])
                 for b in bs if b["点位"] not in ("", "—")]
        A(f"| {i} | **{s['guide']}** | {len(bs)} "
          f"| {bs[0]['日期']} {bs[0]['时段']} | {bs[-1]['日期']} {bs[-1]['时段']} "
          f"| {'、'.join(dict.fromkeys(sites)) or '—'} |")
    A("")

    # 自管项
    self_blocks = [b for b in itin if b["带队"].strip() in SELF_GUIDED]
    if self_blocks:
        A(f"### 自管项（{len(self_blocks)} 个时段，没人带）")
        A("")
        A("| 日期 | 时段 | 地点 | 形式 |")
        A("|---|---|---|---|")
        for b in self_blocks:
            A(f"| {b['日期']} | {b['时段']} | {b['地点']} | {b['形式']} |")
        A("")
        rest = sum(1 for b in self_blocks if b["形式"] in ("rest", "transfer"))
        A(f"> 其中 {rest} 个是转场或休息——**这些本来就不该安排观鸟**，"
          f"不是「缺口」。真正要自己扛的是另外 "
          f"{len(self_blocks) - rest} 个时段。")
        A("")

    # ---------- 报价 ----------
    if lg.exists():
        rows = M.table(lg, "服务项目")
        rate = {r["项"]: r["值"] for r in M.table(lg, "汇率")}
        pax = int(float(rate.get("人数", "2")))
        items, lo_t, hi_t = money(rows, pax)
        A("## 报价核算")
        A("")
        A("> ⚠ **下面每一个数都是市场行情量级的经验判断，不是任何运营商的报价。**")
        A("> 门票由园方定价、含多项税费且近年多次上调，"
          "**不要拿这里的数字去付款**。")
        A("> 拿到真实报价后改 `logistics.md` 的服务项目表再重建。")
        A("")
        A(f"按 {pax} 人计。`pax` 项已乘人数，`vehicle`/`svc` 按次计。")
        A("")
        A("| 项目 | 低 USD | 高 USD | 计价 | 说明 |")
        A("|---|---:|---:|---|---|")
        for name, lo, hi, per, note in items:
            A(f"| {name} | {lo:.0f} | {hi:.0f} | {per} | {note} |")
        A(f"| **合计** | **{lo_t:.0f}** | **{hi_t:.0f}** | | |")
        A("")
        try:
            cny = float(rate.get("LKR / CNY", "0"))
            usd = float(rate.get("LKR / USD", "0"))
            if cny and usd:
                A(f"> 折人民币约 **{lo_t * usd / cny:,.0f} – "
                  f"{hi_t * usd / cny:,.0f} 元**"
                  f"（按 1 USD = {usd:g} LKR、1 CNY = {cny:g} LKR；"
                  f"**汇率需自行核实**）。")
                A("")
        except ValueError:
            pass

    # ---------- 待办 ----------
    if td.exists():
        A("## 待办")
        A("")
        A("四层。**① ② ③ 在本册，④ 在行程表对应时段就地勾选**——两边不重复。")
        A("")
        A("> 级别：🔴 必须办完　🟡 问一句就行　🟢 到店再办")
        A("")

        one = M.table(td, "① 一次性")
        A(f"### ① 一次性：出发前办完（{len(one)} 条）")
        A("")
        A("| ☐ | 级别 | 事项 | 为什么 |")
        A("|:-:|:-:|---|---|")
        for r in one:
            A(f"| ☐ | {r['级别']} | {r['事项']} | {r['为什么']} |")
        A("")

        pg = M.table(td, "② 每位鸟导")
        A(f"### ② 每位带队方都走一遍（{len(pg)} 条 × {len(segs)} 段）")
        A("")
        A("**这是模板**：同一件事不要对每位重想一遍，逐段照着走。")
        A("")
        for i, s in enumerate(segs, 1):
            A(f"**第 {i} 段：{s['guide']}**"
              f"（{s['blocks'][0]['日期']}–{s['blocks'][-1]['日期']}）")
            A("")
            A("| ☐ | 级别 | 事项 |")
            A("|:-:|:-:|---|")
            for r in pg:
                A(f"| ☐ | {r['级别']} | {r['事项']} |")
            A("")

        ps = M.table(td, "③ 每个观鸟时段")
        birding = [b for b in itin if b["形式"] not in ("rest", "transfer")]
        A(f"### ③ 每个观鸟时段都做（{len(ps)} 条 × {len(birding)} 个时段）")
        A("")
        A("**模板，自助时段同样适用。**")
        A("")
        A("| 级别 | 事项 | 为什么 |")
        A("|:-:|---|---|")
        for r in ps:
            A(f"| {r['级别']} | {r['事项']} | {r['为什么']} |")
        A("")

        blk = M.table(td, "④ 某一段专属")
        A(f"### ④ 某一段专属（{len(blk)} 条）")
        A("")
        A("**不在本册展开**——它们和时段绑定，渲染在"
          "[行程表](02-行程表.md)对应时段，现场就地勾选。")
        A("")

    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    cfg = TripConfig(a.trip)
    body = render(cfg)
    out = Path(a.out) if a.out else cfg.dir / "out" / "05-行前与物流.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    itin = M.table(cfg.dir / "itinerary.md", "时段表")
    print(f"写出 {out}  ({len(body.splitlines())} 行)")
    print(f"  带队分段 {len(segments(itin))} 段")


if __name__ == "__main__":
    main()
