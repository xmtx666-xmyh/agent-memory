# -*- coding: utf-8 -*-
"""索引契约：FTS5 能搜、中文能被 trigram 搜到、幂等、统计正确。

判据都来自对 Hermes `session_search` 的实测：普通 FTS5 对中文短语不准
（`数据关系` 命中 0，因为原文是"数据**之**间的关系"），所以要**双索引**。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.base import CollectResult, Record, SessionMeta, session_key  # noqa: E402
from store import QueryError, Store, _relax_query, ingest                     # noqa: E402


def _make(agent="dsh", sid="s1", texts=(), title="测试会话", cwd="F:\\proj"):
    sk = session_key(agent, sid)
    meta = SessionMeta(agent=agent, session_id=sid, title=title, cwd=cwd,
                       started_at="2026-11-01T00:00:00Z")
    recs = [Record(session_key=sk, role=r, text=t, ts="2026-11-01T00:00:0%dZ" % i, seq=i)
            for i, (r, t) in enumerate(texts)]
    meta.message_count = len(recs)
    return CollectResult(meta=meta, records=recs)


@pytest.fixture()
def store(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    yield st
    st.close()


def test_ingest_and_search_english(store):
    res = _make(texts=[("user", "how do we handle PageIndex tree navigation"),
                       ("assistant", "PageIndex routes by tree structure")])
    r = ingest(store, [res])
    assert r["added"] == 1
    rows = store.search("PageIndex")
    assert len(rows) == 2
    assert rows[0]["agent"] == "dsh"


def test_trigram_finds_chinese_phrase(store):
    ingest(store, [_make(texts=[("user", "知识库需要知道数据之间的关系")])])
    # 普通 FTS5 对连续中文短语不稳定，trigram 必须能命中
    rows = store.search("数据之间的关系", use_trigram=True)
    assert len(rows) == 1
    assert "知识库" in rows[0]["snippet"]


def test_idempotent_ingest(store):
    res = _make(texts=[("user", "第一条")])
    ingest(store, [res])
    second = ingest(store, [_make(texts=[("user", "第一条")])])
    assert second["added"] == 0 and second["skipped"] == 1
    assert store.stats()["sessions"] == 1


def test_stats_group_by_agent(store):
    ingest(store, [_make(agent="dsh", sid="a", texts=[("user", "x")]),
                   _make(agent="codex", sid="b", texts=[("user", "y"), ("assistant", "z")])])
    st = store.stats()
    assert st["sessions"] == 2 and st["messages"] == 3
    by = {row["agent"]: row["sessions"] for row in st["by_agent"]}
    assert by == {"dsh": 1, "codex": 1}


def test_search_returns_session_meta(store):
    ingest(store, [_make(texts=[("user", "关于投标保证金的计算")], title="保证金讨论",
                         cwd="F:\\kb")])
    rows = store.search("保证金", use_trigram=True)
    assert rows and rows[0]["title"] == "保证金讨论" and rows[0]["cwd"] == "F:\\kb"


def test_empty_query_safe(store):
    ingest(store, [_make(texts=[("user", "内容")])])
    # 空查询不该抛异常（FTS5 对空 MATCH 会报错，实现里拦下返回空）
    assert store.search("") == []


# ── 2026-11-04 glm-5.3 复核后补的三条契约 ────────────────────────────────
def test_invalid_query_raises_visible_error(store):
    """查询语法错误必须报出来，不能静默变成"零命中"。"""
    ingest(store, [_make(texts=[("user", "C++ 与 Rust 的取舍")])])
    with pytest.raises(QueryError):
        store.search("C++")


def test_hyphenated_word_is_relaxed_not_error(store):
    """`agent-memory` 这类词的 `-` 是 FTS5 运算符：必须自动包成短语，而不是报错。"""
    ingest(store, [_make(texts=[("user", "把 agent-memory 的 peer 改成 git origin")])])
    rows = store.search("agent-memory")
    assert rows, "带连字符的常见词搜不到就是回归"
    assert store.last_query_relaxed is True
    assert store.last_search_via == "fts5"


def test_short_chinese_query_falls_back_to_like(store):
    """1~2 字中文：trigram (3 字滑窗) 命不中，必须回退 LIKE 且标记来源。"""
    ingest(store, [_make(texts=[("user", "质保期两年，投标保证金按 2% 收取")])])
    assert store.search("质保", use_trigram=True, like_fallback=False) == []
    rows = store.search("质保", use_trigram=True)
    assert rows and "质保" in rows[0]["snippet"]
    assert store.last_search_via == "like"


def test_chinese_without_trigram_also_falls_back(store):
    """unicode61 不切分 CJK：不加 --trigram 的中文查询也应回退而不是空。"""
    ingest(store, [_make(texts=[("user", "投标保证金按 2% 收取")])])
    rows = store.search("保证金")
    assert rows and store.last_search_via == "like"
    # 英文正常走索引
    rows_en = store.search("PageIndex")
    assert rows_en == [] and store.last_search_via == "fts5"


# ── peer（2026-11-04 新增：工作区身份按 git origin 派生，见 peers.py）────
def test_ingest_records_peer_via_peer_fn(store):
    ingest(store, [_make(texts=[("user", "PageIndex alpha")])],
           peer_fn=lambda cwd: "github.com-owner-repo")
    rows = store.search("PageIndex", like_fallback=False)
    assert rows[0]["peer"] == "github.com-owner-repo"
    assert store.stats()["peers"] == {"distinct": 1, "sessions": 1}


def test_schema_version_written(store):
    """数据 schema 版本要写进 PRAGMA user_version（包版本 ≠ 数据版本，doctor 靠它对账）。"""
    assert store.schema_version() == (1, 1)


def test_search_filters_by_peer(store):
    ingest(store, [_make(agent="dsh", sid="a", texts=[("user", "PageIndex alpha")])],
           peer_fn=lambda cwd: "peer-alpha")
    ingest(store, [_make(agent="codex", sid="b", texts=[("user", "PageIndex beta")])],
           peer_fn=lambda cwd: "peer-beta")
    assert len(store.search("PageIndex")) == 2
    assert len(store.search("PageIndex", peer="peer-alpha")) == 1
    assert store.search("PageIndex", peer="no-such-peer") == []


def test_backfill_peers_fills_existing_sessions(store):
    ingest(store, [_make(texts=[("user", "PageIndex")])], peer_fn=lambda cwd: "")
    assert store.stats()["peers"]["distinct"] == 0
    r = store.backfill_peers(lambda cwd: "github.com-x-y")
    assert r["updated"] == 1
    assert store.stats()["peers"]["distinct"] == 1
    again = store.backfill_peers(lambda cwd: "github.com-x-y")
    assert again["scanned"] == 0, "幂等：已补过的不再扫"


# ── 第 2 轮 glm-5.3 复核后补的 4 条契约 ─────────────────────────────────
def test_search_peer_escapes_like_wildcards(store):
    """peer 过滤要按**字面**匹配：`_` / `%` 不能当通配符（FTS 路径原本漏了 ESCAPE）。"""
    ingest(store, [_make(texts=[("user", "PageIndex x")])],
           peer_fn=lambda cwd: "path_demo-base")
    assert len(store.search("PageIndex", peer="path_demo")) == 1
    assert store.search("PageIndex", peer="path_demo%") == []
    assert store.search("PageIndex", peer="path_demo_ase") == []


def test_duplicate_key_with_different_size_warns(store, capsys):
    """同 key 已存在但条数不同 ⇒ 不是同一份内容，必须打警告（不能静默丢）。"""
    ingest(store, [_make(texts=[("user", "a")])])
    ingest(store, [_make(texts=[("user", "a"), ("assistant", "b")])])
    assert "重复 key" in capsys.readouterr().out


def test_transient_error_is_not_masked_by_relaxation(store, monkeypatch):
    """`database is locked` 这类瞬态故障不能被"宽松重试"吞成正常结果。"""
    import sqlite3
    ingest(store, [_make(texts=[("user", "x")])])

    class Boom:                     # sqlite3.Connection 的属性是只读的，只能整体替换
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            pass

    monkeypatch.setattr(store, "con", Boom())
    with pytest.raises(QueryError):
        store.search("a-b")


def test_relax_query_boundaries():
    assert _relax_query("agent-memory") == '"agent-memory"'
    assert _relax_query("qwen3.5:9b") == '"qwen3.5:9b"'
    assert _relax_query("agent-memory 质检") == '"agent-memory" 质检'
    assert _relax_query("C++") is None
    assert _relax_query("a*b") is None
    assert _relax_query("") is None
