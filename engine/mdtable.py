#!/usr/bin/env python3
"""Markdown 配置解析：把 `.md` 里的**表格**与**键值块**读成 Python 结构。

为什么配置用 Markdown 而不是 YAML/JSON
--------------------------------------
本机 Python 3.9 **只有标准库**（无 PyYAML、无 tomllib）。
与其自写一个有隐微 bug 风险的 YAML 子集解析器，不如用 Markdown 表格：
解析规则短到可以一眼看完，而且**配置文件本身就是给人读的文档**——
点位表、行程表、判断表，本来就该长成表格的样子。

两种读法
--------
1. **表格** `table(path, 标题)` —— 取指定小节下的第一张表，返回 `list[dict]`，
   键是表头原文。空单元格返回 `""`，不返回 None（调用方少写一半判空）。
2. **键值块** `kv(path)` —— 取形如 `- key: value` 的行，返回 `dict`。

两种读法都**忽略普通正文**，所以配置文件里可以写满解释、理由、踩坑记录——
这正是本项目一贯的做法（判断必须写明理由）。

数据与判断
----------
本模块**只做解析，不做任何解释**：不转类型、不填默认值、不校验。
`"6.42"` 读出来就是字符串 `"6.42"`，由调用方决定怎么用。
理由：一旦解析器开始猜类型，`locId` 这种必须逐字符保真的值就会被毁掉
（如 `L6251335` 若被当成数字处理，前导字母与精度都可能走样）。
"""
import re
from pathlib import Path

# 表格分隔行：`|---|:--:|---|` 这种。
# **破折号允许只有一个**——`|:-:|` 是合法的居中写法，而且很常用。
# 这里曾经写成 `-{2,}`，结果所有用 `:-:` 居中的表格都读不出来（整表静默变空）。
_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
# 键值行：- key: value   （允许行尾 # 注释）
_KV = re.compile(r"^\s*-\s+([A-Za-z_][\w.]*)\s*:\s*(.*?)\s*$")


def _cells(line):
    """切一行表格。去掉首尾的 `|`，再按未转义的 `|` 切。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    # 支持单元格内用 \| 写竖线
    parts = re.split(r"(?<!\\)\|", s)
    return [p.strip().replace(r"\|", "|") for p in parts]


def _strip_comment(v):
    """去掉键值行尾部的 ` # 注释`。单元格内不做这件事——
    表格里的 `#` 常常是内容的一部分（如 `#1 优先`）。"""
    m = re.search(r"\s+#\s", v)
    return v[: m.start()].strip() if m else v


def tables(path):
    """读出文件里**所有**表格，按出现顺序返回 `[(上方最近的标题, rows), ...]`。

    `rows` 是 `list[dict]`，键为表头原文。
    列数与表头不一致的行**原样保留**（多的丢弃、少的补 `""`），
    不抛异常——配置写错时应该由 verify 报告，而不是让解析器崩在这里。
    """
    text = Path(path).read_text(encoding="utf-8")
    out, heading = [], ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("#"):
            heading = ln.lstrip("#").strip()
            i += 1
            continue
        # 表格 = 一行表头 + 一行分隔 + N 行数据
        if "|" in ln and i + 1 < len(lines) and _SEP.match(lines[i + 1]):
            hdr = _cells(ln)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                c = _cells(lines[i])
                rows.append({h: (c[j] if j < len(c) else "")
                             for j, h in enumerate(hdr)})
                i += 1
            out.append((heading, rows))
            continue
        i += 1
    return out


def table(path, heading=None, index=0):
    """取一张表。

    `heading` 给定时在标题里找：**优先精确匹配，没有才退回子串匹配**。

    为什么要优先精确：子串匹配会踩到包含关系。实测过一次——
    文件里既有大标题「本行程断言」又有小节「断言」，
    查 `"断言"` 时**先命中了大标题下的另一张表**，
    于是断言表被静默换成了变量说明表，五条断言全部报「表达式为空」。

    找不到返回 `[]`——调用方若要求必须存在，自己判空并报错，
    这样错误信息能说清「哪个行程的哪张表缺了」，比解析器抛通用异常有用。
    """
    ts = tables(path)
    if heading is not None:
        exact = [t for t in ts if t[0].strip() == heading]
        ts = exact if exact else [t for t in ts if heading in t[0]]
    return ts[index][1] if len(ts) > index else []


def kv(path):
    """读 `- key: value` 形式的键值块。重复 key 以**最后一次**为准。"""
    out = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        m = _KV.match(ln)
        if m:
            out[m.group(1)] = _strip_comment(m.group(2))
    return out


def split_list(v, sep=","):
    """把 `a, b, c` 切成 `["a","b","c"]`。空串返回 `[]`，不返回 `[""]`。"""
    return [x.strip() for x in v.split(sep) if x.strip()]


def split_ws(v):
    """按空白切。用于一个单元格里放多个 locId 的情形。"""
    return v.split()


def parse_pairs(v):
    """把 `a=1, b=2` 读成 `{"a":"1","b":"2"}`。值保持字符串，不转类型。"""
    out = {}
    for item in split_list(v):
        if "=" in item:
            k, _, val = item.partition("=")
            out[k.strip()] = val.strip()
    return out
