#!/usr/bin/env python3
"""物料登记：把外部材料（网页/PDF/文字）收进行程，并留下可追溯的出处。

用法:
    python3 -I engine/materials.py --trip trips/<id> --add <url|路径>
    python3 -I engine/materials.py --trip trips/<id> --add-text "一段话" --label "酒店改到 Deniyaya 南侧"
    python3 -I engine/materials.py --trip trips/<id> --list
    python3 -I engine/materials.py --trip trips/<id> --resolve "Sri Lanka Blue-Magpie" "红脸地鹃"

为什么物料要登记而不是直接改配置
--------------------------------
这套工具的判断文本大量来自外部材料——别人的行程报告、鸟导的邮件、
酒店的确认信、一段随口说的变更。如果看完就直接改配置，
三个月后没人说得清「这条判断是哪来的、可不可信」。

所以每份材料都落盘、算 sha256、登记进 `materials/index.json`，
抽取结果写成 `extract.md`，配置里引用它的 `id`。
**材料本身永不被改写**——它是证据。

与名字闸门的关系
----------------
`--resolve` 是给 agent 用的：**从材料里读出来的每一个鸟名，
必须先过这里解析成 eBird `speciesCode` 才允许写进配置**。
解析不出的进 `unresolved`，由人裁决，**脚本不猜**。
这是防止「从别人的文案里抄来一个不存在的鸟名」的唯一闸门。

下载物是不可信数据
------------------
每份材料放进自己的目录 `materials/<id>/`，与脚本分开，
解析一律以路径为参数传入，不在材料目录里执行任何解释器。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import taxonomy as T                                     # noqa: E402

INDEX = "index.json"


def slugify(s, maxlen=40):
    s = re.sub(r"[^\w一-鿿-]+", "-", (s or "").strip())
    return s.strip("-")[:maxlen].lower() or "material"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


class Materials:
    def __init__(self, trip_dir):
        self.dir = Path(trip_dir) / "materials"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / INDEX
        self.index = (json.loads(self.index_path.read_text(encoding="utf-8"))
                      if self.index_path.exists() else {"materials": []})

    def save(self):
        self.index_path.write_text(
            json.dumps(self.index, ensure_ascii=False, indent=1),
            encoding="utf-8")

    def _new_id(self, label):
        base = f"{time.strftime('%Y%m%d')}-{slugify(label)}"
        existing = {m["id"] for m in self.index["materials"]}
        if base not in existing:
            return base
        i = 2
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    def add_bytes(self, data, filename, label, source):
        """收一份材料。返回它的登记记录。

        同样内容（sha256 相同）已经收过就**不重复收**，直接返回旧记录——
        同一份材料被投两次是常事，不该产生两份证据。
        """
        h = sha256(data)
        for m in self.index["materials"]:
            if m["sha256"] == h:
                return m, False
        mid = self._new_id(label)
        d = self.dir / mid
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_bytes(data)
        rec = {"id": mid, "label": label, "source": source,
               "file": filename, "sha256": h, "bytes": len(data),
               "added": time.strftime("%Y-%m-%d %H:%M"),
               "extracted": False}
        (d / "meta.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        self.index["materials"].append(rec)
        self.save()
        return rec, True

    def add_url(self, url, label=None):
        label = label or url.split("/")[-1] or url
        r = subprocess.run(["curl", "-sSL", "--max-time", "120", url],
                           capture_output=True)
        if r.returncode != 0 or not r.stdout:
            sys.exit(f"下载失败 rc={r.returncode}: "
                     f"{r.stderr.decode('utf-8', 'replace')[:200]}")
        name = url.split("/")[-1].split("?")[0] or "page.html"
        if "." not in name:
            name += ".html"
        return self.add_bytes(r.stdout, name, label, url)

    def add_path(self, path, label=None):
        p = Path(path)
        if not p.exists():
            sys.exit(f"文件不存在: {p}")
        return self.add_bytes(p.read_bytes(), p.name,
                              label or p.name, f"file://{p.resolve()}")

    def add_text(self, text, label):
        return self.add_bytes(text.encode("utf-8"), "input.md",
                              label, "用户直接输入")

    def path_of(self, mid):
        return self.dir / mid


def trip_aliases(trip_dir):
    """读行程的别名表。没有 `--trip` 时返回 None（只用全局分类）。"""
    if not trip_dir:
        return None
    f = Path(trip_dir) / "targets.md"
    if not f.exists():
        return None
    sys.path.insert(0, str(ENGINE))
    import mdtable as M
    return {r["别名"]: r["code"] for r in M.table(f, "别名表")}


def cmd_resolve(names, trip_dir=None):
    """把一批名字解析成 eBird code。给 agent 用的闸门。

    输出设计成**人也能读、机器也能解析**：
    每行 `名字 -> code | 显示名 | 原因`，解析不出的前缀是 `UNRESOLVED`。

    **必须带 `--trip`**，否则读不到该行程的别名表——
    像 `Pompadour Green Pigeon` 这种老图鉴叫法只在行程别名里有定义，
    不加载就会被误判成「查无此名」。
    """
    t = T.load(trip_aliases(trip_dir))
    ok, bad = t.resolve_many(names)
    for nm, c in ok:
        print(f"OK\t{nm}\t{c}\t{t.label(c, 'zh_en')}\t{t.sci(c)}")
    for nm, why in bad:
        print(f"UNRESOLVED\t{nm}\t\t\t{why}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip")
    ap.add_argument("--add", help="url 或本地文件路径")
    ap.add_argument("--add-text", help="直接收一段文字")
    ap.add_argument("--label", help="这份材料是什么")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--resolve", nargs="+",
                    help="把名字解析成 eBird code（写进配置前必须过这一关）")
    a = ap.parse_args()

    if a.resolve:
        sys.exit(cmd_resolve(a.resolve, a.trip))

    if not a.trip:
        sys.exit("需要 --trip")
    m = Materials(a.trip)

    if a.list:
        ms = m.index["materials"]
        print(f"{len(ms)} 份材料：")
        for r in ms:
            flag = "已抽取" if r.get("extracted") else "**未抽取**"
            print(f"  {r['id']}\t{r['bytes']:>8}B\t{flag}\t{r['label']}")
            print(f"      来源 {r['source']}")
        return

    if a.add:
        if a.add.startswith(("http://", "https://")):
            rec, new = m.add_url(a.add, a.label)
        else:
            rec, new = m.add_path(a.add, a.label)
    elif a.add_text:
        if not a.label:
            sys.exit("--add-text 需要配 --label 说明这是什么")
        rec, new = m.add_text(a.add_text, a.label)
    else:
        sys.exit("需要 --add / --add-text / --list / --resolve 之一")

    print(("收入" if new else "已存在（sha256 相同，不重复收）")
          + f" {rec['id']}")
    print(f"  路径   {m.path_of(rec['id'])}/{rec['file']}")
    print(f"  sha256 {rec['sha256'][:16]}…")
    print(f"  来源   {rec['source']}")
    if new:
        print(f"\n下一步：读这份材料，把抽取结果写进 "
              f"{m.path_of(rec['id'])}/extract.md，"
              f"并把其中的鸟名用 --resolve 过一遍闸门。")


if __name__ == "__main__":
    main()
