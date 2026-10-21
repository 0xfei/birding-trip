#!/usr/bin/env python3
"""eBird 取数适配器：**本项目唯一的权威数据源**。

用法:
    EBIRD_API_KEY=<key> python3 -I engine/sources/ebird.py --trip trips/<id>
    EBIRD_API_KEY=<key> python3 -I engine/sources/ebird.py --trip trips/<id> --step spplist
    python3 -I engine/sources/ebird.py --trip trips/<id> --report    # 只读缓存，不联网

取三样东西
----------
1. **地区名录** `product/spplist/{region}` —— 这个地区记录过哪些种。
2. **热点** `ref/hotspot/geo` —— 没钉死 locId 的点位，按半径搜。
3. **频次** `data/obs/{locId}/historic/{y}/{m}/{d}` —— 核心产出：
   **「取样窗口内，有多少比例的观鸟日能报到这种鸟」**。

为什么频次这个数才有用
----------------------
GBIF 给的是**历年累计记录条数**，有两个硬伤：
分不清「十年前有过一笔」和「今年天天有」；**没有分母**——
300 条到底算常见还是罕见，取决于有多少人在那儿看过鸟。

eBird 的 historic 接口按**日期 × 地点**返回当天报到的种，
于是可以算出自带分母的频次，直接回答「我去那天看得到吗」。

钉死热点：为什么不能只靠半径搜
------------------------------
`ref/hotspot/geo` 按半径搜，**对相邻点位会返回完全相同的热点**。
2026-10-16 实测暴露两类错误：

  1. kitulgala 与 makandawa、nuwara 与 victoria **各自取到了一模一样的三个热点**
     —— Victoria Park 就在 Nuwara Eliya 镇里，靠半径永远分不开，
     于是「Victoria Park 的频次」其实是整个镇区的；
  2. sinharaja 取到的三个热点里有两个在 Kudawa（**北侧**），
     而行程住 Deniyaya、走的是**南侧**——两侧是不同的点位和鸟导。
     这是全程最重要的点位，不能用错侧的数据。

所以点位表里可以显式钉死 `locId`（见 `trips/<id>/sites.md`），
钉死了就不搜；没钉死的才按半径搜，并且 `verify` 会对
「两个点位取到相同热点」直接告警。

数据与判断的边界
----------------
- **数据**：eBird 返回的物种 code、日期、地点。逐字符写入缓存，不做任何改写。
- **判断**：点位坐标与半径、每个点取几个热点、钉死哪些 locId。
  这些全在 `trips/<id>/sites.md` 与 `trip.md` 里，**本模块零硬编码**。

API key（全局准则 7）
---------------------
只从环境变量 `EBIRD_API_KEY` 读，其次读仓库根的 `.ebird_api_key`。
绝不写进任何生成物，也不经自然语言链路转述。

为什么用 curl：`python3 -I` 隔离模式不读代理环境变量，urllib 在本机会 DNS 失败。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
ROOT = ENGINE.parent
sys.path.insert(0, str(ENGINE))
import mdtable as M                                    # noqa: E402

API = "https://api.ebird.org/v2"
SLEEP = 0.12          # 批与批之间的间隔；eBird 未公布硬限速，保持克制
TIMEOUT = 45
BATCH = 20            # 一个 curl 进程打多少个 URL
PARALLEL = 3          # curl --parallel-max；调大更快但更容易被限速
DEFAULT_RATE = 25     # 默认每分钟请求数上限（见下「限速」一节）

# ======================== 限速：实测结论，别再试那三条捷径 ========================
#
# 频次步骤的请求量 = 热点数 × 取样天数。一趟 10 天行程约 **1500 个请求**。
# 2026-10-19 实测：40 分钟内发了约 2500 个请求后，eBird 开始对**每一个**请求
# 返回 `429 Too Many Requests`（**纯文本，不是 JSON**），且持续数小时不恢复，
# 隔夜才解除。所以这一步**必须节流 + 可续抓**，不能指望一次跑完。
#
# 试过并已排除的三条捷径：
#
# 1. **并行**（`curl --parallel`）—— 实测确实快 3 倍以上
#    （10 个请求 0.95s vs 串行 3.1s），但**瓶颈是配额不是带宽**，救不了。
#    并行保留着，只是并行度压到很低。
#
# 2. **barchart 接口**（`ebird.org/barchart?...&fmt=tsv`，一个请求返回整张频次表）
#    —— **被 bot 检测挡住**，返回的是人机验证页（Anubis proof-of-work），
#    不是 TSV。不可用。
#
# 3. **地区级 `historic`**（`/data/obs/{region}/historic/...`，想用
#    「1 请求/地区/天」替代「1 请求/热点/天」，降量 27 倍）
#    —— **死路**。实测它返回的记录**每种只有一条**
#    （斯里兰卡某日：244 条记录 = 244 个不同种，分布在 48 个 locId 上）。
#    每个种只被归到某一个 locId，**无法还原各点位的频次**。
#    返回里确实带 `locId`，很容易误以为可行——所以这条写在这里，别再试。
#
# 结论：老老实实逐热点取，但要**节流、缓存、可续抓**。
# `--rate` 控制每分钟请求数；默认 25/min 偏保守，实测不会触发限流。
# 已成功的请求都落盘，重跑只补缺口，所以中断无损失。


# ---------------------------------------------------------------- key / http

def api_key():
    k = os.environ.get("EBIRD_API_KEY", "").strip()
    if k:
        return k
    f = ROOT / ".ebird_api_key"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("缺 eBird API key：export EBIRD_API_KEY=<key>，"
             "或放在仓库根的 .ebird_api_key。申请：https://ebird.org/api/keygen")


class Client:
    """带磁盘缓存的 eBird 客户端。缓存幂等——删掉文件即可强制重抓。"""

    def __init__(self, cache_dir, key=None, offline=False, rate=DEFAULT_RATE):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._key = key
        # 每分钟请求数上限 -> 每批之后要等多久。限速是这一步的真实瓶颈。
        self.rate = max(1, int(rate))
        self.batch_pause = BATCH * 60.0 / self.rate
        self.hits = self.misses = self.fails = self.throttled = 0
        self.done = 0
        self.failed_samples = []

    @property
    def key(self):
        if self._key is None:
            self._key = api_key()
        return self._key

    def get(self, path, cache_name, default=None, retries=4):
        """取一个 JSON。命中缓存就不发请求。

        失败时返回 `default` 并计数——**不中断整条流水线**：
        单个日期取不到是常态（那天没人提交清单），
        但失败总数会被报出来，异常高就说明是网络或 key 的问题。

        限速必须退避重试，不能静默丢弃
        ------------------------------
        eBird 在高频请求下会返回 `Too Many Requests`（**纯文本，不是 JSON**）。
        这类响应若当成「取不到」丢掉，产出的频次数据会有**静默空洞**：
        分母变小、某些种凭空消失，而且**没有任何迹象**——
        比报错危险得多。所以这里对「可重试的失败」做指数退避，
        重试耗尽才计入 `fails`，并在最后统一报出来。
        """
        f = self.cache / f"{cache_name}.json"
        if f.exists():
            self.hits += 1
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                f.unlink()          # 缓存损坏，当未命中处理
        if self.offline:
            return default
        self.misses += 1
        delay = SLEEP
        for attempt in range(retries):
            r = subprocess.run(
                ["curl", "-sS", "--max-time", str(TIMEOUT),
                 "-H", f"X-eBirdApiToken: {self.key}", f"{API}{path}"],
                capture_output=True, text=True)
            time.sleep(delay)
            if r.returncode == 0:
                try:
                    d = json.loads(r.stdout)
                except json.JSONDecodeError:
                    # 限速与服务端错误都是纯文本；退避后重试
                    if "Too Many Requests" in r.stdout or r.stdout.strip() == "":
                        self.throttled += 1
                        delay = min(delay * 3, 20.0)
                        continue
                    self._fail(f"{path} 非 JSON: {r.stdout[:80]}")
                    return default
                f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                return d
            delay = min(delay * 3, 20.0)
        self._fail(f"{path} 重试 {retries} 次仍失败")
        return default

    def _fail(self, msg):
        self.fails += 1
        if len(self.failed_samples) < 5:
            self.failed_samples.append(msg)

    # ------------------------------------------------------------ 批量并行

    def get_many(self, items, default=None, retries=4, on_progress=None):
        """批量取。`items` 是 `[(path, cache_name), ...]`，返回 `{cache_name: json}`。

        为什么必须批量：**每个请求单独起一个 curl 进程太慢**。
        实测逐个取时约 16 次/分钟——一趟 10 天行程的频次要 1512 个请求，
        就是一个半小时；而频次是每次改行程都可能要重取的东西。
        改成 `curl --parallel` 后一个进程打一批，实测快一个数量级。

        并行度的取舍：`PARALLEL` 调大会更快，但 eBird 会返回
        `Too Many Requests`（纯文本，不是 JSON）。所以：
          - 每批成功后不加速，**失败则把并行度减半并退避重试**；
          - 重试仍失败的才计入 `fails` 并报出来——
            **绝不静默丢弃**，否则频次数据会有看不见的空洞。
        """
        todo, out = [], {}
        for path, name in items:
            f = self.cache / f"{name}.json"
            if f.exists():
                try:
                    out[name] = json.loads(f.read_text(encoding="utf-8"))
                    self.hits += 1
                    continue
                except json.JSONDecodeError:
                    f.unlink()
            if self.offline:
                out[name] = default
            else:
                todo.append((path, name))

        par, delay = PARALLEL, self.batch_pause
        attempt = 0
        while todo and attempt < retries:
            attempt += 1
            failed = []
            for i in range(0, len(todo), BATCH):
                chunk = todo[i:i + BATCH]
                got = self._curl_batch(chunk, par)
                for path, name in chunk:
                    if name in got:
                        out[name] = got[name]
                    else:
                        failed.append((path, name))
                self.done += len(chunk)
                if on_progress:
                    on_progress(self)
                time.sleep(delay)
            todo = failed
            if todo:
                # 批里有失败，大概率是限速：降并行度 + 退避
                self.throttled += len(todo)
                par = max(1, par // 2)
                delay = min(max(delay * 2, 30.0), 300.0)
        for path, name in todo:
            self._fail(f"{path} 重试 {retries} 轮仍失败")
            out[name] = default
        return out

    def _curl_batch(self, chunk, parallel):
        """用一个 curl 进程并行取一批。返回成功解析的 `{cache_name: json}`。

        走 `-K` 配置文件而不是命令行参数：批量 URL 会超出参数长度限制，
        而且配置文件让 **key 不出现在进程命令行里**（`ps` 看不到它）。
        """
        tmp = self.cache / ".batch"
        tmp.mkdir(exist_ok=True)
        cfgp = tmp / "curl.cfg"
        lines = [f'header = "X-eBirdApiToken: {self.key}"',
                 'silent', 'show-error', f'max-time = {TIMEOUT}']
        paths = {}
        for path, name in chunk:
            dest = tmp / f"{name}.part"
            paths[name] = dest
            lines.append(f'url = "{API}{path}"')
            lines.append(f'output = "{dest}"')
        cfgp.write_text("\n".join(lines) + "\n", encoding="utf-8")

        subprocess.run(["curl", "--parallel", "--parallel-max", str(parallel),
                        "-K", str(cfgp)], capture_output=True, text=True)
        self.misses += len(chunk)

        got = {}
        for name, dest in paths.items():
            if not dest.exists():
                continue
            raw = dest.read_text(encoding="utf-8", errors="replace")
            dest.unlink()
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue            # 限速/错误页，留给上层重试
            (self.cache / f"{name}.json").write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8")
            got[name] = d
        return got


# ---------------------------------------------------------------- 行程配置

class TripConfig:
    """读 `trips/<id>/` 下的配置。本模块只读，不写。"""

    def __init__(self, trip_dir):
        self.dir = Path(trip_dir)
        if not (self.dir / "trip.md").exists():
            sys.exit(f"{self.dir} 下没有 trip.md")
        self.meta = M.kv(self.dir / "trip.md")
        self.sites = M.table(self.dir / "sites.md", "观鸟点位")
        if not self.sites:
            sys.exit(f"{self.dir}/sites.md 里没找到「观鸟点位」表")
        self.data = self.dir / "data"
        self.raw = self.dir / "materials" / "_ebird_cache"

    @property
    def region(self):
        return self.meta["region"]

    @property
    def years(self):
        return [int(x) for x in M.split_list(self.meta["ebird_years"])]

    @property
    def window(self):
        """`02-01..02-28` -> `((2,1),(2,28))`。"""
        a, _, b = self.meta["ebird_window"].partition("..")
        am, ad = a.split("-")
        bm, bd = b.split("-")
        return (int(am), int(ad)), (int(bm), int(bd))

    @property
    def hotspots_per_site(self):
        return int(self.meta.get("hotspots_per_site", "3"))

    def pinned(self, site_id):
        for s in self.sites:
            if s["id"] == site_id:
                return M.split_ws(s.get("eBird locId（钉死）", ""))
        return []

    def site_ids(self):
        return [s["id"] for s in self.sites]


def window_dates(window, years):
    """展开取样窗口为 `[(y,m,d), ...]`。跨月的窗口也支持。"""
    (m1, d1), (m2, d2) = window
    out = []
    for y in years:
        cur, end = date(y, m1, d1), date(y, m2, d2)
        while cur <= end:
            out.append((cur.year, cur.month, cur.day))
            cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------- 三个步骤

def step_spplist(cfg, cl):
    """地区名录。写 `data/ebird_region_spplist.json`。"""
    codes = cl.get(f"/product/spplist/{cfg.region}",
                   f"spplist_{cfg.region}", default=[])
    if not codes:
        sys.exit(f"取不到 {cfg.region} 的地区名录（离线且无缓存，或 key 无效）")
    out = {"region": cfg.region,
           "source": "eBird API v2 /product/spplist/{region}",
           "n": len(codes), "species": sorted(codes)}
    (cfg.data / "ebird_region_spplist.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"  {cfg.region} 地区名录: {len(codes)} 种")

    # 母语区名录：用来判定「生涯新种」——目的地有、母语区没有的种。
    # 这是 eBird 原生能力，换任何国家都成立，不需要任何人工名单。
    home = cfg.meta.get("home_region", "").strip()
    if home:
        hc = cl.get(f"/product/spplist/{home}", f"spplist_{home}", default=[])
        if hc:
            (cfg.data / "ebird_home_spplist.json").write_text(
                json.dumps({"region": home, "n": len(hc),
                            "source": "eBird API v2 /product/spplist/{region}",
                            "species": sorted(hc)},
                           ensure_ascii=False, indent=0), encoding="utf-8")
            new_cnt = len(set(codes) - set(hc))
            print(f"  {home} 母语区名录: {len(hc)} 种"
                  f"  ->  {cfg.region} 有而 {home} 没有的: {new_cnt} 种")
        else:
            print(f"  ⚠ 取不到母语区 {home} 的名录，生涯新种一档会缺")
    return codes


def step_hotspots(cfg, cl):
    """为每个点位定出要用的 locId。钉死的直接用，没钉死的按半径搜。

    写 `data/ebird_hotspots.json`，含**每个 locId 的来源**（钉死 / 半径搜）——
    这一列是给 verify 和人看的：半径搜出来的结果要能被质疑。
    """
    out = {}
    for s in cfg.sites:
        sid = s["id"]
        pin = M.split_ws(s.get("eBird locId（钉死）", ""))
        if pin:
            out[sid] = {"locs": pin, "via": "钉死", "name": s.get("名称", "")}
            continue
        hs = cl.get(f"/ref/hotspot/geo?lat={s['lat']}&lng={s['lon']}"
                    f"&dist={s['半径km']}&fmt=json",
                    f"hotspots_{sid}", default=[])
        hs = sorted(hs, key=lambda h: -(h.get("numSpeciesAllTime") or 0))
        picked = hs[: cfg.hotspots_per_site]
        out[sid] = {"locs": [h["locId"] for h in picked],
                    "via": f"半径搜 {s['半径km']}km",
                    "name": s.get("名称", ""),
                    "loc_names": [h.get("locName", "") for h in picked]}
    (cfg.data / "ebird_hotspots.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 串点告警：两个点位用了相同的 locId 集合 —— 这是实测踩过的坑
    groups = {}
    for sid, v in out.items():
        if v["locs"]:
            groups.setdefault(tuple(sorted(v["locs"])), []).append(sid)
    clashes = [g for g in groups.values() if len(g) > 1]
    for sid, v in sorted(out.items()):
        flag = "  ⚠ 与其它点位共用热点" if any(sid in g for g in clashes) else ""
        print(f"  {sid:12s} {len(v['locs'])} 个热点  ({v['via']}){flag}")
    if clashes:
        print(f"  ⚠ 串点告警：{clashes} —— 这些点位的频次会是同一份数据，"
              f"请在 sites.md 里钉死各自的 locId")
    return out


def step_freq(cfg, cl, hotspots):
    """频次：取样窗口内每个点位每一天的清单，算出每个种的上报日比例。

    写 `data/ebird_freq.json`：
        {code: {"sites": {site: {"freq": 0.42, "days": 8, "of": 19}}}}

    `of` 是**分母**（该点位在窗口内有数据的观鸟日数）。
    **没有分母的频次没有意义**，所以它必须跟着一起写出来。

    请求是批量并行发的（见 `Client.get_many`）：
    一趟 10 天行程约 1500 个请求，逐个发要一个半小时。
    """
    dates = window_dates(cfg.window, cfg.years)

    # 先把所有请求列出来，再一次性批量取——这样 curl 能并行，也便于报进度
    reqs, key_of = [], {}
    for sid in cfg.site_ids():
        for loc in hotspots.get(sid, {}).get("locs", []):
            for y, m, d in dates:
                name = f"hist_{loc}_{y}{m:02d}{d:02d}"
                reqs.append((f"/data/obs/{loc}/historic/{y}/{m}/{d}?fmt=json",
                             name))
                key_of[name] = (sid, (y, m, d))
    print(f"  共 {len(reqs)} 个请求（{len(dates)} 天 × "
          f"{sum(len(v['locs']) for v in hotspots.values())} 个热点）")

    def progress(c):
        if c.done % 300 < BATCH:
            print(f"    ... {c.done}/{len(reqs)}"
                  f"（缓存 {c.hits} 新取 {c.misses}"
                  + (f" 限速重试 {c.throttled}" if c.throttled else "") + "）")

    got = cl.get_many(reqs, default=None, on_progress=progress)

    # 聚合：同一个点位的多个热点在同一天的记录合并成「那天在这个点位看到的种」
    per_day = {}        # (site, date) -> set(code) | None 表示那天没数据
    for name, obs in got.items():
        sid, day = key_of[name]
        k = (sid, day)
        if obs is None:
            per_day.setdefault(k, None)
            continue
        cur = per_day.get(k)
        if cur is None:
            cur = set()
        cur |= {o["speciesCode"] for o in obs if o.get("speciesCode")}
        per_day[k] = cur

    # 分母只数「真的有人在那儿观鸟的日子」。
    #
    # 这里曾经有个 bug（2026-10-20 修）：原先把「API 有响应」当成「那天有数据」，
    # 于是**空响应也进了分母**——而空响应的含义是「那天没人提交清单」。
    # 结果每个点位的分母都等于取样窗口的全部天数（56），
    # 频次被系统性低估，越冷门的点位低估越多。
    # **没有清单的日子不是「那天没看到这种鸟」，是「那天没有观测」。**
    seen, denom = {}, {}
    for (sid, _day), codes in per_day.items():
        if not codes:          # None（请求失败）或 set()（当天无人提交清单）
            continue
        denom[sid] = denom.get(sid, 0) + 1
        for c in codes:
            seen.setdefault(c, {}).setdefault(sid, 0)
            seen[c][sid] += 1

    out = {}
    for code, per in sorted(seen.items()):
        out[code] = {"sites": {
            s: {"freq": round(n / denom[s], 4), "days": n, "of": denom[s]}
            for s, n in sorted(per.items()) if denom.get(s)}}
    meta = {"source": "eBird API v2 /data/obs/{locId}/historic",
            "years": cfg.years, "window": cfg.meta["ebird_window"],
            "metric": "freq = 该点位窗口内报到此种的观鸟日 ÷ 该点位窗口内有清单的观鸟日（空清单日不计入分母）",
            "denominators": denom, "n_requests": len(reqs),
            "failed_requests": cl.fails, "failed_sample": cl.failed_samples}
    (cfg.data / "ebird_freq.json").write_text(
        json.dumps({"_meta": meta, **out}, ensure_ascii=False, indent=0),
        encoding="utf-8")

    print(f"  频次: {len(out)} 种，{len(denom)} 个点位有数据")
    for s in cfg.site_ids():
        print(f"    {s:12s} 分母 {denom.get(s, 0):3d} 个观鸟日"
              + ("   ⚠ 分母为 0，该点位无频次数据" if not denom.get(s) else ""))
    if cl.fails:
        # 失败会在频次里留下空洞（分母偏小），必须显式报出来而不是静默接受
        print(f"  ⚠ 失败请求 {cl.fails} 次 —— 频次数据有空洞，"
              f"再跑一次本命令可续抓（已成功的走缓存）")
        print(f"    样例: {cl.failed_samples[:2]}")
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--step", choices=["spplist", "hotspots", "freq", "all"],
                    default="all")
    ap.add_argument("--report", action="store_true", help="离线，只读缓存")
    ap.add_argument("--rate", type=int, default=DEFAULT_RATE,
                    help=f"每分钟请求数上限（默认 {DEFAULT_RATE}）。"
                         f"调高会被 eBird 限流，见模块顶部说明")
    a = ap.parse_args()

    cfg = TripConfig(a.trip)
    cfg.data.mkdir(parents=True, exist_ok=True)
    cl = Client(cfg.raw, offline=a.report, rate=a.rate)

    print(f"行程 {cfg.meta.get('id')} | 地区 {cfg.region} | "
          f"窗口 {cfg.meta['ebird_window']} × {cfg.years}"
          + ("  [离线]" if a.report else ""))

    if a.step in ("spplist", "all"):
        print("1. 地区名录")
        step_spplist(cfg, cl)
    if a.step in ("hotspots", "freq", "all"):
        print("2. 热点")
        hs = step_hotspots(cfg, cl)
    if a.step in ("freq", "all"):
        print("3. 频次（请求数多，首次会慢；缓存后秒回）")
        step_freq(cfg, cl, hs)

    print(f"\n缓存命中 {cl.hits}，新取 {cl.misses}，失败 {cl.fails}"
          + (f"，被限速重试 {cl.throttled} 次" if cl.throttled else ""))


if __name__ == "__main__":
    main()
