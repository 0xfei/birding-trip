#!/usr/bin/env python3
"""名字闸门：**全项目唯一允许「把一个名字变成一个物种」的地方**。

为什么必须收口到一个模块
------------------------
通用化之后，大量判断文本是**由 LLM 从物料（网页/PDF/别人的行程）里读出来的**。
物料里的鸟名五花八门：老图鉴叫法、带连字符的、属名已被拆分的、中文俗名。
只要有任何一处允许「凭名字直接写进文档」，就一定会出现**编造或张冠李戴的鸟名**——
而鸟名错一个字母，当地鸟导就查不到这只鸟。

所以：
  1. 任何外部名字进入本项目，**必须先过 `resolve()` 变成 eBird `speciesCode`**；
  2. 判断文本里提到鸟，**只能写 `{{code}}` 占位**，渲染时由本模块注入；
  3. 解析不出的名字进 `unresolved`，**由人裁决，脚本绝不猜**。

主键
----
全项目的物种主键是 eBird `speciesCode`。学名会随分类修订变，中文名一鸟多名，
只有它在 eBird 体系内稳定唯一——而我们的分布、频次、名录数据全来自 eBird。

中文名的来源与边界
------------------
查找链（`zh()`）：
    eBird 学名 → IOC 学名            （实测命中 99%）
  → eBird 英文名 → IOC 英文名        （累计 99.7%）
  → eBird 自带 zh_SIM                （补 IOC 的漏，如 Gygis candida）
  → **查不到就只写英文名，记进缺失报告，绝不编造**

**IOC 在本项目里只提供翻译，不提供任何事实。**
物种在不在名录、分布、季节、频次、是否特有，一律以 eBird 为准。
中文名是显示标签，**永不参与任何匹配、统计、分档、去重**。

别名
----
`resolve()` 之所以能认出「Sri Lanka Blue-Magpie」就是 eBird 的
「Sri Lanka Blue Magpie」，靠的是规范化（见 `norm()`）而不是模糊匹配——
**不做编辑距离、不做子串猜测**。确实对不上的，由行程配置里的别名表显式声明。
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFDATA = HERE / "refdata"

# IOC 字典文件名带版本号；取目录里版本号最大的那个（换版不改代码）
_IOC_GLOB = "ioc_*_zh.json"

_PUNCT = re.compile(r"[’'`.()]")
_SEPS = re.compile(r"[-–—_/]+")
_WS = re.compile(r"\s+")


def norm(s):
    """名字规范化：只做**确定性的等价折叠**，不做任何模糊猜测。

    折叠的三类差异都是实测遇到过的写法分歧：
      - 大小写：`Chestnut-backed owlet` vs `Chestnut-backed Owlet`
      - 连字符：`Sri Lanka Blue-Magpie` vs `Sri Lanka Blue Magpie`
      - 撇号与点：`Layard's Parakeet` vs `Layards Parakeet`
    中文名里没有这些差异，折叠对它无害。
    """
    s = (s or "").strip()
    s = _PUNCT.sub("", s)
    s = _SEPS.sub(" ", s)
    return _WS.sub(" ", s).lower()


class Taxonomy:
    """eBird 分类骨干 + IOC 中文名，以及由二者构建的反向索引。"""

    def __init__(self, aliases=None):
        tax_f = REFDATA / "ebird_taxonomy.json"
        if not tax_f.exists():
            raise SystemExit(
                f"缺 {tax_f}\n  先跑: python3 -I engine/refdata/fetch_taxonomy.py")
        self.sp = json.loads(tax_f.read_text(encoding="utf-8"))["species"]

        iocs = sorted(REFDATA.glob(_IOC_GLOB))
        if not iocs:
            raise SystemExit(
                f"缺 IOC 中文名字典（{REFDATA}/{_IOC_GLOB}）\n"
                f"  先跑: python3 -I engine/refdata/fetch_ioc.py")
        self.ioc_version = iocs[-1].name
        ioc = json.loads(iocs[-1].read_text(encoding="utf-8"))
        self.ioc_by_sci = ioc
        self.ioc_by_en = {}
        for sci, v in ioc.items():
            if v.get("en"):
                self.ioc_by_en.setdefault(norm(v["en"]), sci)

        # 中文名与 IOC 英文名缓存，以及中文名的来源标记
        self._zh, self._zh_via, self._en_ioc = {}, {}, {}
        for code in self.sp:
            z, via = self._lookup_zh(code)
            self._zh[code] = z
            self._zh_via[code] = via
            hit = self.ioc_by_sci.get(self.sp[code]["sci"])
            if hit and hit.get("en"):
                self._en_ioc[code] = hit["en"]

        # 反向索引：规范化名字 -> {code}。一名对多 code 的留作歧义，不自动选。
        # **eBird 英文名与 IOC 英文名都收**，这样鸟导用哪种叫法都查得到。
        self.index = {}
        for code, r in self.sp.items():
            for key in (code, r["sci"], r["en"],
                        self._en_ioc.get(code), self._zh[code]):
                if key:
                    self.index.setdefault(norm(key), set()).add(code)

        # 行程配置声明的别名：{别名: code}，**显式覆盖**，优先于索引
        self.aliases = {norm(k): v for k, v in (aliases or {}).items()}

    # ---------- 中文名 ----------

    def _lookup_zh(self, code):
        # IOC 表里个别中文名带尾随空格（如 `斯里兰卡绿鸠 `），
        # 直接渲染会在文档里留下可见的多余空格，故统一 strip。
        r = self.sp[code]
        hit = self.ioc_by_sci.get(r["sci"])
        if hit and hit.get("zh", "").strip():
            return hit["zh"].strip(), "IOC/学名"
        sci2 = self.ioc_by_en.get(norm(r["en"]))
        if sci2 and self.ioc_by_sci[sci2].get("zh", "").strip():
            return self.ioc_by_sci[sci2]["zh"].strip(), "IOC/英文名"
        if r.get("zh_ebird"):
            return r["zh_ebird"], "eBird/zh_SIM"
        return "", ""

    def zh(self, code):
        """中文名；查不到返回 `""`（调用方只写英文名，**不要编**）。"""
        return self._zh.get(code, "")

    def zh_source(self, code):
        """这个中文名是哪条链给的。用于缺失报告与可追溯性。"""
        return self._zh_via.get(code, "")

    # ---------- 英文名 ----------
    #
    # 口径（用户 2026-10-19）：**用老牌图鉴常用名（= IOC 口径），
    # 只要还能对应到 eBird 数据即可。**
    #
    # 为什么这不违反「以 eBird 为准」：英文名和中文名一样是**显示标签**。
    # 数据的键始终是 eBird `speciesCode`，分布/频次/名录一个字节都没动。
    #
    # 实测差异（35 种特有种中 10 种不同，全部 257 种中 50 种不同）：
    #   - 7 种只是 eBird 的连字符习惯：`Blue-Magpie` vs `Blue Magpie`
    #   - 1 种是美式拼写：`Gray Hornbill` vs `Grey Hornbill`
    #   - **只有 2 种是真的不同名**，且这 2 种 IOC 与用户给的叫法完全一致：
    #       Sri Lanka Myna              -> Sri Lanka Hill Myna
    #       White-throated Flowerpecker -> Legge's Flowerpecker
    #
    # 两个名字**都进反向索引**，所以鸟导不论用哪一种叫法都能解析到同一个 code。

    def en(self, code):
        """显示用英文名：**优先 IOC（老牌图鉴常用名）**，没有才退回 eBird。"""
        if code not in self.sp:
            return ""
        return self._en_ioc.get(code) or self.sp[code]["en"]

    def en_ebird(self, code):
        """eBird 原文英文名。用于与 eBird 接口对照、以及分歧报告。"""
        return self.sp[code]["en"] if code in self.sp else ""

    def en_differs(self, code):
        """IOC 与 eBird 的英文名是否实质不同（忽略连字符/大小写/撇号差异）。

        只报**实质**差异：`Blue-Magpie` vs `Blue Magpie` 不算，
        `Sri Lanka Myna` vs `Sri Lanka Hill Myna` 才算。
        连字符那类差异有 48 条，混在报告里会把真正要看的 2 条淹掉。
        """
        a, b = self.en(code), self.en_ebird(code)
        return bool(a) and bool(b) and norm(a) != norm(b)

    def sci(self, code):
        return self.sp[code]["sci"] if code in self.sp else ""

    def family(self, code):
        return self.sp[code]["family"] if code in self.sp else ""

    def order(self, code):
        return self.sp[code]["order"] if code in self.sp else ""

    def taxon_order(self, code):
        """eBird 分类序号。**排序一律用它**，不要用名字排——
        名字排序会让中英文混排的清单在两次构建间漂移。"""
        return self.sp[code]["order_num"] if code in self.sp else 0

    def label(self, code, style="zh_en"):
        """给文档用的显示名。

        `zh_en`（默认）: `中文名（English Name）`；无中文名时只写英文名。
        `zh`:  中文名，没有则英文名。
        `en`:  英文名（**要报给鸟导的那个**，永远是 eBird 原文）。
        """
        if code not in self.sp:
            return f"⟨未知 code: {code}⟩"
        z, e = self.zh(code), self.en(code)
        if style == "en":
            return e
        if style == "zh":
            return z or e
        return f"{z}（{e}）" if z else e

    # ---------- 解析 ----------

    def resolve(self, name):
        """把任意写法的名字变成 `speciesCode`。

        返回 `(code, 原因)`。失败时 `code is None`，`原因` 说明为什么——
        这条原因会直接进 `unresolved` 报告给人看，所以要具体。

        **不做模糊匹配**：对不上就是对不上，由人加别名，不由脚本猜。
        """
        n = norm(name)
        if not n:
            return None, "空名字"
        if n in self.aliases:
            c = self.aliases[n]
            if c not in self.sp:
                return None, f"别名表指向的 code 不存在: {c}"
            return c, "别名表"
        hits = self.index.get(n)
        if not hits:
            return None, "eBird 分类中查无此名（code/学名/英文名/中文名均未命中）"
        if len(hits) > 1:
            return None, ("名字有歧义，对应多个物种: "
                          + ", ".join(f"{c}={self.en(c)}" for c in sorted(hits))
                          + "；请在行程的别名表里显式指定")
        return next(iter(hits)), "直接命中"

    def resolve_many(self, names):
        """批量解析。返回 `(ok, unresolved)`：
        `ok` 是 `[(原文, code)]` 保持输入顺序；`unresolved` 是 `[(原文, 原因)]`。"""
        ok, bad = [], []
        for nm in names:
            c, why = self.resolve(nm)
            (ok.append((nm, c)) if c else bad.append((nm, why)))
        return ok, bad

    # ---------- 占位符 ----------

    PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9]+)(!?)\}\}")

    def expand(self, text, strict=True):
        """展开判断文本里的 `{{code}}` / `{{code!}}` 占位。

        `{{code}}`  -> 中文名（无则英文名）
        `{{code!}}` -> `中文名（English Name）`，要报给鸟导时用

        `strict=True` 时，占位指向不存在的 code 直接报错——
        **这是防编造的最后一道闸**：判断文本里写错 code 不能被静默渲染成正常文字。
        """
        bad = []

        def sub(m):
            code, bang = m.group(1), m.group(2)
            if code not in self.sp:
                bad.append(code)
                return f"⟨未知 code: {code}⟩"
            return self.label(code, "zh_en" if bang else "zh")

        out = self.PLACEHOLDER.sub(sub, text)
        if bad and strict:
            raise ValueError(
                f"判断文本里的占位符指向不存在的 eBird code: {sorted(set(bad))}\n"
                f"  code 以 engine/refdata/ebird_taxonomy.json 为准。")
        return out

    def placeholders(self, text):
        """列出文本里用到的所有 code（供 verify 反查）。"""
        return [m.group(1) for m in self.PLACEHOLDER.finditer(text)]

    # ---------- 报告 ----------

    def zh_coverage(self, codes):
        """给定一批 code，返回中文名覆盖统计与缺失清单。

        缺失不是错误，是**事实**：有的种确实没有通行中文名。
        报告出来，让人决定要不要在别名表里手工补——而不是让脚本编一个。
        """
        by_via, missing = {}, []
        for c in codes:
            if self.zh(c):
                by_via[self.zh_source(c)] = by_via.get(self.zh_source(c), 0) + 1
            else:
                missing.append(c)
        return {"total": len(codes), "by_source": by_via,
                "missing": sorted(missing, key=self.taxon_order)}


_cached = None


def load(aliases=None):
    """进程内单例。别名不同则重建（行程切换时会发生）。"""
    global _cached
    if _cached is None or _cached[0] != (tuple(sorted((aliases or {}).items()))):
        _cached = (tuple(sorted((aliases or {}).items())), Taxonomy(aliases))
    return _cached[1]


if __name__ == "__main__":
    import sys
    t = load()
    print(f"eBird 分类 {len(t.sp)} 种 | IOC 字典 {t.ioc_version} "
          f"{len(t.ioc_by_sci)} 种")
    cov = t.zh_coverage(list(t.sp))
    print(f"全球中文名覆盖: {cov['total'] - len(cov['missing'])}/{cov['total']}"
          f" = {100 * (cov['total'] - len(cov['missing'])) / cov['total']:.1f}%")
    for k, v in sorted(cov["by_source"].items(), key=lambda x: -x[1]):
        print(f"   {k:14s} {v}")
    for name in sys.argv[1:]:
        c, why = t.resolve(name)
        print(f"\n{name!r} -> {c or '未解析'}  ({why})")
        if c:
            print(f"   {t.label(c, 'zh_en')} | {t.sci(c)} | {t.family(c)}"
                  f" | 中文名来源 {t.zh_source(c) or '—'}")
