"""前提校验（P0）：结论里引用的路径，现在是「活的 / 迁移了 / 真死了」。

## 为什么不是简单的 os.path.exists

GLM-5.3 评审（docs/staleness-design.md §二 E1）指出我原来的错：
把「路径不存在」直接当「结论失效」。但实测 58 条幽灵路径里**大部分是项目迁移**
（`F:\\demo-wiki` → `F:\\demo-base`）——迁移意味着前提**换了名字活着**，结论在新位置**可能仍成立**。
标「勿照做」会把仍有效的经验错误劝阻，与本项目目标相反。

## 三路判定（判据是"这个项目还有活着的目录吗"，不是"这条路径存在吗"）

| 判定 | 条件 | 处置 |
|---|---|---|
| `alive` | 路径存在 | 前提通过 |
| `dead_with_successor` | 路径不存在，但**其所属实体仍有存活目录** | 🟡 带注「项目已迁移至 X」，**不标勿照做** |
| `dead_no_successor` | 路径不存在，且**该实体已无任何存活目录** | 🔴 真失效 |

端口**不进失效判定**：GLM 评审指出「端口无监听」测的是**存活**不是**存在**（服务没启动是常态），
瞬时探测会大面积误标。这里只标 `unverified` 并把端口号原样带回，交人工。

模型名同样不进失效判定（历史实测记录为真于当时，且模型没了就无人能照做，危险度最低）。

## 时间性（评审 W7）

每条判定都带 `check_at`：存在性判断是**检验时刻**的函数（路径可能删了又建、服务后来启动）。
注入时应**懒检验**（注入前复核），而不是永久缓存一次结果。
"""
from __future__ import annotations

import collections
import os
import re
import sqlite3
import time

#: 路径字符集：**故意包含 `*?`**，这样通配符路径能整段匹配到、再被下面过滤掉。
#: 若把 `*?` 排除在字符集外，`F:\demo-main\work\waves\int-0*.json` 会被截成 `int-0` 当真实路径。
PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'`<>|\n，。；）、]{3,200}")
PORT_RE = re.compile(r"(?:端口|port)[^\d]{0,6}(\d{2,5})")

#: 判定结果常量（下游按这个名字分组，不要改字面量）
ALIVE = "alive"
DEAD_WITH_SUCCESSOR = "dead_with_successor"
DEAD_NO_SUCCESSOR = "dead_no_successor"
UNVERIFIED = "unverified"

#: 路径里"项目名"所在段之后的噪声尾（`F:\x\a.py#L29` 这类）
_TAIL_NOISE = ";,.):]}'\"#"


#: 中文标点/括号：路径常写在中文句子里或被 markdown 链接包裹
_CJK_CUT_RE = re.compile(r"[，。；：、「」【】《》（）]")


def extract_paths(text: str) -> list[str]:
    """从结论句里抽绝对路径。

    实测踩过的抽取假阳性（都会把无关路径判成"结论失效"）：
      · markdown 链接 `[x.md](F:\\demo-main\\docs\\x.md)（含 15 行）` → 抽出带 `)（含` 的脏路径
      · 通配符 `F:\\demo-main\\work\\waves\\int-0*.json` → 不是实体路径
      · GBK 乱码 `F:\\閿欒鎺掓煡\\work` → 文本在讨论编码问题时出现的伪路径
    """
    out: list[str] = []
    for raw in PATH_RE.findall(text or ""):
        p = raw
        # markdown 链接：只留链接目标部分
        if "](" in p:
            p = p.split("](", 1)[1]
        # 在中英文括号/中文标点处截断（`（含 15 行）` / `)：版本升第七轮`）
        p = _CJK_CUT_RE.split(p, 1)[0]
        p = p.split(")", 1)[0]
        p = p.rstrip(_TAIL_NOISE)
        p = re.sub(r"[#:]L?\d+(-L?\d+)?$", "", p).rstrip(_TAIL_NOISE)
        if len(p) < 4 or "*" in p or "?" in p:      # 通配符不是实体路径
            continue
        if p not in out:
            out.append(p)
    return out


