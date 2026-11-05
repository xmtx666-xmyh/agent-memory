"""首次安装 / 换机初始化：生成实体表与注入目标，并打印本机实体列表。

    python cli.py init            # 缺 entities.json 就生成；缺 targets.json 就生成候选
    python cli.py init --force    # 覆盖重建（会丢手工加的别名，慎用）

## 为什么需要它

实体同义词表和注入目标都是**每台机器自己的数据**，不能写死在代码里。
换台电脑（没有 demo-base / 示例街道A…）时，先跑 init 建立本机的实体表与目标。

## 实体表怎么来（不猜项目名）

从 `session_paths`（工具调用碰过的目录）里数"有多少会话碰过该目录"，
取**现存目录**，每个目录名自成一个实体；同义（历代改名）靠人工补，脚本不猜——
实测用共现率自动判同义并不可靠（demo-wiki 与 demo-next 曾并行存在）。
"""
from __future__ import annotations

import collections
import json
import os

from paths import DATA, ENTITIES_FILE, TARGETS_FILE, ensure_data_dir

#: 容器/公共目录，不是项目。**从 topics 导入**，不手工拷贝 ——
#: 实测手工拷一份会与 topics._PATH_DIR_NOISE 漂移（一边加、另一边把它当实体）。
from topics import _PATH_DIR_NOISE as _NOISE   # noqa: E402


def candidate_projects(store, limit: int = 30) -> list[tuple[str, int, str]]:
    """候选项目：[(目录, 会话数, 目录名)]，按会话数降序；只留**当前存在**的目录。"""
    rows = list(store.con.execute("""
        SELECT p.dir AS dir, COUNT(DISTINCT p.session_key) AS n
        FROM session_paths p
        GROUP BY p.dir ORDER BY n DESC"""))
    out = []
    for r in rows:
        d = r["dir"] or ""
        if not d or not os.path.isdir(d):
            continue
        name = d.replace("/", "\\").rstrip("\\").rsplit("\\", 1)[-1].lower()
        if name in _NOISE:
            continue
        if d.lower().startswith("c:\\users\\") and d.count("\\") == 2:
            continue
        out.append((d, r["n"], name))
        if len(out) >= limit:
            break
    return out


def init(store, force: bool = False, targets: bool = True) -> dict:
    ensure_data_dir()
    result = {"entities_created": False, "entities": 0, "targets_created": False,
              "candidates": []}

    if force or not os.path.exists(ENTITIES_FILE):
        cands = candidate_projects(store)
        doc = {"_comment": "本机实体同义词表（数据）。canonical -> 别名列表（小写匹配）。"
                           "历代改名的别名请手工加，脚本不猜。",
               "entities": {name: [name] for _d, _n, name in cands}}
        with open(ENTITIES_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        result["entities_created"] = True
        result["entities"] = len(doc["entities"])

    if targets and (force or not os.path.exists(TARGETS_FILE)):
        cands = candidate_projects(store, limit=8)
        # ⚠️ 不猜"注入块该写给哪个项目"。实测按会话数排序会挑到错误的项目
        # （本机挑到了 f:\示例工具库，而真正想要的是 f:\demo-base）。
        # 这里只写空表 + 填法说明，由人决定。
        doc = {"_howto": "把要生成注入块的项目填进 targets：entity 用 cli.py topics 里的实体名，"
                         "out 指向该项目的 .agent-memory/context.md",
               "targets": []}
        with open(TARGETS_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        result["targets_created"] = True
        result["candidates"] = [(d, n) for d, n, _name in cands]

    return result
