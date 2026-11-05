# -*- coding: utf-8 -*-
"""话题归并契约：实体同义、意图边界、多标签、幂等。

## 为什么这些测试重要（都是实测踩出来的）

1. **实体同义**：`demo-wiki`(307 会话) 与 `demo-base`(27) 是同一系统的前后两个名字；
   `DEMO2021` 与 `示例园区` 是同一项目。不合并 → 同一件事被拆成两条话题线。
2. **意图词必须词边界匹配**：`api` 裸词命中 281 会话（46%，含 `api key`/`capital` 之类），
   `session` 命中代码里的 `session_key`。这两个 bug 实测把「接口与前端」顶成第一大意图。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.base import CollectResult, Record, SessionMeta, session_key   # noqa: E402
from store import Store, ingest                                                # noqa: E402
from topics import (detect_entities, detect_intents, entities_from_paths,  # noqa: E402
                    label_session, label_session_scored)


# ── 实体同义 ─────────────────────────────────────────────────────────────
def test_system_aliases_merge():
    """同一demo-kb的历代名字必须归到同一实体。"""
    for name in ("demo-wiki", "demo-base", "demo-next", "demo-kb"):
        assert detect_entities("我们改 %s 的检索" % name) == ["demo-kb"], name


def test_project_aliases_merge():
    assert detect_entities("DEMO2021-SH090 的预算") == ["示例客户项目(DEMO2021)"]
    assert detect_entities("示例客户项目三期的预算") == ["示例客户项目(DEMO2021)"]


def test_multiple_entities():
    ents = detect_entities("用 codex 改 demo-base 的 PageIndex")
    assert "demo-kb" in ents and "Codex" in ents and "PageIndex" in ents


# ── 意图：词边界 ─────────────────────────────────────────────────────────
def test_ascii_keyword_needs_word_boundary():
    """ASCII 关键词必须词边界匹配：`fastapi` 不能命中 `myfastapix`。

    历史 bug（已修，见 docs/topics-a.md）：`ui`/`api` 用子串匹配会命中
    build / requirement / capital，把「接口与前端」顶成第一大意图。
    """
    assert "服务端接口" not in detect_intents("myfastapix 和 xuvicorny")
    assert "Web前端" not in detect_intents("the build requirement capital")


def test_ascii_keyword_matches_standalone():
    assert "服务端接口" in detect_intents("给 Flask 加一个接口")
    assert "上下文压缩" in detect_intents("压缩上下文窗口，避免 truncation")


def test_chinese_keyword_substring_ok():
    assert "检索与排序" in detect_intents("精排把金标送达率提高了")


def test_intent_cap_is_four():
    text = ("检索 精排 金标 评测 解析 切分 会话 压缩 架构 重构 部署 性能 "
            "前端 接口 数据库 sqlite 投标 招标 合规 风险")
    assert len(detect_intents(text)) <= 4


def test_no_entity_name_inside_intent_keywords():
    """纪律：意图关键词里不得出现实体名，否则同一件事被算两次。

    实测：`agent 协作` 里放了 `codex`/`workbuddy`，导致该意图虚高到 129 会话
    （其实只是"提到了 Codex"）。实体由 ENTITIES 负责，意图只描述"在干什么"。
    """
    from topics import ENTITIES, INTENTS
    entity_aliases = {a.lower() for aliases in ENTITIES.values() for a in aliases}
    for label, kws in INTENTS.items():
        for kw in kws:
            assert kw.lower() not in entity_aliases, \
                "意图 %r 的关键词 %r 是实体名" % (label, kw)


# ── 会话级打标 ───────────────────────────────────────────────────────────
def test_label_session_entity_needs_repeat():
    """实体要**多次**提到才算它的主话题；一次带过的不算（主次之分）。

    实测动机：一个 45K 字会话里 7 个项目名各出现一次，全都算实体 → 话题计数被稀释。
    """
    texts = ["demo-base 的检索", "demo-base 又出问题", "顺便提一句 codex"]
    ents, _intents = label_session(texts)
    assert "demo-kb" in ents
    assert "Codex" not in ents, "只提一次的实体不该算主话题"


def test_label_session_single_entity_fallback():
    """短会话只提一次唯一实体时仍要保留，否则短会话永远没标签。"""
    ents, _ = label_session(["检查 demo-base 的日志"])
    assert ents == ["demo-kb"]


def test_generic_word_once_does_not_label():
    """泛词出现一次不打标（实测：一次「字段」把「16G内存」会话判成字段抽取）。"""
    _ents, intents = label_session(["这个 SMBIOS 字段读不出单槽容量"])
    assert "字段抽取" not in intents


def test_specific_phrase_once_does_label():
    """具体短语出现一次就打标（`compaction` 基本只在本话题出现）。"""
    _ents, intents = label_session(["先做 compaction 把上下文收一下"])
    assert "上下文压缩" in intents


def test_label_session_union_and_top4():
    texts = ["demo-base 的检索", "demo-base 又改了", "金标评测跑基线 金标评测再跑"]
    ents, intents = label_session(texts)
    assert "demo-kb" in ents
    assert len(intents) <= 4
    assert "评测与金标准" in intents


# ── 存储与聚合 ───────────────────────────────────────────────────────────
def _mk(sid, texts, started="2026-11-01T00:00:00Z"):
    sk = session_key("dsh", sid)
    meta = SessionMeta(agent="dsh", session_id=sid, title="t", started_at=started)
    recs = [Record(session_key=sk, role="user", text=t, ts=started, seq=i)
            for i, t in enumerate(texts)]
    meta.message_count = len(recs)
    return CollectResult(meta=meta, records=recs)


@pytest.fixture()
def store(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    yield st
    st.close()


def test_set_topics_idempotent(store):
    ingest(store, [_mk("a", ["demo-base 检索"])])
    store.set_topics("dsh:a", ["demo-kb"], ["检索与排序"])
    store.set_topics("dsh:a", ["demo-kb"], ["检索与排序"])
    n = store.con.execute(
        "SELECT COUNT(*) FROM session_topics WHERE session_key='dsh:a'").fetchone()[0]
    assert n == 2                       # 1 实体 + 1 意图，没有重复


def test_topic_pairs_and_timeline_order(store):
    ingest(store, [_mk("s1", ["demo-base 检索"], started="2026-09-01T00:00:00Z"),
                   _mk("s2", ["demo-base 检索"], started="2026-06-01T00:00:00Z")])
    for key in ("dsh:s1", "dsh:s2"):
        store.set_topics(key, ["demo-kb"], ["检索与排序"])
    pairs = store.topic_pairs(min_sessions=2)
    assert pairs and pairs[0]["sessions"] == 2
    assert pairs[0]["first_at"] < pairs[0]["last_at"]
    rows = store.sessions_for("demo-kb")
    assert [r["session_key"] for r in rows] == ["dsh:s2", "dsh:s1"]   # 按时间升序


def test_sessions_for_filters_by_intent(store):
    ingest(store, [_mk("a", ["x"]), _mk("b", ["y"])])
    store.set_topics("dsh:a", ["demo-kb"], ["检索与排序"])
    store.set_topics("dsh:b", ["demo-kb"], ["评测与金标准"])
    assert len(store.sessions_for("demo-kb")) == 2
    assert len(store.sessions_for("demo-kb", "检索与排序")) == 1


# ── 工具路径 → 实体归属（第二阶段 A 的硬信号）────────────────────────────
def test_entities_from_paths_maps_aliases():
    """路径目录名命中别名时归到 canonical（demo-wiki → demo-kb）。"""
    from topics import entities_from_paths
    assert entities_from_paths([("f:\\demo-wiki", 100)]) == [("demo-kb", 100)]
    assert entities_from_paths([("f:\\demo-base", 5)]) == [("demo-kb", 5)]


def test_entities_from_paths_keeps_new_project():
    """不在词典里的新项目目录，直接用目录名当实体。"""
    from topics import entities_from_paths
    assert entities_from_paths([("f:\\agent-memory", 183)]) == [("agent-memory", 183)]


def test_entities_from_paths_drops_noise():
    """公共容器/用户主目录根不算项目。

    实测：`c:\\users\\demo` 曾让 "demo" 成为 56 个会话的实体；`f:\\demo-main` 是 DSH 默认工作区。
    """
    from topics import entities_from_paths
    assert entities_from_paths([("c:\\users\\demo", 35)]) == []
    assert entities_from_paths([("f:\\demo-main", 349)]) == []
    assert entities_from_paths([("f:\\demo-wiki\\docs", 1)]) == []      # 末段是公共名 docs


def test_entities_from_paths_dedupes_and_caps():
    from topics import entities_from_paths
    got = entities_from_paths([("f:\\demo-wiki", 10), ("f:\\demo-base", 5),
                               ("f:\\a", 3), ("f:\\b", 2), ("f:\\c", 1)])
    assert got[0][0] == "demo-kb"          # 同 canonical 只留一次
    assert len(got) <= 3


def test_tool_paths_outrank_text_mentions():
    """有工具路径时，实体以**路径**为准，正文提及不参与。

    实测动机：有会话在 cwd=F:\\demo-kb 里干活、产出 F:\\agent-memory 新项目，
    正文大量讨论 demo-base；只看正文会把它归成「demo-kb」。
    """
    texts = ["demo-wiki 的检索很难调", "demo-base 的评测也麻烦", "我们新建 agent-memory 吧"]
    ents, _ = label_session_scored(texts, tool_dirs=[("f:\\agent-memory", 183)])
    assert [e for e, _n in ents] == ["agent-memory"]


def test_falls_back_to_text_without_paths():
    from topics import label_session_scored
    texts = ["demo-wiki 检索一", "demo-wiki 检索二"]
    ents, _ = label_session_scored(texts, tool_dirs=[])
    assert [e for e, _n in ents] == ["demo-kb"]
