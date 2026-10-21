#!/usr/bin/env python3
"""特有种判定：**纯 eBird 原生**——不依赖 GBIF，也不依赖任何人工名单。

用法:
    EBIRD_API_KEY=<key> python3 -I engine/endemism.py --world-cache   # 一次性，抓 253 个地区
    python3 -I engine/endemism.py --trip trips/<id>                   # 判定本行程地区的特有种
    python3 -I engine/endemism.py --trip trips/<id> --compare <file>  # 与一份已有名单比对

方法
----
缓存**全部国家/地区**的 `product/spplist`，
然后：**只在一个地区出现过的种 = 该地区的特有种**。

为什么不用 GBIF 的比例法
------------------------
原项目用 GBIF「地区记录数 / 全球记录数 ≥ 90%」来判定。那是个合理的近似，
但它引入了**第二个权威源**——本项目的口径是 eBird 唯一权威，
物种在不在某地区的事实必须由 eBird 自己回答。

而且 eBird 能回答得更干脆：`spplist` 就是「这个地区记录过哪些种」的权威答案，
不需要再从记录条数去推断比例、也不需要挑阈值。

实测佐证（2026-10-19）
----------------------
35 种斯里兰卡特有种，在**印度（1457 种）与马尔代夫（177 种）名录中出现 0 次**。
即最容易误伤的两个邻区没有任何泄漏。

已知局限（必须写进文档，不要假装没有）
--------------------------------------
1. **迷鸟会打破特有性**：某个特有种若被记录到一笔境外迷鸟，
   它就会从特有名单里掉出来。这是 eBird 数据的事实，不是 bug——
   但对「我这趟要看哪些只有这里有的鸟」这个用途而言可能过严。
   所以输出里**另给一档「准特有」**：只在本地区 + 另一个地区出现，
   且在另一个地区……本模块**不猜**，只把它列出来给人看。
2. **地区粒度是国家**：海南特有、婆罗洲特有这类**跨国或次国家级**的特有性
   判不出来。需要时把 `region` 设成次级行政区码（如 `CN-HI`），
   但那时「只在一个地区出现」的含义也随之改变，结果要人工复核。
3. eBird 的地区列表含部分**重叠辖区**（如某些海外属地既单列又计入宗主国），
   会让真特有种看起来出现在 2 个地区。输出里标出这种情形，交人判断。

为什么用 curl：`python3 -I` 隔离模式不读代理环境变量，urllib 在本机会 DNS 失败。
"""
import argparse
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import mdtable as M                                     # noqa: E402
import taxonomy as T                                    # noqa: E402
from ebird import Client, TripConfig                    # noqa: E402

WORLD = ENGINE / "refdata" / "spplist_world"
INDEX = ENGINE / "refdata" / "endemic_index.json"


