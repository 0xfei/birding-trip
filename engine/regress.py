#!/usr/bin/env python3
"""回归比对：旧流水线的结论 vs 新引擎的结论，**逐条列出差异与可解释原因**。

用法:
    python3 -I engine/regress.py --trip trips/<id> --old data/targets.json

为什么验收标准不是「数字相等」
------------------------------
旧流水线以第三方名录为主数据源，新引擎以 eBird 为唯一权威。
**换口径必然导致鸟种进出**——强求数字相等反而会把 eBird 的正确结论改错。

所以验收标准是：**每一个进/出的种都有可解释的原因**，
逐条人工签字后记进 `trips/<id>/checks.md`。

本脚本只负责把差异摆出来并给出**疑似原因**，不做任何裁决。
"""
import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
sys.path.insert(0, str(ENGINE / "render"))
import mdtable as M                                      # noqa: E402
import taxonomy as T                                     # noqa: E402
from species_list import Catalog, TIER_NAME              # noqa: E402


def load_old(path, t):
    """读旧产出。按学名解析成 eBird code；解析不出的单列。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = raw if isinstance(raw, list) else list(raw.values())
    ok, bad = {}, []
    for r in recs:
        sci = r.get("sci", "")
        c, why = t.resolve(sci) if sci else (None, "无学名")
        if not c and r.get("zh"):
            c, why = t.resolve(r["zh"])
        if c:
            ok[c] = r
        else:
            bad.append((r.get("zh", "?"), sci, why))
    return ok, bad, len(recs)


def why_added(code, cat, idx):
    """这个种为什么新引擎有、旧的没有。"""
    if cat.tiers[code] == 1:
        return "eBird 判定为特有种"
    regs = idx.get("where", {}).get(code, [])
    if len(regs) > 100:
        return "广布种，旧名录可能未收录或分类不同"
    return "eBird 地区名录收录，旧第三方名录未收录"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--old", required=True, help="旧产出 JSON（如 data/targets.json）")
    a = ap.parse_args()

    cat = Catalog(a.trip)
    t = cat.t
    idx_f = ENGINE / "refdata" / "endemic_index.json"
    idx = json.loads(idx_f.read_text(encoding="utf-8")) if idx_f.exists() else {}

    old, old_bad, n_old_raw = load_old(a.old, t)
    new = set(cat.all_codes)

    print(f"旧产出 {a.old}：{n_old_raw} 条，解析出 {len(old)} 个 eBird code")
    print(f"新引擎 {cat.cfg.region} 地区名录：{len(new)} 种（种级）")
    print()

    # ---- 旧有新无 ----
    gone = sorted(set(old) - new, key=t.taxon_order)
    print(f"【旧有、新无】{len(gone)} 种")
    for c in gone:
        regs = idx.get("where", {}).get(c, [])
        here = cat.cfg.region in regs
        why = ("eBird 地区名录确实不含它"
               if not here else "在 eBird 名录里但被种级过滤排除")
        print(f"   {t.zh(c) or '—':<14} {t.en(c):<34} {why}")
    print()

    # ---- 旧的解析失败 ----
    print(f"【旧产出里解析不出 eBird code】{len(old_bad)} 条")
    for zh, sci, why in old_bad:
        print(f"   {zh:<14} {sci or '（无学名）':<28} {why[:44]}")
    print()

    # ---- 新有旧无 ----
    added = sorted(new - set(old), key=t.taxon_order)
    print(f"【新有、旧无】{len(added)} 种")
    bytier = {}
    for c in added:
        bytier.setdefault(cat.tiers[c], []).append(c)
    for tier in sorted(bytier):
        cs = bytier[tier]
        print(f"   {TIER_NAME[tier]}（{len(cs)} 种）")
        for c in cs[:40]:
            print(f"      {t.zh(c) or '—':<14} {t.en(c):<34} "
                  f"{why_added(c, cat, idx)}")
        if len(cs) > 40:
            print(f"      …另有 {len(cs) - 40} 种")
    print()

    # ---- 特有种专项 ----
    old_end = {c for c, r in old.items() if r.get("cat") == 1 or r.get("endemic")}
    new_end = cat.endemic
    print(f"【特有种】旧 {len(old_end)} 种 / 新 {len(new_end)} 种")
    for c in sorted(old_end - new_end, key=t.taxon_order):
        regs = idx.get("where", {}).get(c, [])
        others = [r for r in regs if r != cat.cfg.region]
        print(f"   旧有新无: {t.zh(c) or t.en(c):<16} 另见于 {others}")
    for c in sorted(new_end - old_end, key=t.taxon_order):
        print(f"   新有旧无: {t.zh(c) or t.en(c):<16} "
              f"（eBird 全地区倒排判定）")
    if old_end == new_end:
        print("   两边完全一致 ✅")
    print()

    print("=" * 60)
    print(f"差异合计：出 {len(gone)} / 入 {len(added)} / 解析失败 {len(old_bad)}")
    print("**本脚本不做裁决。** 逐条看过之后，把结论记进 "
          f"{Path(a.trip) / 'checks.md'} 的「已裁决的第三方分歧」一节。")


if __name__ == "__main__":
    main()
