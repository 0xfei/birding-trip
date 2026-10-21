#!/usr/bin/env python3
"""渲染**第三方分歧报告**：第三方与 eBird 不一致的地方，交人裁决。

用法:
    python3 -I engine/render/discrepancy.py --trip trips/<id>

为什么需要这份报告
------------------
本项目的最高原则是 **eBird 是唯一权威源**：
物种在不在名录、分布在哪、什么季节、频次多少、是否特有，一律以 eBird 为准。
雀跃、GBIF、别人的行程报告都是第三方，**只能用来挑分歧，不能覆盖 eBird**。

但「不能覆盖」不等于「可以无视」。第三方说的不一样，**要么它错、要么 eBird 漏**，
两种都值得看一眼。所以分歧全部汇总到这里，由人裁决，
**裁决结果记进 `checks.md`**——下次再出现同样的分歧就不必重新想一遍。

**本报告不做任何自动裁决。** 它只负责把差异摆出来、说清每条差异的可能原因。

四类分歧
--------
1. **名录差异**：第三方名录有、eBird 没有（或反过来）；
2. **英文名差异**：IOC（老牌图鉴常用名）与 eBird 的叫法不同——
   本项目显示用 IOC，但**要报给鸟导的那个字符串**值得两个都知道；
3. **点位主张冲突**：GBIF 说某点有、而 eBird 在足够样本下零报到（被否决的）；
4. **解析失败**：第三方的名字在 eBird 分类里查无此名。
"""
import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
sys.path.insert(0, str(ENGINE / "render"))
import mdtable as M                                      # noqa: E402
import taxonomy as T                                     # noqa: E402
from species_list import Catalog                         # noqa: E402

def load_third_party(cfg):
    """读本行程声明的第三方名录。

    **由行程配置声明，不在引擎里硬编码。**
    这里曾经硬写着某一趟用的那个第三方文件，结果换国家跑的时候
    拿泰国的 eBird 名录去对比了斯里兰卡的第三方名录，
    产出一千多行毫无意义的「差异」——**这正是「通用」不该有的残留**。

    在 `trip.md` 里声明（可多条，逗号分隔）：

        - thirdparty_lists: 雀跃地区名录=../../legacy/data/sri-lanka.json

    路径相对行程目录。支持两种 JSON 结构，自动识别：
      - 列表，元素含 `sci`（学名）与可选 `zh`；
      - 对象，值含同样的字段。
    不声明就跳过这一节——第三方本来就是可选的。
    """
    spec = cfg.meta.get("thirdparty_lists", "").strip()
    if not spec:
        return []
    out = []
    for item in M.split_list(spec):
        label, _, rel = item.partition("=")
        label, rel = label.strip(), rel.strip()
        if not rel:
            continue
        p = (cfg.dir / rel).resolve()
        if not p.exists():
            print(f"  ⚠ 第三方名录不存在，跳过: {p}", file=sys.stderr)
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        recs = raw if isinstance(raw, list) else list(raw.values())
        items = [(r.get("sci", ""), r.get("zh", ""))
                 for r in recs if isinstance(r, dict)]
        out.append((label, items))
    return out


