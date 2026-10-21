#!/usr/bin/env python3
"""一键重建一趟行程的全部产出。**任一步非零退出立即停。**

用法:
    python3 -I engine/build.py --trip trips/<id>
    python3 -I engine/build.py --trip trips/<id> --offline    # 不联网，只用缓存
    python3 -I engine/build.py --trip trips/<id> --fetch      # 连带重新取数

为什么必须有这个脚本
--------------------
校验脚本**只读产出的 `.md` 文件，发现不了生成器崩了**。
原项目实测踩过一次：某个生成器抛 `NameError` 退出、文档停在旧版本，
而校验照样报「全部通过」——因为它校验的是上一次成功生成的旧文件。

所以**生成与校验必须串在一起跑**，中间任何一步非零退出就停。
改了生成器就用这个脚本，不要只跑单个渲染器。

取数不在默认流水线里
--------------------
eBird 的频次步骤要上千个请求、会被限流、且结果已缓存
（见 `engine/sources/ebird.py` 顶部的限速说明）。
所以默认**不重新取数**，只用已缓存的数据重建文档。
真要刷新加 `--fetch`。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent

# (标题, 相对 ROOT 的脚本, 是否取数步骤)
STEPS = [
    ("参考数据：eBird 分类骨干", "engine/refdata/fetch_taxonomy.py", True),
    ("参考数据：IOC 中文名字典", "engine/refdata/fetch_ioc.py", True),
    ("取数：eBird 名录 / 热点 / 频次", "engine/sources/ebird.py", True),
    ("判定：特有种（eBird 全地区倒排）", "engine/endemism.py", False),
    ("产出 01：鸟种清单", "engine/render/species_list.py", False),
    ("产出 02：行程表", "engine/render/itinerary.py", False),
    ("产出 03：第三方分歧", "engine/render/discrepancy.py", False),
    ("产出 04：预期产出", "engine/estimate.py", False),
    ("产出 05：行前与物流", "engine/render/logistics.py", False),
]

# 不接受 --trip 的脚本（全局参考数据，与行程无关）
NO_TRIP = {"engine/refdata/fetch_taxonomy.py", "engine/refdata/fetch_ioc.py"}


def run(label, script, trip, extra=()):
    cmd = ["python3", "-I", str(ROOT / script)]
    if script not in NO_TRIP:
        cmd += ["--trip", trip]
    cmd += list(extra)
    print(f"\n=== {label} ===")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"\n✗ 失败于「{label}」（{script}，退出码 {r.returncode}）\n"
                 f"  流水线已停止——**文档可能停留在上一次的旧版本**，"
                 f"不要拿它当最新结果。")
    print(f"  （{time.time() - t0:.1f}s）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--fetch", action="store_true",
                    help="连带重新取数（eBird 频次上千请求，会被限流）")
    ap.add_argument("--offline", action="store_true",
                    help="完全不联网，只用已缓存数据")
    ap.add_argument("--rate", type=int, default=25,
                    help="取数时每分钟请求数上限")
    a = ap.parse_args()

    trip = str(Path(a.trip))
    if not (Path(trip) / "trip.md").exists():
        sys.exit(f"{trip} 下没有 trip.md")

    t0 = time.time()
    for label, script, is_fetch in STEPS:
        if is_fetch and not a.fetch:
            # 参考数据已存在就跳过；频次步骤默认不跑
            if script == "engine/sources/ebird.py":
                print(f"\n=== {label} ===\n  跳过（默认不重新取数，"
                      f"要刷新加 --fetch）")
                continue
        extra = []
        if a.offline and script == "engine/sources/ebird.py":
            extra = ["--report"]
        if a.fetch and script == "engine/sources/ebird.py":
            extra = ["--rate", str(a.rate)]
        run(label, script, trip, extra)

    out = Path(trip) / "out"
    print(f"\n{'=' * 52}")
    print(f"全部重建完成（{time.time() - t0:.1f}s）。产出在 {out}/：")
    for f in sorted(out.glob("*.md")):
        print(f"  {f.name}  ({len(f.read_text(encoding='utf-8').splitlines())} 行)")


if __name__ == "__main__":
    main()
