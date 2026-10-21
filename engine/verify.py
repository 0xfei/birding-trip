#!/usr/bin/env python3
"""全链路校验：**通用检查 + 本行程断言**。任一项失败则非零退出。

用法:
    python3 -I engine/verify.py --trip trips/<id>
    python3 -I engine/verify.py --trip trips/<id> -v     # 列出每一项

校验**不能**代替 build.py
-------------------------
本脚本只读配置与产出的 `.md`，**发现不了生成器崩了**。
原项目实测踩过：生成器抛异常退出、文档停在旧版本，而校验照样全绿——
因为它校验的是上一次成功生成的旧文件。
所以改了生成器一定要走 `engine/build.py`，它会把生成与校验串起来。

检查分三类
----------
**① 防编造**——文档里出现的鸟名必须能回溯到 eBird；
  占位符必须指向真实存在的 `speciesCode`。
  这是整套工具最重要的护栏：判断文本大量由 LLM 从物料里写出，
  没有这道检查，一个不存在的鸟名可以一路渲染进最终文档。

**② 防漂移**——同样的输入必须产出同样的文档。
  无序遍历 `set` 会让两次构建的产物不同（实测连续三次生成出三份不同的文档）。

**③ 防口径分裂**——「有效机会」这类规则只能有一个实现。
  原项目有四份副本，改规则时险些漏改。

另有**本行程断言**从 `trips/<id>/checks.md` 读（可选）：
形如「特有种恰好 35 种」这类**只对这一趟成立**的期望值。
它和通用检查分开，换行程不会互相干扰。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import mdtable as M                                      # noqa: E402
import taxonomy as T                                     # noqa: E402
from ebird import TripConfig                             # noqa: E402

# 必须引用共享机会判定模块、不得自己硬写阈值的消费方
OPP_CONSUMERS = [
    "engine/render/species_list.py",
    "engine/render/itinerary.py",
    "engine/estimate.py",
]
# 必须确定性输出的生成器
GENERATORS = [
    "engine/render/species_list.py",
    "engine/render/itinerary.py",
    "engine/render/discrepancy.py",
    "engine/render/logistics.py",
    "engine/estimate.py",
]


class Checker:
    def __init__(self, verbose=False):
        self.n = 0
        self.fails = []
        self.verbose = verbose

    def check(self, label, ok, detail=""):
        self.n += 1
        if ok:
            if self.verbose:
                print(f"  ✅ {label}")
        else:
            self.fails.append(label)
            print(f"  ❌ {label}" + (f"\n       {detail}" if detail else ""))
        return ok


def verify(trip, verbose=False):
    cfg = TripConfig(trip)
    d = Path(trip)
    c = Checker(verbose)
    aliases = ({r["别名"]: r["code"]
                for r in M.table(d / "targets.md", "别名表")}
               if (d / "targets.md").exists() else None)
    t = T.load(aliases)

    # ================= ① 配置完整性 =================
    print("① 配置完整性")
    itin = M.table(d / "itinerary.md", "时段表")
    sites = {s["id"] for s in cfg.sites}
    c.check("itinerary.md 有时段表", bool(itin))
    c.check("sites.md 有点位表", bool(cfg.sites))

    bad = sorted({b["点位"] for b in itin
                  if b["点位"] not in sites and b["点位"] not in ("", "—")})
    c.check("行程里的点位都在 sites.md 里定义", not bad, f"未定义: {bad}")

    modes = {"birding", "safari", "hike", "pelagic", "night-walk",
             "night-drive", "transfer", "rest"}
    badm = sorted({b["形式"] for b in itin if b["形式"] not in modes})
    c.check("行程的「形式」都是合法取值", not badm,
            f"未知形式: {badm}；合法: {sorted(modes)}")

    mm = M.parse_pairs(cfg.meta.get("mode_mult", ""))
    missing_mm = sorted({b["形式"] for b in itin if b["形式"] not in mm})
    c.check("每种「形式」都有模型权重", not missing_mm,
            f"trip.md 的 mode_mult 缺: {missing_mm}")

    for key in ("id", "region", "dates"):
        c.check(f"trip.md 有 `{key}`", key in cfg.meta)

    # ④ 待办的 key 必须与行程时段逐字对得上，否则那条待办永远渲染不出来
    tdf = d / "todos.md"
    if tdf.exists():
        blk = M.table(tdf, "④ 某一段专属")
        keys = {(b["日期"], b["时段"]) for b in itin}
        orphan = sorted({(r["日期"], r["时段"]) for r in blk} - keys)
        c.check(f"④ 层待办的 {len(blk)} 条都对得上行程时段", not orphan,
                f"对不上（永远渲染不出来，等于丢了）: {orphan}")
        for sec, n_min in [("① 一次性", 1), ("② 每位鸟导", 1),
                           ("③ 每个观鸟时段", 1)]:
            c.check(f"todos.md 的「{sec}」表能读出来",
                    len(M.table(tdf, sec)) >= n_min,
                    "表为空——常见原因是分隔行写法解析不了")

    # ================= ② 名字与防编造 =================
    print("② 名字与防编造")
    if aliases:
        bada = [(k, v) for k, v in aliases.items() if v not in t.sp]
        c.check("别名表里的 code 都真实存在", not bada,
                f"不存在: {bada}")
        wrong = [(k, v) for k, v in aliases.items()
                 if v in t.sp and t.resolve(k)[0] != v]
        c.check("别名都能解析到它声明的 code", not wrong, f"{wrong}")

    fams = {r["科（eBird familyComName）"]
            for r in M.table(d / "targets.md", "关注科目")} \
        if (d / "targets.md").exists() else set()
    if fams:
        allf = {t.family(x) for x in t.sp}
        badf = sorted(fams - allf)
        c.check(f"关注科目的 {len(fams)} 个科名都存在于 eBird 分类",
                not badf, f"不存在: {badf}")

    named = [r["名字"] for r in M.table(d / "targets.md", "用户点名")] \
        if (d / "targets.md").exists() else []
    if named:
        _, nbad = t.resolve_many(named)
        c.check(f"用户点名的 {len(named)} 个名字都能解析", not nbad,
                f"未解析: {[x[0] for x in nbad]}")

    out = d / "out"
    docs = sorted(out.glob("*.md")) if out.exists() else []
    c.check("产出文档存在", bool(docs), f"{out} 下没有 .md")

    # 占位符必须指向真实 code
    bad_ph = []
    for f in list(d.glob("*.md")) + docs:
        for code in t.placeholders(f.read_text(encoding="utf-8")):
            if code not in t.sp:
                bad_ph.append(f"{f.name}:{code}")
    c.check("所有 {{code}} 占位符都指向真实的 eBird code", not bad_ph,
            f"{bad_ph[:5]}")

    # 产出文档里的英文名必须来自 eBird/IOC —— 这是防编造的主检查
    known_en = {t.en(x) for x in t.sp} | {t.en_ebird(x) for x in t.sp}
    bogus = []
    for f in docs:
        text = f.read_text(encoding="utf-8")
        for name in re.findall(r"\*\*([A-Z][A-Za-z'\- ]{4,40})\*\*", text):
            if name in known_en:
                continue
            # 表头、栏目名这类非鸟名的粗体会误报，只认带两个及以上单词的
            if len(name.split()) >= 2 and name not in ("English", "Why"):
                bogus.append(f"{f.name}:{name}")
    c.check("产出文档里的加粗英文名都来自 eBird/IOC（防编造）",
            not bogus, f"未知名: {sorted(set(bogus))[:6]}")

    # ================= ③ 防漂移与防口径分裂 =================
    print("③ 防漂移与防口径分裂")
    unsorted_iter = []
    for rel in GENERATORS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*for\s+\w+\s+in\s+(.+):$", src, re.M):
            e = m.group(1)
            if ("set(" in e or e.strip().startswith("{")) and "sorted(" not in e:
                unsorted_iter.append(f"{rel}: {e.strip()[:48]}")
    c.check("生成器没有无序遍历 set（防文档漂移）", not unsorted_iter,
            f"{unsorted_iter[:3]}")

    no_ref, hardcoded = [], []
    for rel in OPP_CONSUMERS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        if "opportunity" not in src and "cat.opp" not in src:
            no_ref.append(rel)
        if re.search(r"=\s*0\.15\s*$|freq_min\s*=\s*0\.15", src, re.M):
            hardcoded.append(rel)
    c.check(f"{len(OPP_CONSUMERS)} 个消费方都走共享的机会判定模块",
            not no_ref, f"未引用: {no_ref}")
    c.check("没有消费方硬写阈值", not hardcoded, f"硬写: {hardcoded}")

    # 热点串点：两个点位用了同一组 locId
    hs_f = cfg.data / "ebird_hotspots.json"
    if hs_f.exists():
        hs = json.loads(hs_f.read_text(encoding="utf-8"))
        groups = {}
        for sid, v in sorted(hs.items()):
            if v["locs"]:
                groups.setdefault(tuple(sorted(v["locs"])), []).append(sid)
        clash = [g for g in groups.values() if len(g) > 1]
        c.check("没有两个点位共用同一组热点（防串点）", not clash,
                f"共用: {clash}；在 sites.md 里钉死各自的 locId")

    # 频次分母：太小的分母会让整段结论不可信
    fq_f = cfg.data / "ebird_freq.json"
    if fq_f.exists():
        meta = json.loads(fq_f.read_text(encoding="utf-8")).get("_meta", {})
        den = meta.get("denominators", {})
        c.check("频次数据没有永久失败的请求",
                meta.get("failed_requests", 0) == 0,
                f"失败 {meta.get('failed_requests')} 次——频次有空洞，"
                f"重跑 ebird.py 可续抓")
        zero = sorted([s for s in sites if den.get(s, 0) == 0])
        c.check("每个点位都有频次数据", not zero, f"分母为 0: {zero}")

    # ================= ④ 本行程断言 =================
    chk = d / "checks.md"
    if chk.exists():
        print("④ 本行程断言（checks.md）")
        rows = M.table(chk, "断言表")
        ctx = build_context(cfg, t, itin)
        for r in rows:
            # 断言在表格里会写成 `n_endemic == 35`（反引号是 Markdown 代码标记，
            # 给人看的），求值前要剥掉——否则整列全是语法错误。
            expr = r.get("断言", "").strip().strip("`").strip()
            why = r.get("说明", "")
            if not expr:
                continue
            try:
                ok = bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307
            except Exception as e:
                ok, why = False, f"表达式报错: {e}"
            c.check(f"{expr}" + (f"　（{why}）" if why else ""), ok)
    else:
        print(f"④ 本行程断言：无（可选，建 {chk} 后生效）")

    print(f"\n{c.n - len(c.fails)}/{c.n} 项通过")
    if c.fails:
        print("失败项：" + "；".join(c.fails))
        return 1
    print("全部通过。")
    return 0


def build_context(cfg, t, itin):
    """给 checks.md 的断言表达式用的变量。**只读，且不暴露 builtins。**"""
    d = cfg.data
    ctx = {"n_blocks": len(itin), "n_sites": len(cfg.sites),
           "n_days": len({b["日期"] for b in itin})}
    f = d / "endemic.json"
    if f.exists():
        ctx["n_endemic"] = len(json.loads(
            f.read_text(encoding="utf-8")).get("endemic", []))
    f = d / "ebird_region_spplist.json"
    if f.exists():
        sp = json.loads(f.read_text(encoding="utf-8"))["species"]
        ctx["n_region"] = len(sp)
        ctx["n_species"] = len([x for x in sp if x in t.sp])
    f = d / "ebird_home_spplist.json"
    if f.exists() and "n_species" in ctx:
        home = set(json.loads(f.read_text(encoding="utf-8"))["species"])
        sp = json.loads((d / "ebird_region_spplist.json")
                        .read_text(encoding="utf-8"))["species"]
        ctx["n_lifer"] = len([x for x in sp if x in t.sp and x not in home])
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    sys.exit(verify(a.trip, a.verbose))


if __name__ == "__main__":
    main()
