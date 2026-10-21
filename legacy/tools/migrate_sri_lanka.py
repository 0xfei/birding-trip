#!/usr/bin/env python3
"""一次性迁移：把 `scripts/` 里硬编码的判断表导成 `trips/<id>/*.md` 配置。

用法:
    python3 -I tools/migrate_sri_lanka.py            # 预览，不写盘
    python3 -I tools/migrate_sri_lanka.py --write    # 落盘

为什么要写这个脚本，而不是手敲配置
----------------------------------
要迁的内容里有大量**逐字符保真的值**：eBird 热点 `locId`、点位经纬度、
时段起止时刻、报价数字。这些一旦经人工转写或自然语言转述就可能出错，
而 `locId` 错一个字符，整个点位的频次数据就会悄悄取到别的地方去
（全局准则 7：逐字符保真的值禁止走 LLM 生成链路）。

所以：**用 import 把那些 Python 表直接读进来，再原样渲染成 Markdown**。

迁移范围
--------
  scripts/fetch_gbif_season.py : SITES        -> sites.md（坐标、半径）
  scripts/fetch_ebird_feb.py   : HOTSPOT_PIN  -> sites.md（钉死的 locId）
  scripts/build_field_manual.py: DAYS         -> itinerary.md（逐日时段）
  scripts/todos.py             : 四层待办      -> todos.md
  scripts/price_check.py       : ITEMS/汇率    -> logistics.md

这是**一次性**脚本：迁完、回归签字、`scripts/` 退役之后它就没用了，
但保留在仓库里作为「这些数字是从哪来的」的证据。
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIP = ROOT / "trips" / "sri-lanka-2027-02"


def load_module(name):
    """从 scripts/ 载入一个模块（它们不是包，只能按路径载）。"""
    p = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def cell(s):
    """转义单元格里的竖线与换行，使表格不被内容撑破。"""
    return (str(s).replace("|", r"\|").replace("\n", " ").strip()
            if s is not None else "")


def render_sites(gbif, ebird):
    """SITES（坐标半径）+ HOTSPOT_PIN（钉死的 locId）合成一张点位表。"""
    pin = ebird.HOTSPOT_PIN
    lines = [
        "# 观鸟点位",
        "",
        "每一行是一个**取数点位**：eBird 频次与 GBIF 记录都按这里的坐标/热点来取。",
        "",
        "`eBird locId` 留空则退回按半径搜热点——**但那会串点**。",
        "实测事故（2026-10-16）：kitulgala 与 makandawa、nuwara 与 victoria",
        "各自取到了**完全相同的三个热点**，于是「Victoria Park 的频次」",
        "其实是整个 Nuwara Eliya 镇区的；sinharaja 还取到了两个 Kudawa（北侧）热点，",
        "而我们住 Deniyaya、走的是**南侧**——两侧是完全不同的一套点位和鸟导。",
        "所以关键点位一律**显式钉死 locId**。",
        "",
        "> **坐标与半径是判断，不是官方边界**：按地图估的中心点，",
        "> 半径按该点实际活动范围取，统一偏保守（宁可小一点）。",
        "> 半径取大会把邻近生境的记录算进来——",
        "> 2026-10-19 的「瘤鸭事件」就是 Mirissa 的 30 km 半径把内陆水体算了进来。",
        "",
        "| id | 名称 | lat | lon | 半径km | eBird locId（钉死） |",
        "|---|---|---|---|---|---|",
    ]
    for sid, label, lat, lon, radius in gbif.SITES:
        lines.append(f"| {sid} | {cell(label)} | {lat} | {lon} | {radius} "
                     f"| {' '.join(pin.get(sid, []))} |")
    missing = [s for s in pin if s not in {x[0] for x in gbif.SITES}]
    if missing:
        lines += ["", f"> ⚠ HOTSPOT_PIN 里有 SITES 没有的点位: {missing}"]
    return "\n".join(lines) + "\n"


def render_itinerary(fm):
    """DAYS -> 逐日时段表。

    原结构: DAYS = [(日期, [(时段, 标题, 点位, 带队, 夜探?, 说明), ...]), ...]
    说明文字里带 Markdown 粗体与鸟名，**原样搬**——它是经验层，不是数据。
    """
    lines = [
        "# 行程（逐日逐时段）",
        "",
        "一行一个**时段**。这张表是全项目行程的**单一来源**：",
        "现场手册、待办、概率模型都从这里读，不许任何生成器再自己写一份",
        "（迁移前它在三个脚本里各写了一遍，口径已经开始走样）。",
        "",
        "`形式` 的取值与含义（它同时决定概率模型的权重与现场手册的章节组织）：",
        "",
        "| 形式 | 含义 | 模型权重 |",
        "|---|---|---|",
        "| `birding` | 常规步行观鸟 | 1.0 |",
        "| `pelagic` | 出海 | 1.0 |",
        "| `hike` | 长距离徒步，以赶路为主 | 0.9 |",
        "| `safari` | 车上观察，覆盖广但停留少 | 0.8 |",
        "| `night-walk` / `night-drive` | 夜探 | 0.7 |",
        "| `transfer` | 转场，沿途机会 | 0.3 |",
        "| `rest` | 休息，不计观鸟产出 | 0 |",
        "",
        "## 时段表",
        "",
        "| 日期 | 时段 | 地点 | 点位 | 形式 | 带队 | 夜探 | 说明 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for date, blocks in fm.DAYS:
        for time, title, site, guide, night, note in blocks:
            # 形式按原数据推断，迁移后由人复核——故在下方另列待复核清单
            mode = ("night-walk" if night else
                    "transfer" if site is None else "birding")
            lines.append(
                f"| {date} | {cell(time)} | {cell(title)} | {cell(site) or '—'} "
                f"| {mode} | {cell(guide)} | {'✓' if night else ''} "
                f"| {cell(note)} |")
    lines += [
        "",
        "> **`形式` 一列是迁移时按原数据机械推断的**（有点位=birding、",
        "> 无点位=transfer、夜探=night-walk），**尚未人工复核**。",
        "> 已知至少两处需要改：02-07 Yala 全天应为 `safari`、",
        "> 02-07 晚上应为 `night-drive`、02-05 霍顿平原 9 km 应为 `hike`、",
        "> 02-11 观鲸应为 `pelagic`。复核后删掉这段提示。",
    ]
    return "\n".join(lines) + "\n"



def render_todos(td):
    """四层待办 -> todos.md。

    原结构在 `scripts/todos.py` 里是四个 Python 常量。四层的划分本身是
    这个项目最有价值的经验之一（见那个模块的文档），**原样保住**：

      ① 一次性，出发前办完
      ② 每位鸟导都走一遍（模板，按鸟导分段展开）
      ③ 每个观鸟时段都做（模板，自助同样适用）
      ④ 某一段专属（key = 日期 + 时段，必须与 itinerary.md 对得上）
    """
    L = [
        "# 待办（四层）",
        "",
        "待办的**单一来源**。四层的划分来自实测教训：",
        "",
        "原先一次性待办在一份文档、而十几条「到店先问 / 提前让鸟导 /",
        "到现场确认」散在另一份文档的正文里，**一条都没进任何待办表**——",
        "清晨 5:30 在林子里根本翻不到。并且**完全没有「每次」的模板**，",
        "同一件事（确认英文名口径、预习叫声、问老点是否失效）",
        "在四段鸟导那里要重复想四遍。",
        "",
        "> 级别只允许 🔴（必须办完）／🟡（问一句就行）／🟢（到店再办）。",
        "",
        "## ① 一次性：出发前办完",
        "",
        "| 级别 | 事项 | 为什么 |",
        "|:-:|---|---|",
    ]
    for lv, what, why in td.ONE_OFF:
        L.append(f"| {lv} | {cell(what)} | {cell(why)} |")
    L += ["", "## ② 每位鸟导都走一遍", "",
          "模板。每段鸟导各走一遍，不要只对第一位说。", "",
          "| 级别 | 事项 | 为什么 |", "|:-:|---|---|"]
    for lv, what, why in td.PER_GUIDE:
        L.append(f"| {lv} | {cell(what)} | {cell(why)} |")
    L += ["", "## ③ 每个观鸟时段都做", "",
          "模板。**自助时段同样适用**。", "",
          "| 级别 | 事项 | 为什么 |", "|:-:|---|---|"]
    for lv, what, why in td.PER_SESSION:
        L.append(f"| {lv} | {cell(what)} | {cell(why)} |")
    L += ["", "## ④ 某一段专属", "",
          "`日期` + `时段` 必须与 `itinerary.md` 的时段表**逐字对得上**，",
          "由 verify 反向校验——对不上的待办永远不会被渲染出来，等于丢了。", "",
          "| 日期 | 时段 | 事项 |", "|---|---|---|"]
    for (date, time), items in td.BLOCK.items():
        for it in items:
            L.append(f"| {date} | {cell(time)} | {cell(it)} |")
    return "\n".join(L) + "\n"


def render_logistics(pc):
    """报价表 + 汇率 -> logistics.md。

    **每一个数字都由 import 读出，不经人工转写**（全局准则 7）。
    报价是要拿去付钱的，转错一位就是真金白银。
    """
    L = [
        "# 物流与报价",
        "",
        "> ⚠ **下面每一个数都是市场行情量级的经验判断，不是任何运营商的实际报价。**",
        "> 门票由园方定价、含多项税费且近年多次上调，",
        "> **不要拿这里的数字去付款**。拿到真实报价后直接改这张表再重建。",
        "",
        "## 汇率",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| LKR / CNY | {pc.LKR_PER_CNY} |",
        f"| LKR / USD | {pc.LKR_PER_USD} |",
        f"| 人数 | {pc.PAX} |",
        "",
        "## 服务项目",
        "",
        "`计价` 的含义：`pax` 按人收、`vehicle` 按车收、`svc` 按次/按组收。",
        "",
        "| 项目 | 低USD | 高USD | 计价 | 时长h | 说明 |",
        "|---|---:|---:|---|---:|---|",
    ]
    for name, lo, hi, per, hours, note in pc.ITEMS:
        L.append(f"| {cell(name)} | {lo} | {hi} | {per} | {hours} "
                 f"| {cell(note)} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="落盘；默认只预览")
    a = ap.parse_args()

    gbif = load_module("fetch_gbif_season")
    ebird = load_module("fetch_ebird_feb")
    fm = load_module("build_field_manual")
    td = load_module("todos")
    pc = load_module("price_check")

    out = {
        "sites.md": render_sites(gbif, ebird),
        "itinerary.md": render_itinerary(fm),
        "todos.md": render_todos(td),
        "logistics.md": render_logistics(pc),
    }
    for name, body in out.items():
        p = TRIP / name
        if a.write:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            print(f"写出 {p.relative_to(ROOT)}  ({len(body.splitlines())} 行)")
        else:
            print(f"===== {name} ({len(body.splitlines())} 行) =====")
            print(body)


if __name__ == "__main__":
    main()
