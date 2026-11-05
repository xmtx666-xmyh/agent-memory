"""会话索引：SQLite + FTS5（含 trigram 索引给中文用）。

设计借鉴（实测 Hermes `session_search` 后确认有效的部分）：
  · **索引用 0 次 LLM**：纯 FTS5 MATCH，毫秒级；
  · **中文用 trigram 索引**：两个索引分工是**实测**出来的（2026-11-04 内存 FTS5 验证）——
    `unicode61` **不切分 CJK**：一段连续中文是**一个 token**，所以任何中文子串都查不到
    （`招标`/`保证金` 全部 0 命中，连 3 字词也不中）；`trigram` 按 3 字滑窗建索引，
    3 字及以上的中文短语能命中，但 **1~2 字的中文词（`质保`/`预算`）在 trigram 上也查不到**——
    这条由 `search()` 的 LIKE 回退兜底（`last_search_via == "like"`，调用方要报给用户）；
  · **内容有界**：单条正文入库前已截断 20000 字符（见 collectors/base.clean_text）。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from typing import Iterable

from collectors.base import CollectResult, Record, SessionMeta

#: 数据 schema 版本（存在 SQLite 的 `PRAGMA user_version`）。
#: 为什么要它（借鉴 Helm 的 version vs appVersion 分离）：包版本（SKILL.md 的 version）
#: 与**数据**版本是两件事 —— 升级包不等于数据已迁移，反过来也一样。doctor 会把两者
#: 都报出来；未来的迁移按这个号做阶梯（0 = 2026-11-04 之前的库，结构已由 _migrate 补齐）。
SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_key   TEXT PRIMARY KEY,
    agent         TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    title         TEXT,
    cwd           TEXT,
    started_at    TEXT,
    ended_at      TEXT,
    model         TEXT,
    provider      TEXT,
    parent_session TEXT,
    origin        TEXT,
    source_path   TEXT,
    peer          TEXT,                 -- 工作区身份：由 cwd 的 git origin 派生（见 peers.py）
    message_count INTEGER,
    tool_call_count INTEGER,
    indexed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    agent       TEXT NOT NULL,
    role        TEXT NOT NULL,
    ts          TEXT,
    seq         INTEGER,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id', tokenize='unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_trgm USING fts5(
    text, content='messages', content_rowid='id', tokenize='trigram'
);

-- 话题归并结果（第二阶段 A）：一个会话可有多个实体与意图
CREATE TABLE IF NOT EXISTS session_topics (
    session_key TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- 'entity' | 'intent'
    label       TEXT NOT NULL,
    hits        INTEGER DEFAULT 0,      -- 命中次数，用于排序/权重
    PRIMARY KEY (session_key, kind, label)
);
CREATE INDEX IF NOT EXISTS idx_topics_label ON session_topics(kind, label);

-- 工具调用碰过的项目目录（第二阶段 A 的归属信号；只存目录名与次数，不存工具输出）
CREATE TABLE IF NOT EXISTS session_paths (
    session_key TEXT NOT NULL,
    dir         TEXT NOT NULL,
    hits        INTEGER DEFAULT 0,
    PRIMARY KEY (session_key, dir)
);
CREATE INDEX IF NOT EXISTS idx_paths_dir ON session_paths(dir);
"""


class QueryError(ValueError):
    """查询本身有问题（FTS5 语法错误），**必须**与"没命中"区分开。

    2026-11-04 glm-5.3 复核指出：原来 `except sqlite3.OperationalError: return []` 把
    `C++`、未闭合引号这类语法错误静默变成"零命中"，用户会以为"历史上没聊过"。
    """

    def __init__(self, query: str, detail: str):
        self.query = query
        self.detail = detail
        super().__init__(
            "查询语法错误（不是没有结果）：%r ｜ 原始错误：%s ｜ 提示：FTS5 里 "
            "`+ - * ^ : \" ( )` 是语法字符，搜它们请加引号或换词" % (query, detail))


#: 是否含中日韩字符（决定要不要走 LIKE 回退）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

#: 这些字符出现在查询里通常是"我想搜这个词"，不是语法意图（`agent-memory`、`user:query`）
_RELAXABLE_CHARS = re.compile(r"[-:.]")
#: 这些是真·语法字符：出现就不做宽松重试，直接报错（`C++`、`(a OR b)`、`"未闭合`）
_HARD_SYNTAX = re.compile(r'[+\*^()"]')


#: 瞬时故障（不是查询写错）：这些 OperationalError **不允许**被"宽松重试"掩盖
_TRANSIENT_ERR = ("locked", "disk i/o", "unable to open database", "out of memory")