def extract_ports(text: str) -> list[str]:
    return PORT_RE.findall(text or "")


def project_dir_of(path: str) -> str:
    """`F:\\demo-wiki\\server\\x.py` → `f:\\demo-wiki`（只要前两段）。"""
    parts = [p for p in path.replace("/", "\\").split("\\") if p]
    if len(parts) < 2 or len(parts[0]) != 2:
        return ""
    return (parts[0] + "\\" + parts[1]).lower()


def live_dirs_by_entity(db_path: str) -> dict[str, list[str]]:
    """从库里的 session_paths × session_topics 反推：每个实体现在还**活着**的目录。

    这是"项目是否还有活着的资产"的事实来源 —— 比写死别名表可靠：
    别名表只说明"谁改名叫谁"，而这里说明"它现在到底在哪、还存不存在"。

    ⚠️ 必须用 `dir_entity_map` 过滤：一个会话被标成「demo-kb」，不代表它顺手碰过的
    `f:\\agent-memory` 也算demo-kb的目录。实测不过滤时，demo-kb名下会混进
    agent-memory / demo-shield / 示例工具库 / 用户主目录 —— 那样"迁移判定"就永远为真了。
    """
    d2e = dir_entity_map(db_path)
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    # 按「最后被工具调用碰到的时间」倒序 —— 后继目录的正确排序是**最近还在用的**，
    # 不是字母序。实测踩过：demo-kb的活目录是 demo-next / demo-wiki2 / demo-base，
    # 按字母取前 2 会显示 "已迁移至 f:\demo-next, f:\demo-wiki2"，而正确答案是 f:\demo-base。
    rows = list(con.execute("""
        SELECT dir, MAX(s.started_at) AS last_at
        FROM session_paths p JOIN sessions s ON s.session_key=p.session_key
        GROUP BY dir"""))
    con.close()
    last_used = {d.lower(): (t or "") for d, t in rows}
    out: dict[str, list[str]] = collections.defaultdict(list)
    for d in last_used:
        if not d or not os.path.isdir(d):
            continue
        ent = d2e.get(d)
        if ent:
            out[ent].append(d)
    for k in out:
        out[k] = sorted(set(out[k]), key=lambda d: last_used.get(d, ""), reverse=True)
    return dict(out)


#: 不是"项目资产"的路径：系统目录 / 临时目录 —— 出现在结论里通常是示例、攻击载荷或一次性脚本。
#: 实测误判：`C:\\Windows\\evil.txt` 是路径穿越测试的载荷（本来就不该存在），
#: `AppData\\Local\\Temp\\probe_*.py` 是临时脚本。把它们判成"结论失效"是错的。
_NON_ASSET_RE = re.compile(
    r"^(?:[a-z]:\\windows|[a-z]:\\program|%temp%|[a-z]:\\users\\[^\\]+\\appdata\\(?:local\\)?temp"
    r"|/tmp)", re.IGNORECASE)


def is_project_asset(path: str) -> bool:
    """这条路径是否值得做前提校验（系统/临时目录里的不算项目资产）。"""
    return not _NON_ASSET_RE.match(path.replace("/", "\\").lower())


