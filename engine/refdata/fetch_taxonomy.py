#!/usr/bin/env python3
"""抓 eBird 全球分类骨干，作为全项目的**物种主键来源**。

用法:
    EBIRD_API_KEY=<key> python3 -I engine/refdata/fetch_taxonomy.py
    EBIRD_API_KEY=<key> python3 -I engine/refdata/fetch_taxonomy.py --force
    python3 -I engine/refdata/fetch_taxonomy.py --report      # 只读缓存

为什么是「主键来源」
--------------------
本项目的权威数据源只有 eBird。所有匹配、统计、分档、去重的键
一律是 eBird **`speciesCode`**（如 `srllbm1`）——不是学名、更不是中文名。

理由：学名会随分类修订变（同一只鸟在 IOC 与 Clements 下属名不同），
中文名更是一鸟多名。只有 `speciesCode` 在 eBird 体系内稳定且唯一，
而我们所有的分布、频次、名录数据都来自 eBird，必须用它自己的键去对。

两份拉取
--------
1. `locale=en`     —— 权威英文名（**要原样发给当地鸟导的那个字符串**）、学名、科、目；
2. `locale=zh_SIM` —— eBird 自带中文名，只覆盖「中国有记录的种」，
   在本项目里**仅作中文名查找链的最后一环兜底**（IOC 查不到时才用）。

API key（全局准则 7）
---------------------
**key 只从环境变量 `EBIRD_API_KEY` 读**，其次读仓库根的 `.ebird_api_key`；
绝不写进任何生成物，也不经自然语言链路转述。
免费申请：https://ebird.org/api/keygen

为什么用 curl：`python3 -I` 隔离模式不读代理环境变量，urllib 在本机会 DNS 失败。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
API = "https://api.ebird.org/v2/ref/taxonomy/ebird"
OUT = HERE / "ebird_taxonomy.json"


def api_key():
    k = os.environ.get("EBIRD_API_KEY", "").strip()
    if k:
        return k
    f = ROOT / ".ebird_api_key"
    if f.exists():
        k = f.read_text(encoding="utf-8").strip()
        if k:
            return k
    sys.exit("缺 eBird API key：export EBIRD_API_KEY=<key>，"
             "或放在仓库根的 .ebird_api_key。申请：https://ebird.org/api/keygen")


def fetch(locale, key):
    url = f"{API}?fmt=json&cat=species&locale={locale}"
    r = subprocess.run(
        ["curl", "-sS", "--max-time", "180", "-H", f"X-eBirdApiToken: {key}", url],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"curl 失败 rc={r.returncode}: {r.stderr.strip()[:200]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"eBird 返回的不是 JSON（前 200 字）: {r.stdout[:200]}")
    if not isinstance(d, list) or len(d) < 10_000:
        sys.exit(f"locale={locale} 只返回 {len(d) if isinstance(d, list) else '?'} 条，"
                 f"远少于预期的 ~11,000，拒绝写入。")
    return d


def has_cjk(s):
    return any("一" <= c <= "鿿" for c in s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    if a.report or (OUT.exists() and not a.force):
        if not OUT.exists():
            sys.exit(f"缓存不存在: {OUT}（先不带 --report 跑一次）")
        d = json.loads(OUT.read_text(encoding="utf-8"))
        zh = sum(1 for v in d["species"].values() if v.get("zh_ebird"))
        print(f"eBird 分类缓存: {len(d['species'])} 种"
              f"（taxonomy {d.get('version', '?')}）")
        print(f"  自带中文名 zh_SIM: {zh} 种 "
              f"({100 * zh / max(len(d['species']), 1):.0f}%)"
              f" —— 只覆盖中国有记录的种，境外特有种基本为空，故需 IOC 补")
        return

    key = api_key()
    print("拉 eBird 分类 locale=en ...")
    en = fetch("en", key)
    print("拉 eBird 分类 locale=zh_SIM ...")
    zh = {r["speciesCode"]: r.get("comName", "") for r in fetch("zh_SIM", key)}

    species = {}
    for r in en:
        c = r["speciesCode"]
        z = zh.get(c, "")
        species[c] = {
            "sci": r.get("sciName", ""),
            "en": r.get("comName", ""),
            # zh_SIM 对「中国没有的种」直接回落成英文名，那种不算中文名
            "zh_ebird": z if has_cjk(z) else "",
            "family": r.get("familyComName", ""),
            "family_sci": r.get("familySciName", ""),
            "order": r.get("order", ""),
            "order_num": r.get("taxonOrder", 0),
        }

    OUT.write_text(json.dumps(
        {"source": "eBird API v2 /ref/taxonomy/ebird?cat=species",
         "version": (en[0].get("taxonomyVersion") if en else "") or "",
         "species": species},
        ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
    n_zh = sum(1 for v in species.values() if v["zh_ebird"])
    print(f"写出 {OUT.name}: {len(species)} 种，自带中文名 {n_zh} 种")


if __name__ == "__main__":
    main()