def render(cat):
    t, cfg = cat.t, cat.cfg
    ebird = set(cat.all_codes)
    L, A = [], None
    L = []
    A = L.append

    A(f"# {cfg.meta.get('title', cfg.meta.get('id', ''))} · 第三方分歧")
    A("")
    A("**eBird 是本项目的唯一权威源。** 本报告只把第三方与 eBird 不一致的地方"
      "摆出来，**不做任何自动裁决**，也**不会覆盖 eBird 的任何结论**。")
    A("")
    A("裁决之后请把结论记进 `checks.md`，下次就不必重新想一遍。")
    A("")

    # ---------- 1. 名录差异 ----------
    tps = load_third_party(cfg)
    for label, items in tps:
        A(f"## 名录差异：{label}")
        A("")
        resolved, unresolved = {}, []
        for sci, zh in items:
            c, why = t.resolve(sci)
            if c:
                resolved[c] = (sci, zh)
            else:
                unresolved.append((sci, zh, why))
        only_tp = sorted(set(resolved) - ebird, key=t.taxon_order)
        only_eb = sorted(ebird - set(resolved), key=t.taxon_order)
        A(f"{label} {len(items)} 条，解析出 {len(resolved)} 个 eBird code；"
          f"eBird `{cfg.region}` 名录 {len(ebird)} 种。")
        A("")

        if unresolved:
            A(f"### ⚠ 解析失败 {len(unresolved)} 条")
            A("")
            A("第三方用的学名在 eBird 分类里查无此名。"
              "通常是**第三方采用了更新/更旧的分类**，"
              "或该名字在 eBird 体系下已被归并。**脚本不猜**。")
            A("")
            A("| 第三方学名 | 第三方中文名 | 原因 |")
            A("|---|---|---|")
            for sci, zh, why in unresolved:
                A(f"| *{sci}* | {zh or '—'} | {why[:60]} |")
            A("")

        if only_tp:
            A(f"### {label}有、eBird `{cfg.region}` 名录没有：{len(only_tp)} 种")
            A("")
            A("**以 eBird 为准**——这些种不进本行程的任何清单。"
              "列在这里只是让你知道第三方多说了什么。")
            A("")
            A("| 鸟种 | English | 学名 |")
            A("|---|---|---|")
            for c in only_tp:
                A(f"| {t.zh(c) or '—'} | {t.en(c)} | *{t.sci(c)}* |")
            A("")

        if only_eb:
            A(f"### eBird 有、{label}没有：{len(only_eb)} 种")
            A("")
            A("**这些已经在清单里了**（以 eBird 为准）。"
              "数量大是正常的——第三方名录通常更保守或更新更慢。")
            A("")
            A(f"<details><summary>展开 {len(only_eb)} 种</summary>")
            A("")
            A("| 鸟种 | English | 档 |")
            A("|---|---|---|")
            from species_list import TIER_NAME
            for c in only_eb:
                A(f"| {t.zh(c) or '—'} | {t.en(c)} "
                  f"| {TIER_NAME[cat.tiers[c]]} |")
            A("")
            A("</details>")
            A("")

    # ---------- 2. 英文名差异 ----------
    diff = [c for c in sorted(ebird, key=t.taxon_order) if t.en_differs(c)]
    A(f"## 英文名差异：IOC vs eBird（{len(diff)} 种）")
    A("")
    A("本项目**显示用 IOC（老牌图鉴常用名）**，因为当地鸟导用的是图鉴。"
      "但 eBird 用户与 eBird 接口用的是另一个叫法，"
      "**两个都值得知道**——报鸟时对方听不懂就换另一个说。")
    A("")
    A("> 纯连字符/拼写差异（`Blue-Magpie` vs `Blue Magpie`、`Gray` vs `Grey`）"
      "已被忽略，这里只列**实质不同名**的。")
    A("")
    if diff:
        A("| 鸟种 | 本项目显示（IOC）| eBird 叫法 | 档 |")
        A("|---|---|---|---|")
        from species_list import TIER_NAME
        for c in diff:
            A(f"| {t.zh(c) or '—'} | **{t.en(c)}** | {t.en_ebird(c)} "
              f"| {TIER_NAME[cat.tiers[c]]} |")
        A("")

    # ---------- 3. 点位主张冲突 ----------
    opp = cat.opp
    if opp.gbif:
        vetoed = []
        for c in sorted(ebird, key=t.taxon_order):
            for s in cat.sites:
                if opp.gbif_at(c, s) >= opp.gbif_min and opp.vetoed(c, s):
                    vetoed.append((c, s, opp.gbif_at(c, s)))
        A(f"## 点位主张冲突：GBIF 说有、eBird 零报到（{len(vetoed)} 条）")
        A("")
        A("GBIF 在该点位有足够记录，但 eBird 在**足够样本**下一次都没报到。"
          "按 `engine/opportunity.py` 的规则，**eBird 的零记录否决 GBIF**。")
        A("")
        A("为什么敢否决：GBIF 按**半径**圈记录，半径里的邻近生境会被算进来；"
          "而 eBird 钉死了具体热点，是点位级的。"
          "实测过的典型错误：出海点的 30 km 半径把内陆水体的淡水鸭算了进来，"
          "而我们去那里是**出海看鲸**。")
        A("")
        A("> **关键区分**：低频 ≠ 不存在。"
          "只有「零报到 + 样本足够」才算有证据的不存在。")
        A("")
        if vetoed:
            labels = {s["id"]: s["名称"] for s in cfg.sites}
            A("| 鸟种 | 点位 | GBIF 条数 | eBird 观鸟日 | 裁决 |")
            A("|---|---|---:|---:|---|")
            for c, s, n in vetoed[:80]:
                A(f"| {t.zh(c) or t.en(c)} | {labels.get(s, s)} | {n} "
                  f"| 0/{opp.denom.get(s, 0)} | 以 eBird 为准，不计机会 |")
            A("")
            if len(vetoed) > 80:
                A(f"> 另有 {len(vetoed) - 80} 条同类，从略。")
                A("")
    else:
        A("## 点位主张冲突")
        A("")
        A("_未取 GBIF 数据（跑 `engine/sources/thirdparty/gbif.py` 后重建）。_")
        A("")

    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    cat = Catalog(a.trip)
    body = render(cat)
    out = Path(a.out) if a.out else cat.cfg.dir / "out" / "03-第三方分歧.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"写出 {out}  ({len(body.splitlines())} 行)")


if __name__ == "__main__":
    main()