def judge_path(path: str, live_dirs: dict[str, list[str]],
               dir_to_entity: dict[str, str],
               check_at: str = "") -> tuple[str, str]:
    """三路判定一条路径。返回 (verdict, note)。

    `dir_to_entity`：目录 → 实体（同一项目在库里的归属）。
    目录不在表里时（例如只在正文被提到、没有工具真的碰过），**回退到别名表**判断归属 ——
    实测 `F:\\demo-system` 就是这种情况：别名里有它，但它没进 session_paths，
    不回退就会把"迁移"误判成"彻底消失"。
    """
    if not is_project_asset(path):
        return UNVERIFIED, "非项目资产（系统/临时目录）"
    if os.path.exists(path):
        return ALIVE, ""
    pdir = project_dir_of(path)
    entity = dir_to_entity.get(pdir, "")
    if not entity:
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from topics import entities_from_paths
            ents = entities_from_paths([(pdir, 1)])
            entity = ents[0][0] if ents else ""
        except Exception:                                  # noqa: BLE001
            entity = ""
    alive = live_dirs.get(entity) if entity else None
    if alive:
        return DEAD_WITH_SUCCESSOR, "项目已迁移至 %s" % ", ".join(alive[:2])
    # 项目目录含非 ASCII 且找不到任何存活目录：实测多为 GBK 乱码伪路径
    # （`F:\閿欒鎺掓煡\work`，那个会话本身就在讨论编码问题）。
    # 注意：`entities_from_paths` 会把乱码目录名当成"新项目"返回非空 entity，
    # 所以这里必须按 **pdir 是否 ASCII** 判，不能只按 entity 是否为空判。
    if not pdir.isascii():
        return UNVERIFIED, "疑似编码乱码/未知项目，不判失效"
    return DEAD_NO_SUCCESSOR, ""


def dir_entity_map(db_path: str) -> dict[str, str]:
    """目录 → 实体（用与打标一致的规则：entities_from_paths 的别名映射）。"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from topics import entities_from_paths
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    rows = con.execute("SELECT DISTINCT dir FROM session_paths").fetchall()
    con.close()
    out: dict[str, str] = {}
    for (d,) in rows:
        ents = entities_from_paths([(d, 1)])
        if ents:
            out[d.lower()] = ents[0][0]
    return out


def check_conclusions(db_path: str, entity: str, limit: int = 0) -> dict:
    """对某实体下所有结论做前提校验，返回统计与🔴清单。"""
    from timeline import extract_conclusions   # 延迟导入，避免循环

    live = live_dirs_by_entity(db_path)
    d2e = dir_entity_map(db_path)
    check_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    rows = list(con.execute("""
    SELECT s.session_key, s.started_at, s.agent, s.title
    FROM sessions s
    JOIN session_topics t ON t.session_key=s.session_key AND t.kind='entity' AND t.label=?
    ORDER BY s.started_at LIMIT ?""", (entity, limit or -1)))

    stats = collections.Counter()
    items = []
    for r in rows:
        msgs = [(x["role"], x["ts"], x["text"]) for x in con.execute(
            "SELECT role, ts, text FROM messages WHERE session_key=? ORDER BY seq",
            (r["session_key"],))]
        for c in extract_conclusions(msgs):
            text = c["text"]
            paths = extract_paths(text)
            ports = extract_ports(text)
            stats["结论总数"] += 1
            if not paths and not ports:
                stats[UNVERIFIED] += 1
                continue
            if ports and not paths:
                stats[UNVERIFIED] += 1          # 端口不进失效判定（评审 E1）
                continue
            verdicts = [judge_path(p, live, d2e, check_at) for p in paths]
            vset = {v for v, _n in verdicts}
            if DEAD_NO_SUCCESSOR in vset:
                main = DEAD_NO_SUCCESSOR
            elif DEAD_WITH_SUCCESSOR in vset:
                main = DEAD_WITH_SUCCESSOR
            else:
                main = ALIVE
            stats[main] += 1
            if main != ALIVE and len(items) < 60:
                items.append({"verdict": main, "text": text[:150],
                              "paths": paths[:3], "note": verdicts[0][1],
                              "when": (r["started_at"] or "")[:10],
                              "agent": r["agent"], "title": (r["title"] or "")[:40],
                              "check_at": check_at})
    con.close()
    return {"entity": entity, "sessions": len(rows), "stats": dict(stats),
            "items": items, "check_at": check_at,
            "live_dirs": {k: v[:3] for k, v in live.items()}}
