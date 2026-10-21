#!/usr/bin/env python3
"""GBIF 适配器：**第三方源，只用来 double check，永不覆盖 eBird**。

用法:
    python3 -I engine/sources/thirdparty/gbif.py --trip trips/<id>
    python3 -I engine/sources/thirdparty/gbif.py --trip trips/<id> --taxa Mammalia
    python3 -I engine/sources/thirdparty/gbif.py --trip trips/<id> --report

定位（务必先读）
----------------
本项目的权威数据源**只有 eBird**。GBIF 在这里有且只有三个用途：

  1. **double check** —— 两源不一致的地方进分歧报告，交人裁决；
  2. **eBird 完全无数据时的弱信号兜底** —— 实测它只在极少数种上是唯一依据；
  3. **非鸟类群**（哺乳/爬行/两栖）—— eBird 根本不覆盖这些，
     但这一层**不计入总种数、不进概率模型**，单独成篇并声明无 eBird 数据。

GBIF 的两个硬伤（为什么它当不了权威）
-------------------------------------
1. **按半径圈，点位之间会重叠**。实测最极端的一对点位中心只隔 2.3 km，
   半径却分别是 12 km 与 10 km——所以 GBIF 的「某点多少条」
   根本不是点位级的数字。「瘤鸭事件」就是这么来的：
   出海点 30 km 半径把内陆水体的记录算了进来，把人指向错误的地点。
2. **没有分母**。300 条记录算常见还是罕见，取决于有多少人在那儿看过鸟，
   而 GBIF 不告诉你有多少份清单。eBird 的频次自带分母。

还有一条：**GBIF 的分类骨干滞后**，近年新拆分的学名常常只能匹配到属级，
于是真实存在的种会显示成全区 0 条。**不要拿 GBIF 的 0 去否定任何事。**

数据与判断
----------
- **数据**：GBIF 返回的记录条数。原样写入，不做任何改写。
- **判断**：点位坐标与半径（来自 `trips/<id>/sites.md`，与 eBird 共用同一张表）、
  查哪些类群。本模块零硬编码。

为什么用 curl：`python3 -I` 隔离模式不读代理环境变量，urllib 在本机会 DNS 失败。
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import taxonomy as T                                     # noqa: E402
from ebird import TripConfig                             # noqa: E402

API = "https://api.gbif.org/v1/occurrence/search"
UA = "birds-trip-planner/2.0 (personal trip planning)"
SLEEP = 0.34                 # 约 3 req/s，对公共 API 保持克制

# GBIF 的分类 key。鸟类不在这里——鸟类一律走 eBird。
TAXON_KEYS = {
    "Mammalia": 359,
    "Reptilia": 358,
    "Amphibia": 131,
}


def fetch(params, cache, name):
    """取一次计数。命中缓存就不请求（幂等、可离线重跑）。"""
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8")), True
    url = API + "?" + urllib.parse.urlencode(params, doseq=True)
    r = subprocess.run(["curl", "-sS", "--max-time", "40",
                        "-H", f"User-Agent: {UA}", url],
                       capture_output=True, text=True)
    time.sleep(SLEEP)
    if r.returncode != 0:
        return None, False
    try:
        body = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, False
    # 只留需要的字段，不把整个响应塞进仓库
    slim = {"count": body.get("count", 0), "query": params}
    if "facets" in body:
        slim["facets"] = body["facets"]
    f.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return slim, False


def bbox(lat, lon, radius_km):
    """圆近似成外接矩形。GBIF 的 geoDistance 参数在批量查询下不稳，
    改用经纬度区间——**比圆更大**，所以它只会更保守（更容易假阳性），
    这与「GBIF 只作弱信号」的定位一致。"""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, abs(__import__("math").cos(
        __import__("math").radians(lat)))))
    return (f"{lat - dlat:.4f},{lat + dlat:.4f}",
            f"{lon - dlon:.4f},{lon + dlon:.4f}")


def months(window):
    (m1, _), (m2, _) = window
    return list(range(m1, m2 + 1)) if m1 <= m2 else [m1, m2]


def birds_crosscheck(cfg, codes, t):
    """鸟类：按学名 × 点位取条数，**仅供与 eBird 比对**。"""
    cache = cfg.dir / "materials" / "_gbif_cache"
    out, cached = {}, 0
    ms = months(cfg.window)
    for i, code in enumerate(codes, 1):
        sci = t.sci(code)
        if not sci:
            continue
        per = {}
        for s in cfg.sites:
            la, lo = bbox(float(s["lat"]), float(s["lon"]), float(s["半径km"]))
            d, hit = fetch({"scientificName": sci, "decimalLatitude": la,
                            "decimalLongitude": lo, "month": ms, "limit": 0},
                           cache, f"site_{s['id']}_{sci.replace(' ', '_')}")
            cached += hit
            per[s["id"]] = (d or {}).get("count", 0)
        out[code] = {"sci": sci, "sites": per}
        if i % 25 == 0:
            print(f"    ... {i}/{len(codes)} 种（缓存命中 {cached}）")
    p = cfg.data / "gbif_sites.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"  写出 {p.name}: {len(out)} 种 × {len(cfg.sites)} 点位")
    return out


def nonbird(cfg, taxon):
    """非鸟类群：按点位取该类群的 top 物种。

    **这一层没有 eBird 数据源**，所以它的产出被标记为第三方，
    单独成篇、不计入总种数、不进概率模型。
    """
    key = TAXON_KEYS.get(taxon)
    if not key:
        sys.exit(f"未知类群 {taxon}，可选: {sorted(TAXON_KEYS)}")
    cache = cfg.dir / "materials" / "_gbif_cache"
    ms = months(cfg.window)
    out = {}
    for s in cfg.sites:
        la, lo = bbox(float(s["lat"]), float(s["lon"]), float(s["半径km"]))
        d, _ = fetch({"classKey": key, "decimalLatitude": la,
                      "decimalLongitude": lo, "month": ms, "limit": 0,
                      "facet": "speciesKey", "facetLimit": 30},
                     cache, f"nonbird_{taxon}_{s['id']}")
        counts = []
        for f in (d or {}).get("facets", []):
            if f.get("field") == "SPECIES_KEY":
                counts = [{"speciesKey": c["name"], "count": c["count"]}
                          for c in f.get("counts", [])]
        out[s["id"]] = {"total": (d or {}).get("count", 0), "top": counts}
        print(f"  {s['id']:12s} {taxon:10s} {out[s['id']]['total']:6d} 条，"
              f"top {len(counts)} 种")
    p = cfg.data / f"gbif_{taxon.lower()}.json"
    p.write_text(json.dumps(
        {"_meta": {"source": "GBIF occurrence/search",
                   "taxon": taxon, "classKey": key, "months": ms,
                   "warning": "第三方数据，无 eBird 来源；"
                              "不计入总种数，不进概率模型"},
         "sites": out}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"  写出 {p.name}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--taxa", help=f"非鸟类群: {sorted(TAXON_KEYS)}；"
                                   f"不给则做鸟类的 double check")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    cfg = TripConfig(a.trip)
    cfg.data.mkdir(parents=True, exist_ok=True)

    if a.taxa:
        print(f"GBIF 非鸟类群 {a.taxa}（第三方，无 eBird 来源）")
        nonbird(cfg, a.taxa)
        return

    f = cfg.data / "ebird_region_spplist.json"
    if not f.exists():
        sys.exit(f"缺 {f}；先跑 engine/sources/ebird.py --step spplist")
    codes = json.loads(f.read_text(encoding="utf-8"))["species"]
    t = T.load()
    codes = [c for c in codes if c in t.sp]
    print(f"GBIF double check：{len(codes)} 种 × {len(cfg.sites)} 点位"
          f"（第三方，只作比对，不覆盖 eBird）")
    birds_crosscheck(cfg, codes, t)


if __name__ == "__main__":
    main()
