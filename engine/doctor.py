#!/usr/bin/env python3
"""排障自检：出问题时**第一个**该跑的脚本。

用法:
    python3 -I engine/doctor.py --trip trips/<id>
    python3 -I engine/doctor.py --trip trips/<id> --net      # 连带测网络与 key
    python3 -I engine/doctor.py --trip trips/<id> --determinism  # 测构建确定性

为什么需要它
------------
这套工具的失败大多**不是报错，而是悄悄给出错的结果**：
限速响应被当成空数据、表格分隔行解析不了导致整表读成空、
缓存里混进了损坏文件、分母为 0 让频次全变 0。
这些都不会抛异常，只会让产出静静地变错。

所以 doctor 专门查这类「静默故障」，并对每一项说清
**症状是什么、影响什么、怎么修**。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "sources"))
import mdtable as M                                      # noqa: E402

OK, WARN, BAD = "✅", "⚠️ ", "❌"


def line(status, what, detail="", fix=""):
    print(f"{status} {what}")
    if detail:
        print(f"      {detail}")
    if fix:
        print(f"      → {fix}")


def check_refdata():
    print("\n【全局参考数据】所有行程共用，缺了任何一项都跑不起来")
    rd = ENGINE / "refdata"
    tax = rd / "ebird_taxonomy.json"
    if tax.exists():
        n = len(json.loads(tax.read_text(encoding="utf-8"))["species"])
        line(OK if n > 10000 else WARN, f"eBird 分类骨干 {n} 种",
             "" if n > 10000 else "数量异常偏少，可能是抓取被截断",
             "" if n > 10000 else "python3 -I engine/refdata/fetch_taxonomy.py --force")
    else:
        line(BAD, "eBird 分类骨干缺失", str(tax),
             "python3 -I engine/refdata/fetch_taxonomy.py")

    iocs = sorted(rd.glob("ioc_*_zh.json"))
    if iocs:
        d = json.loads(iocs[-1].read_text(encoding="utf-8"))
        zh = sum(1 for v in d.values() if v.get("zh"))
        line(OK, f"IOC 中文名字典 {iocs[-1].name}：{len(d)} 种，有中文名 {zh}")
    else:
        line(BAD, "IOC 中文名字典缺失",
             "没有它，境外特有种全部只有英文名"
             "（eBird 的 zh_SIM 只覆盖中国有记录的种）",
             "python3 -I engine/refdata/fetch_ioc.py")

    idx = rd / "endemic_index.json"
    if idx.exists():
        d = json.loads(idx.read_text(encoding="utf-8"))
        failed = d.get("failed", [])
        line(OK if not failed else WARN,
             f"全地区名录倒排：{d['n_regions']} 个地区，{len(d['where'])} 种",
             "" if not failed else
             f"{len(failed)} 个地区没取到 {failed[:6]}"
             f"——**缺地区会把非特有种误判成特有**",
             "" if not failed else
             "python3 -I engine/endemism.py --world-cache（续抓，已成功的走缓存）")
    else:
        line(BAD, "特有种索引缺失", "", "python3 -I engine/endemism.py --world-cache")


def check_config(trip):
    print("\n【行程配置】")
    d = Path(trip)
    need = ["trip.md", "sites.md", "itinerary.md"]
    for f in need:
        line(OK if (d / f).exists() else BAD, f,
             "" if (d / f).exists() else "必需", "")
    if not (d / "trip.md").exists():
        return None

    meta = M.kv(d / "trip.md")
    for k in ("id", "region", "dates", "ebird_years", "ebird_window"):
        line(OK if k in meta else BAD, f"trip.md: {k} = {meta.get(k, '缺')}")

    # 表能不能读出来——读成空是最常见的静默故障
    for f, sec in [("sites.md", "观鸟点位"), ("itinerary.md", "时段表"),
                   ("targets.md", "别名表"), ("targets.md", "关注科目"),
                   ("todos.md", "① 一次性"), ("logistics.md", "服务项目")]:
        p = d / f
        if not p.exists():
            line(WARN, f"{f} 不存在（可选）")
            continue
        n = len(M.table(p, sec))
        line(OK if n else WARN, f"{f} 的「{sec}」表：{n} 行",
             "" if n else "读成空表——**这是静默故障**，表格分隔行可能写错了",
             "" if n else "分隔行要形如 |---|---| 或 |:-:|---|")
    return meta


def check_data(trip):
    print("\n【取数结果】")
    d = Path(trip) / "data"
    if not d.exists():
        line(BAD, "data/ 不存在", "", f"python3 -I engine/sources/ebird.py --trip {trip}")
        return

    f = d / "ebird_region_spplist.json"
    if f.exists():
        v = json.loads(f.read_text(encoding="utf-8"))
        line(OK, f"地区名录 {v['region']}：{v['n']} 种")
    else:
        line(BAD, "地区名录缺失", "", "engine/sources/ebird.py --step spplist")

    f = d / "ebird_home_spplist.json"
    line(OK if f.exists() else WARN,
         "母语区名录" + (
             f"：{json.loads(f.read_text(encoding='utf-8'))['n']} 种"
             if f.exists() else " 缺失"),
         "" if f.exists() else "缺了就没有「生涯新种」一档",
         "" if f.exists() else "在 trip.md 里设 home_region，再跑 --step spplist")

    f = d / "ebird_freq.json"
    if not f.exists():
        line(BAD, "频次数据缺失", "", "engine/sources/ebird.py --step freq")
        return
    v = json.loads(f.read_text(encoding="utf-8"))
    meta = v.get("_meta", {})
    den = meta.get("denominators", {})
    nfail = meta.get("failed_requests", 0)
    line(OK if not nfail else BAD, f"频次：{len(v) - 1} 种",
         "" if not nfail else
         f"**{nfail} 个请求永久失败——频次里有看不见的空洞**"
         f"（分母偏小，某些种凭空消失）",
         "" if not nfail else
         f"python3 -I engine/sources/ebird.py --trip {trip} --step freq"
         f"（已成功的走缓存，只补缺口）")
    for sid, n in sorted(den.items()):
        if n == 0:
            line(BAD, f"点位 {sid} 分母为 0",
                 "该点位没有任何观鸟日数据，它的所有频次都会是 0",
                 "检查 sites.md 里这个点位的 locId / 坐标是否正确")
        elif n < 10:
            line(WARN, f"点位 {sid} 分母只有 {n} 个观鸟日",
                 "样本太小，频次统计噪声大，该点位的结论要打问号",
                 "考虑放宽 trip.md 的 ebird_window 或 ebird_years")

    hs = d / "ebird_hotspots.json"
    if hs.exists():
        h = json.loads(hs.read_text(encoding="utf-8"))
        radius = [k for k, v in sorted(h.items()) if "半径搜" in v["via"]]
        if radius:
            line(WARN, f"{len(radius)} 个点位用的是半径搜索：{radius}",
                 "半径搜对相邻点位可能返回**完全相同的热点**，"
                 "实测出过「公园的频次其实是整个镇区的」",
                 "在 sites.md 里给关键点位钉死 locId")


def check_cache(trip):
    print("\n【缓存健康】损坏的缓存会被当成「那天没数据」")
    cdir = Path(trip) / "materials" / "_ebird_cache"
    if not cdir.exists():
        line(WARN, "无 eBird 缓存目录（还没取过数）")
        return
    files = list(cdir.glob("*.json"))
    bad = []
    for f in files:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            bad.append(f.name)
    line(OK if not bad else BAD, f"eBird 缓存 {len(files)} 份",
         "" if not bad else f"{len(bad)} 份损坏: {bad[:5]}",
         "" if not bad else f"删掉损坏文件后重跑取数：rm {cdir}/<文件>")


def check_net():
    print("\n【网络与 key】")
    key = os.environ.get("EBIRD_API_KEY", "").strip()
    src = "环境变量"
    if not key:
        f = ROOT / ".ebird_api_key"
        if f.exists():
            key, src = f.read_text(encoding="utf-8").strip(), str(f)
    if not key:
        line(BAD, "没有 eBird API key", "",
             "export EBIRD_API_KEY=<key> 或放在 .ebird_api_key。"
             "申请：https://ebird.org/api/keygen")
        return
    line(OK, f"找到 key（来源：{src}）", "**不打印 key 本身**")

    r = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "25", "-H", f"X-eBirdApiToken: {key}",
         "https://api.ebird.org/v2/ref/region/list/country/world?fmt=json"],
        capture_output=True, text=True)
    code = r.stdout.strip()
    if code == "200":
        line(OK, "eBird API 可达且 key 有效")
    elif code == "429":
        line(WARN, "eBird 正在限速（429）",
             "这是正常的保护机制，不是 key 失效。实测突发请求过多后可持续数小时",
             "降低 --rate，或等一段时间再取；已缓存的数据不受影响")
    elif code in ("401", "403"):
        line(BAD, f"key 被拒（HTTP {code}）", "", "检查 key 是否正确/过期")
    else:
        line(BAD, f"eBird 不可达（HTTP {code or '无响应'}）",
             "注意：python3 -I 隔离模式**不读代理环境变量**，"
             "所以本项目一律用 curl 取数；curl 会读 https_proxy",
             "需要代理就 export https_proxy=...")


def check_determinism(trip):
    print("\n【构建确定性】同样的输入必须产出同样的文档")
    out = Path(trip) / "out"
    before = {f.name: f.read_text(encoding="utf-8")
              for f in sorted(out.glob("*.md"))} if out.exists() else {}
    if not before:
        line(WARN, "还没有产出文档，跳过", "", f"engine/build.py --trip {trip}")
        return
    r = subprocess.run(["python3", "-I", str(ENGINE / "build.py"),
                        "--trip", trip], cwd=ROOT, capture_output=True,
                       text=True)
    if r.returncode != 0:
        line(BAD, "重建失败", r.stdout[-300:])
        return
    after = {f.name: f.read_text(encoding="utf-8")
             for f in sorted(out.glob("*.md"))}
    diff = sorted(k for k in set(before) | set(after)
                  if before.get(k) != after.get(k))
    line(OK if not diff else BAD, f"重建 {len(after)} 份文档，逐字节比对",
         "" if not diff else f"**产物漂移**: {diff}",
         "" if not diff else
         "常见原因是生成器无序遍历 set；engine/verify.py 有专项检查")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--net", action="store_true", help="连带测网络与 key")
    ap.add_argument("--determinism", action="store_true",
                    help="重建一次并逐字节比对（会覆盖 out/）")
    a = ap.parse_args()

    print(f"排障自检：{a.trip}")
    check_refdata()
    meta = check_config(a.trip)
    if meta:
        check_data(a.trip)
        check_cache(a.trip)
    if a.net:
        check_net()
    if a.determinism:
        check_determinism(a.trip)
    print("\n说明：⚠️ 是提醒不是错误；❌ 需要处理。"
          "每条都给了修复命令。")


if __name__ == "__main__":
    main()