def _relax_query(query: str) -> str | None:
    """把含 `- : .` 的普通词包成 FTS5 短语，避免被当成语法运算符。

    实测（2026-11-04）：`search "agent-memory"` 会报 `no such column: reminder` ——
    因为 `-` 在 FTS5 里是运算符。这类词在本机语料里极常见（`demo-base`、`qwen3.5:9b`），
    必须能搜。返回 None = 不做宽松重试（含真·语法字符，应报错）。
    """
    parts = query.split()
    if not parts:
        return None
    out = []
    for part in parts:
        if _HARD_SYNTAX.search(part):
            return None
        out.append('"%s"' % part.replace('"', '""') if _RELAXABLE_CHARS.search(part) else part)
    return " ".join(out)


def _like_escape(s: str) -> str:
    """LIKE 模式里的通配符转义（配合 SQL 里的 `ESCAPE '\\'`）。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self._migrate()
        #: 最近一次 search() 实际走的路：fts5 / trigram / like（调用方要把它报给用户，
        #: 不能把「回退 LIKE」伪装成索引命中）
        self.last_search_via = ""
        #: 查询里含 `- : .` 时是否做了"包成短语"的宽松重试（CLI 要如实告知）
        self.last_query_relaxed = False

    def _migrate(self) -> None:
        """老库补列：`peer` 是 2026-11-04 新增的（git 派生的工作区身份）。

        `CREATE TABLE IF NOT EXISTS` 不会给已存在的表加列，所以必须显式 ALTER；
        幂等：只在该列缺失时执行。
        """
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(sessions)")}
        if "peer" not in cols:
            self.con.execute("ALTER TABLE sessions ADD COLUMN peer TEXT")
        # 索引放在这里（而不是 SCHEMA 里）：老库的 sessions 表还没有 peer 列，
        # executescript 阶段建索引会直接 `no such column: peer` 挂掉。
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_peer ON sessions(peer)")
        # 数据 schema 版本：库比代码新 → 直接拒绝（新结构旧代码读会给出错答案，比崩溃更糟）
        cur = self.con.execute("PRAGMA user_version").fetchone()[0]
        if cur > SCHEMA_VERSION:
            raise RuntimeError(
                "索引库 schema 版本 %d 高于本代码支持的 %d：请升级 agent-memory 包（别用旧代码读新库）"
                % (cur, SCHEMA_VERSION))
        if cur < SCHEMA_VERSION:
            self.con.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        self.con.commit()

    def schema_version(self) -> tuple[int, int]:
        """返回 (库里的版本, 本代码支持的版本)；供 doctor 与测试使用。"""
        cur = self.con.execute("PRAGMA user_version").fetchone()[0]
        return cur, SCHEMA_VERSION

    # ── 写入 ────────────────────────────────────────────────────────────
    def upsert_session(self, cr: CollectResult, peer: str = "") -> bool:
        """写入一个会话；已存在则跳过（幂等）。返回是否新写入。

        `peer` 由 `ingest()` 按 cwd 的 git origin 派生后传入（见 peers.py）；
        老调用方不传就是空串（= 无归属），不影响其它字段。
        """
        m: SessionMeta = cr.meta
        from collectors.base import session_key as _sk
        key = _sk(m.agent, m.session_id)
        exists = self.con.execute(
            "SELECT message_count FROM sessions WHERE session_key=?", (key,)).fetchone()
        if exists:
            # 静默跳过 ≠ 内容相同：CN/AI 两套日志里实测有 22 个同名 session（大小相同、
            # 字节不同）。message_count 不同就说明**不是同一份**，必须让人看见
            # （2026-11-04 glm-5.3 第 2 轮复核：原实现连这个都不区分）。
            old = exists["message_count"] or 0
            if old != len(cr.records):
                print("  [重复 key] %s 已存在（%d 条）但本次是 %d 条，保留先入库的那份"
                      % (key, old, len(cr.records)))
            return False
        self.con.execute(
            "INSERT INTO sessions (session_key,agent,session_id,title,cwd,started_at,"
            "ended_at,model,provider,parent_session,origin,source_path,peer,"
            "message_count,tool_call_count,indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, m.agent, m.session_id, m.title, m.cwd, m.started_at, m.ended_at,
             m.model, m.provider, m.parent_session, m.origin, m.source_path, peer or "",
             m.message_count, m.tool_call_count, _now()))
        for r in cr.records:
            cur = self.con.execute(
                "INSERT INTO messages (session_key,agent,role,ts,seq,text) VALUES (?,?,?,?,?,?)",
                (key, m.agent, r.role, r.ts, r.seq, r.text))
            self.con.execute("INSERT INTO messages_fts (rowid,text) VALUES (?,?)",
                             (cur.lastrowid, r.text))
            self.con.execute("INSERT INTO messages_trgm (rowid,text) VALUES (?,?)",
                             (cur.lastrowid, r.text))
        self.con.commit()
        return True

    # ── 查询 ────────────────────────────────────────────────────────────
    _SEARCH_COLS = """m.id, m.session_key, m.agent, m.role, m.ts,
               substr(m.text, 1, 400) AS snippet,
               s.title, s.cwd, s.started_at, s.peer"""

    _SEARCH_SQL = """
        SELECT {cols}
        FROM {t} f
        JOIN messages m ON m.id = f.rowid
        JOIN sessions s ON s.session_key = m.session_key
        WHERE {t} MATCH ? {peer}
        ORDER BY rank
        LIMIT ?
        """

    def search(self, query: str, limit: int = 10, use_trigram: bool = False,
               like_fallback: bool = True, peer: str = "") -> list[dict]:
        """FTS5 检索；中文短词自动回退 LIKE 全表扫描。

        两条实测边界（2026-11-04，内存 FTS5 验证）：
          · `unicode61` 不切分 CJK ⇒ 默认索引**查不到任何中文子串**（含 3 字以上）；
          · `trigram` 只索引 3 字滑窗 ⇒ **1~2 字的中文词**（`质保`/`预算`）命不中。
        所以：FTS 零命中且查询含中文时回退 `LIKE '%词%'`（34k 条约十几 ms），
        并把 `last_search_via` 标成 `"like"`；空查询仍返回 `[]`（不算错误）；
        语法错误抛 `QueryError`，**不再**静默返回空列表。

        `peer` 非空时只检索该工作区身份下的会话（子串匹配，便于只写仓库名）。
        """
        self.last_search_via = "trigram" if use_trigram else "fts5"
        self.last_query_relaxed = False
        if not query or not query.strip():
            return []
        peer_sql = "AND s.peer LIKE ? ESCAPE '\\'" if peer else ""
        table = "messages_trgm" if use_trigram else "messages_fts"
        sql = self._SEARCH_SQL.format(cols=self._SEARCH_COLS, t=table, peer=peer_sql)

        def run(q):
            params = (q, "%" + _like_escape(peer) + "%", limit) if peer else (q, limit)
            return [dict(r) for r in self.con.execute(sql, params).fetchall()]

        try:
            rows = run(query)
        except sqlite3.OperationalError as exc:
            # 瞬时故障（锁/IO/内存）不许被重试掩盖 —— 要让调用方看见真故障
            if any(k in str(exc).lower() for k in _TRANSIENT_ERR):
                raise QueryError(query, str(exc)) from exc
            # 常见词的 `- : .` 会被 FTS5 当运算符（`agent-memory` → no such column 或 syntax error），
            # 先尝试"包成短语"再重试；真·语法字符（`C++`）仍按错误报出。
            relaxed = _relax_query(query)
            if not relaxed or relaxed == query:
                raise QueryError(query, str(exc)) from exc
            try:
                rows = run(relaxed)
                self.last_query_relaxed = True
            except sqlite3.OperationalError:
                raise QueryError(query, str(exc)) from exc
        if rows or not (like_fallback and _CJK_RE.search(query)):
            return rows
        hits = self._search_like(query, limit, peer=peer)
        if hits:
            self.last_search_via = "like"
        return hits

    def _search_like(self, query: str, limit: int, peer: str = "") -> list[dict]:
        """中文 1~2 字词的兜底：FTS5 两个索引都覆盖不到，只能全表 LIKE。

        排序按 `m.ts` 倒序（LIKE 没有相关性分）；这是**回退**，不是主路，
        调用方必须把 `last_search_via == "like"` 如实报出来。
        """
        peer_sql = "AND s.peer LIKE ? ESCAPE '\\'" if peer else ""
        sql = """
        SELECT {cols}
        FROM messages m
        JOIN sessions s ON s.session_key = m.session_key
        WHERE m.text LIKE ? ESCAPE '\\' {peer}
        ORDER BY m.ts DESC
        LIMIT ?
        """.format(cols=self._SEARCH_COLS, peer=peer_sql)
        params = (("%" + _like_escape(query) + "%",
                   "%" + _like_escape(peer) + "%", limit) if peer
                  else ("%" + _like_escape(query) + "%", limit))
        try:
            return [dict(r) for r in self.con.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as exc:
            # 回退路上的真错误（锁/IO）不许伪装成"没命中"（2026-11-04 glm-5.3 第 2 轮复核）
            raise QueryError(query, str(exc)) from exc

    def stats(self) -> dict:
        """统计**以入库条数为准**（`messages` 表），不用 sessions.message_count ——
        后者对 Hermes 来自导出 frontmatter、含工具消息，与"入索引的 user/assistant 条数"
        不是同一个口径，混用会让人以为索引漏了数据。"""
        rows = self.con.execute(
            "SELECT s.agent AS agent, COUNT(DISTINCT s.session_key) AS sessions, "
            "COUNT(m.id) AS msgs "
            "FROM sessions s LEFT JOIN messages m ON m.session_key = s.session_key "
            "GROUP BY s.agent ORDER BY -sessions").fetchall()
        total_msg = self.con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        pr = self.con.execute(
            "SELECT COUNT(DISTINCT peer) AS distinct_peers, COUNT(*) AS covered "
            "FROM sessions WHERE peer IS NOT NULL AND peer<>''").fetchone()
        return {"by_agent": [dict(r) for r in rows], "messages": total_msg,
                "sessions": self.con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "peers": {"distinct": pr["distinct_peers"], "sessions": pr["covered"]}}

    def peer_summary(self, limit: int = 20) -> list[dict]:
        """每个工作区身份（peer）的会话数、时间跨度与代表 cwd；空 peer 不列。"""
        return [dict(r) for r in self.con.execute("""
            SELECT s1.peer AS peer, COUNT(*) AS sessions,
                   MIN(s1.started_at) AS first_at, MAX(s1.started_at) AS last_at,
                   (SELECT s2.cwd FROM sessions s2
                    WHERE s2.peer=s1.peer AND s2.cwd IS NOT NULL AND s2.cwd<>''
                    GROUP BY s2.cwd ORDER BY COUNT(*) DESC LIMIT 1) AS top_cwd
            FROM sessions s1
            WHERE s1.peer IS NOT NULL AND s1.peer<>''
            GROUP BY s1.peer ORDER BY sessions DESC LIMIT ?""", (limit,))]

    def backfill_peers(self, peer_fn, only_missing: bool = True) -> dict:
        """给**已入库**的会话补 peer（幂等；`ingest` 对已存在会话会跳过）。

        实测必要性：peer 是 2026-11-04 新加的能力，555 个存量会话的 cwd 都还在，
        但没有 peer 列 —— 不补就得 `rmdir index` 重建 45 秒。
        """
        where = " WHERE peer IS NULL OR peer=''" if only_missing else ""
        rows = self.con.execute("SELECT session_key, cwd FROM sessions" + where).fetchall()
        cache: dict = {}
        updated = 0
        for r in rows:
            cwd = r["cwd"] or ""
            if cwd not in cache:
                try:
                    cache[cwd] = peer_fn(cwd)
                except Exception:                              # noqa: BLE001
                    cache[cwd] = ""
            p = cache[cwd]
            if p:
                self.con.execute("UPDATE sessions SET peer=? WHERE session_key=?",
                                 (p, r["session_key"]))
                updated += 1
        self.con.commit()
        return {"scanned": len(rows), "updated": updated}

    def close(self):
        self.con.close()

    # ── 话题归并（第二阶段 A）────────────────────────────────────────────
    def set_topics(self, session_key: str, entities, intents) -> None:
        """写入一个会话的实体/意图标签（先删后插，保证重跑幂等）。

        元素可以是 `str` 或 `(str, hits)`；hits 用于按"提及强度"排序，
        没有就记 1（老调用方兼容）。
        """
        self.con.execute("DELETE FROM session_topics WHERE session_key=?", (session_key,))
        for kind, labels in (("entity", entities), ("intent", intents)):
            for item in labels:
                label, hits = item if isinstance(item, (tuple, list)) else (item, 1)
                self.con.execute(
                    "INSERT OR REPLACE INTO session_topics (session_key,kind,label,hits) "
                    "VALUES (?,?,?,?)", (session_key, kind, label, int(hits)))

    def topic_pairs(self, min_sessions: int = 2) -> list[dict]:
        """按 (实体 × 意图) 聚合：会话数 + 时间跨度。时间线(B) 的输入。"""
        rows = self.con.execute("""
        SELECT e.label AS entity, i.label AS intent,
               COUNT(DISTINCT e.session_key) AS sessions,
               MIN(s.started_at) AS first_at, MAX(s.started_at) AS last_at
        FROM session_topics e
        JOIN session_topics i ON i.session_key = e.session_key AND i.kind='intent'
        JOIN sessions s ON s.session_key = e.session_key
        WHERE e.kind='entity'
        GROUP BY e.label, i.label
        HAVING sessions >= ?
        ORDER BY sessions DESC, entity
        """, (min_sessions,)).fetchall()
        return [dict(r) for r in rows]

    def topic_summary(self, kind: str) -> list[dict]:
        rows = self.con.execute("""
        SELECT t.label AS label, COUNT(DISTINCT t.session_key) AS sessions,
               MIN(s.started_at) AS first_at, MAX(s.started_at) AS last_at
        FROM session_topics t JOIN sessions s ON s.session_key = t.session_key
        WHERE t.kind=?
        GROUP BY t.label ORDER BY sessions DESC
        """, (kind,)).fetchall()
        return [dict(r) for r in rows]

    def coverage(self) -> dict:
        """标签覆盖率：多少会话至少有一个实体 / 一个意图（衡量词典是否够用）。"""
        total = self.con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        ent = self.con.execute(
            "SELECT COUNT(DISTINCT session_key) FROM session_topics WHERE kind='entity'"
        ).fetchone()[0]
        itn = self.con.execute(
            "SELECT COUNT(DISTINCT session_key) FROM session_topics WHERE kind='intent'"
        ).fetchone()[0]
        return {"sessions": total, "with_entity": ent, "with_intent": itn}

    def set_paths(self, session_key: str, dirs) -> None:
        """写入该会话的工具路径（dirs 为 [(dir, hits)]，先删后插保证幂等）。"""
        self.con.execute("DELETE FROM session_paths WHERE session_key=?", (session_key,))
        for item in dirs or ():
            d, hits = item if isinstance(item, (tuple, list)) else (item, 1)
            self.con.execute(
                "INSERT OR REPLACE INTO session_paths (session_key,dir,hits) VALUES (?,?,?)",
                (session_key, d, int(hits)))

    def paths_for(self, session_key: str) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.con.execute(
            "SELECT dir, hits FROM session_paths WHERE session_key=? ORDER BY hits DESC",
            (session_key,))]

    def sessions_for(self, entity: str, intent: str = "") -> list[dict]:
        """某实体（可再限定意图）下的会话，**按时间排序** —— 演变时间线(B) 的地基。"""
        if intent:
            sql = """
            SELECT s.session_key, s.agent, s.title, s.started_at, s.cwd
            FROM sessions s
            JOIN session_topics e ON e.session_key=s.session_key AND e.kind='entity'
            JOIN session_topics i ON i.session_key=s.session_key AND i.kind='intent'
            WHERE e.label=? AND i.label=?
            ORDER BY s.started_at
            """
            rows = self.con.execute(sql, (entity, intent)).fetchall()
        else:
            sql = """
            SELECT s.session_key, s.agent, s.title, s.started_at, s.cwd
            FROM sessions s
            JOIN session_topics e ON e.session_key=s.session_key AND e.kind='entity'
            WHERE e.label=?
            ORDER BY s.started_at
            """
            rows = self.con.execute(sql, (entity,)).fetchall()
        return [dict(r) for r in rows]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ingest(store: Store, results: Iterable[CollectResult], verbose: bool = False,
           peer_fn=None) -> dict:
    """批量写入。返回统计。

    `peer_fn(cwd) -> str` 决定每个会话的工作区身份（默认 `peers.peer_for_cwd`，
    测试可注入桩）。cwd 相同只算一次 —— 555 个会话实测极少有 555 个不同的 cwd。
    """
    added = skipped = 0
    by_agent: dict[str, int] = {}
    peer_cache: dict[str, str] = {}
    if peer_fn is None:
        from peers import peer_for_cwd
        peer_fn = peer_for_cwd
    t0 = time.perf_counter()
    for cr in results:
        try:
            from collectors.base import session_key as _sk2
            key2 = _sk2(cr.meta.agent, cr.meta.session_id)
            store.set_paths(key2, cr.tool_dirs)      # 路径每次都更新（不依赖新增）
            cwd = cr.meta.cwd or ""
            if cwd not in peer_cache:
                try:
                    peer_cache[cwd] = peer_fn(cwd)
                except Exception:                    # noqa: BLE001
                    peer_cache[cwd] = ""
            if store.upsert_session(cr, peer=peer_cache[cwd]):
                added += 1
                by_agent[cr.meta.agent] = by_agent.get(cr.meta.agent, 0) + 1
            else:
                skipped += 1
        except Exception as e:                            # noqa: BLE001
            print("  写入失败 %s/%s: %s: %s"
                  % (cr.meta.agent, cr.meta.session_id, type(e).__name__, e))
    return {"added": added, "skipped": skipped, "by_agent": by_agent,
            "sec": round(time.perf_counter() - t0, 1)}
