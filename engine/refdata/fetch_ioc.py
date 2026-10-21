#!/usr/bin/env python3
"""下载并解析 **IOC World Bird List 多语种版**，产出学名/英文名 → 中文名字典。

用法:
    python3 -I engine/refdata/fetch_ioc.py            # 有缓存则跳过下载
    python3 -I engine/refdata/fetch_ioc.py --force    # 强制重下
    python3 -I engine/refdata/fetch_ioc.py --report   # 只看已有字典的统计

这一层在本项目里的**定位与边界**
--------------------------------
本项目的权威数据源**只有 eBird**：物种在不在名录、分布在哪、什么季节、
出现频率、是否特有——全部以 eBird 为准。

**IOC 在这里只做一件事：把英文名翻译成中文名。**
它不提供任何事实判断，不参与任何匹配、统计、分档、去重——
那些的键一律是 eBird `speciesCode`。中文名是**显示标签**，不是数据。

为什么必须引入它（eBird 的中文名为什么不够用）
----------------------------------------------
eBird 的 `locale=zh_SIM` **只给「中国有记录的种」中文名**，
中国没有的种直接沿用 IOC 英文名。所以它结构性地覆盖不到任何境外特有种。

实测（2026-10-19）：
  - eBird zh_SIM 全球覆盖 1,666 / 11,167 种；
  - **斯里兰卡 35 种特有种，一个中文名都没有**；
  - 换成 IOC 多语种版后：11,227 种里 11,204 种有中文名（99.8%），
    **35 种特有种 35/35 全中**，且与用户提供的叫法一致。

为什么用 xlsx 而不装 openpyxl
-----------------------------
xlsx 本质是 **zip + XML**，标准库 `zipfile` + `xml.etree` 足够解析，
无需任何第三方依赖（本机 Python 3.9 装不了包）。
`sharedStrings.xml` 有 31 万条、`sheet1.xml` 有 20 MB，
所以用 `iterparse` 流式读并及时 `clear()`，否则内存会炸。

为什么用 curl 而不是 urllib
---------------------------
`python3 -I` 的隔离模式**不读代理环境变量**，`urllib` 在本机会 DNS 失败。
这是本项目已知的坑（GBIF/eBird 的取数脚本都踩过）。

版本与换源
----------
IOC 15.2 是该列表的**最后一版**（编者转向 AviList）。
故 `SOURCES` 写成一张表、字典文件名带版本号，换源时只改这张表，
不改解析逻辑；已有缓存不会被新版本静默覆盖。
"""
import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# ========== 判断表：数据源 ==========
# 每条是 (版本, URL, 期望的学名列标题)。取**第一条**为当前源。
# URL 逐字符来自 worldbirdnames.org 的 Master Lists 页面，**不是手敲的**。
SOURCES = [
    ("15.2", "https://worldbirdnames.org/Multiling%20IOC%2015.2.xlsx", "IOC_15.2"),
]

# 列标题（IOC 多语种版表头原文）。中文列就叫 "Chinese"，繁体是 "Chinese (Traditional)"。
COL_EN = "English"
COL_ZH = "Chinese"


def _colnum(ref):
    """`BC12` -> 54（0 基列号）。"""
    n = 0
    for c in ref:
        if c.isalpha():
            n = n * 26 + ord(c.upper()) - 64
        else:
            break
    return n - 1


def _shared_strings(z):
    """流式读 sharedStrings.xml。31 万条，必须 clear()。"""
    out = []
    with z.open("xl/sharedStrings.xml") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == NS + "si":
                out.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    return out


def _rows(z, ss):
    """流式产出每一行：`{列号: 值}`。sheet1.xml 有 20 MB。"""
    with z.open("xl/worksheets/sheet1.xml") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag != NS + "row":
                continue
            d = {}
            for c in el.findall(NS + "c"):
                v = c.find(NS + "v")
                if v is None or v.text is None:
                    continue
                d[_colnum(c.get("r"))] = (ss[int(v.text)]
                                          if c.get("t") == "s" else v.text)
            el.clear()
            yield d


def download(url, dest):
    """用 curl 取文件。下载物单独放一个目录，不与脚本混放。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", "300", "-o", str(dest), url],
        capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 100_000:
        sys.exit(f"下载失败 rc={r.returncode}: {r.stderr.strip()[:200]}\n"
                 f"  URL: {url}\n"
                 f"  若本机需代理，先 export https_proxy=... 再跑（curl 会读它）。")
    return dest


def parse(xlsx, sci_col_title):
    """解析 xlsx，返回 `{学名: {"en":…, "zh":…}}`。

    表头在第一行；学名列的标题随版本变（`IOC_15.2`），故由调用方传入。
    只收**双名法**（含空格）的行，跳过属级/科级汇总行。
    """
    z = zipfile.ZipFile(xlsx)
    ss = _shared_strings(z)
    out, cols, header = {}, {}, True
    for d in _rows(z, ss):
        if header:
            for idx, val in d.items():
                cols[val] = idx
            missing = [c for c in (sci_col_title, COL_EN, COL_ZH) if c not in cols]
            if missing:
                sys.exit(f"表头缺列 {missing}；实际表头: {sorted(cols)[:12]}\n"
                         f"  IOC 换版可能改了列名，请更新 SOURCES / COL_* 常量。")
            header = False
            continue
        sci = d.get(cols[sci_col_title], "")
        if not sci or " " not in sci:
            continue          # 属级/科级行，跳过
        out[sci] = {"en": d.get(cols[COL_EN], ""),
                    "zh": d.get(cols[COL_ZH], "")}
    return out


def dict_path(version):
    return HERE / f"ioc_{version}_zh.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存，重下重解析")
    ap.add_argument("--report", action="store_true", help="只读已有字典并统计")
    a = ap.parse_args()

    version, url, sci_col = SOURCES[0]
    out_path = dict_path(version)

    if a.report or (out_path.exists() and not a.force):
        if not out_path.exists():
            sys.exit(f"字典不存在: {out_path}（先不带 --report 跑一次）")
        d = json.loads(out_path.read_text(encoding="utf-8"))
        zh = sum(1 for v in d.values() if v["zh"])
        print(f"IOC {version} 字典: {len(d)} 种，其中有中文名 {zh} "
              f"({100 * zh / max(len(d), 1):.1f}%)")
        print(f"  路径: {out_path}")
        return

    # 下载物放独立目录（外部不可信数据，不与脚本混放）
    xlsx = HERE / "downloads" / f"ioc_{version}.xlsx"
    if not xlsx.exists():
        print(f"下载 IOC {version} ...")
        download(url, xlsx)
    print(f"解析 {xlsx.name}（{xlsx.stat().st_size / 1e6:.1f} MB）...")
    d = parse(xlsx, sci_col)
    if len(d) < 10_000:
        sys.exit(f"只解析出 {len(d)} 种，远少于预期的 ~11,200——"
                 f"文件可能不完整或表结构变了，拒绝写入。")

    out_path.write_text(
        json.dumps(d, ensure_ascii=False, sort_keys=True, indent=0),
        encoding="utf-8")
    zh = sum(1 for v in d.values() if v["zh"])
    print(f"写出 {out_path.name}: {len(d)} 种，有中文名 {zh} "
          f"({100 * zh / len(d):.1f}%)")


if __name__ == "__main__":
    main()