def fetch_world(cl):
    """抓全部国家/地区的名录，构建 `code -> {地区}` 倒排。"""
    regions = cl.get("/ref/region/list/country/world?fmt=json",
                     "regions_world", default=[])
    if not regions:
        sys.exit("取不到国家列表（离线且无缓存，或 key 无效）")
    print(f"国家/地区: {len(regions)} 个")

    where, failed = {}, []
    for i, r in enumerate(regions, 1):
        rc = r["code"]
        codes = cl.get(f"/product/spplist/{rc}", f"spplist_{rc}", default=None)
        if codes is None:
            failed.append(rc)
            continue
        for c in codes:
            where.setdefault(c, []).append(rc)
        if i % 25 == 0:
            print(f"  ... {i}/{len(regions)}（缓存 {cl.hits} 新取 {cl.misses}）")

    INDEX.write_text(json.dumps(
        {"source": "eBird API v2 /product/spplist 全地区",
         "n_regions": len(regions), "failed": failed,
         "regions": {r["code"]: r["name"] for r in regions},
         "where": {c: sorted(v) for c, v in sorted(where.items())}},
        ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"写出 {INDEX.name}: {len(where)} 种，失败 {len(failed)} 个地区"
          + (f" {failed[:5]}" if failed else ""))
    return where, failed


def load_index():
    if not INDEX.exists():
        sys.exit(f"缺 {INDEX}\n  先跑: python3 -I engine/endemism.py --world-cache")
    return json.loads(INDEX.read_text(encoding="utf-8"))


def classify(region, idx, species_only=None):
    """返回 `(特有, 准特有)`。

    `特有`   —— 只在 `region` 出现；
    `准特有` —— 在 `region` 加**恰好一个**其它地区出现；
                很可能是迷鸟或辖区重叠，**由人判断**，脚本不替它决定。

    `species_only` —— 种级 code 的集合。`product/spplist` **会返回亚种群等
    非种级分类单元**（实测斯里兰卡返回了 `bkrfla3`，它是个 form 而不是种），
    不过滤就会多出一个查不到名字的「特有种」。传入分类表的 keys 即可过滤。
    """
    endemic, near, dropped = [], [], []
    for code, regs in idx["where"].items():
        if region not in regs:
            continue
        if species_only is not None and code not in species_only:
            if len(regs) <= 2:
                dropped.append(code)
            continue
        if len(regs) == 1:
            endemic.append(code)
        elif len(regs) == 2:
            near.append((code, [r for r in regs if r != region][0]))
    return sorted(endemic), sorted(near), sorted(dropped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world-cache", action="store_true",
                    help="抓全部地区名录（一次性，带缓存可断点续抓）")
    ap.add_argument("--trip")
    ap.add_argument("--compare", help="与一份名单比对（每行一个名字）")
    a = ap.parse_args()

    if a.world_cache:
        cl = Client(WORLD)
        fetch_world(cl)
        print(f"缓存命中 {cl.hits}，新取 {cl.misses}，失败 {cl.fails}")
        if cl.fails:
            print("  有失败——再跑一次本命令即可续抓（已成功的走缓存）")
        return

    if not a.trip:
        sys.exit("需要 --trip 或 --world-cache")

    cfg = TripConfig(a.trip)
    idx = load_index()
    t = T.load({r["别名"]: r["code"]
                for r in M.table(cfg.dir / "targets.md", "别名表")}
               if (cfg.dir / "targets.md").exists() else None)

    endemic, near, dropped = classify(cfg.region, idx, species_only=set(t.sp))
    names = idx.get("regions", {})
    failed = idx.get("failed", [])
    print(f"地区 {cfg.region}（{names.get(cfg.region, '?')}）"
          f" | 对比 {idx['n_regions']} 个地区")
    if failed:
        # 缺一个地区就可能把非特有种误判成特有，必须显式告警而不是静默出结果
        print(f"  ⚠ {len(failed)} 个地区的名录**没取到** {failed[:8]}"
              f"\n    —— 结果可能偏多（误判成特有）。"
              f"再跑 --world-cache 续抓后重算。")
    if dropped:
        print(f"  已过滤 {len(dropped)} 个非种级分类单元（spplist 会返回亚种群）: "
              f"{dropped}")
    print(f"\n特有种 {len(endemic)} 种：")
    for c in sorted(endemic, key=t.taxon_order):
        print(f"   {t.label(c, 'zh_en')}")

    print(f"\n准特有 {len(near)} 种（本地区 + 另一个地区，疑似迷鸟或辖区重叠，需人工判断）：")
    for c, other in sorted(near, key=lambda x: t.taxon_order(x[0])):
        print(f"   {t.label(c, 'zh_en'):<52} 另见于 {other}（{names.get(other, '?')}）")

    out = cfg.data / "endemic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"region": cfg.region, "method": "eBird spplist 全地区倒排",
         "n_regions_compared": idx["n_regions"],
         "endemic": endemic,
         "near_endemic": [{"code": c, "also_in": o} for c, o in near]},
        ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"\n写出 {out}")

    if a.compare:
        want = [ln.split("\t")[0].strip()
                for ln in Path(a.compare).read_text(encoding="utf-8").splitlines()
                if ln.strip()]
        ok, bad = t.resolve_many(want)
        wset = {c for _, c in ok}
        eset = set(endemic)
        print(f"\n=== 与 {a.compare} 比对（{len(want)} 条）===")
        for nm, why in bad:
            print(f"   未解析: {nm} —— {why[:60]}")
        only_list = sorted(wset - eset, key=t.taxon_order)
        only_ebird = sorted(eset - wset, key=t.taxon_order)
        print(f"  名单有、eBird 判定不是特有: {len(only_list)}")
        for c in only_list:
            others = [r for r in idx["where"].get(c, []) if r != cfg.region]
            print(f"     {t.label(c, 'zh_en'):<50} 另见于 {others}")
        print(f"  eBird 判定是特有、名单没有: {len(only_ebird)}")
        for c in only_ebird:
            print(f"     {t.label(c, 'zh_en')}")


if __name__ == "__main__":
    main()
