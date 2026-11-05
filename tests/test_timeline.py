# -*- coding: utf-8 -*-
"""演变时间线契约：结论句抽取、状态判定、冲突检测（以及"不该报冲突"的反例）。

## 为什么要有这些测试

规则抽取最容易出两类错，两类都在真实数据上出现过：
  ① 抽到噪音（表格行、`**` 残留、菜单项「Bug 修复」）；
  ② 冲突检测把无关的东西当冲突（实测 40 个 `py:行号`、ollama/streamlit/chroma 全塞进
     一个「技术选型」键）——这种输出比没有更糟。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline import (extract_conclusions, extract_pairs, find_conflicts,  # noqa: E402
                      render, _valid_key)


def _msgs(*texts):
    return [("assistant", "2026-11-0%dT00:00:00Z" % (i + 1), t)
            for i, t in enumerate(texts)]


# ── 结论句抽取 ───────────────────────────────────────────────────────────
def test_extracts_heading_anchored_conclusion():
    cons = extract_conclusions(_msgs("### 结论\n改用 PageIndex 树导航，不再用 chunk 检索。"))
    assert cons and any("PageIndex" in c["text"] for c in cons)


def test_extracts_decision_phrase():
    cons = extract_conclusions(_msgs("3 处 check_health() 调用改为 .get('ok')，避免 KeyError。"))
    assert any("改为" in c["text"] for c in cons)


def test_skips_table_rows_and_menu_noise():
    """表格行与「Bug 修复」这类菜单项不该被当成结论。"""
    text = ("| 项目 | 说明 | 改为 |\n"
            "| --- | --- | --- |\n"
            "- Bug 修复\n"
            "- 项目部署\n")
    assert extract_conclusions(_msgs(text)) == []


def test_strips_markdown_prefix():
    cons = extract_conclusions(_msgs("> **结论：桌面版首选 pgvector（省心）或 LanceDB。"))
    assert cons and not cons[0]["text"].startswith(">")
    assert "**" not in cons[0]["text"]


# ── 状态判定 ─────────────────────────────────────────────────────────────
def test_status_superseded_and_verified():
    cons = extract_conclusions(_msgs(
        "该模块已废弃，不再用旧接口。",                       # superseded
        "实测 34 层全部上 GPU，吞吐 43 tok/s。"))            # verified
    st = {c["status"] for c in cons}
    assert "superseded_candidate" in st
    assert "verified" in st


# ── 冲突检测 ─────────────────────────────────────────────────────────────
def test_conflict_detected_for_same_param():
    cons = [{"text": "默认候选数 = 60，精排取前 60 条。", "ts": "2026-10-01"},
            {"text": "默认候选数 = 15，成本降 58%。", "ts": "2026-11-02"}]
    pairs = extract_pairs(cons)
    assert any(k == "默认候选数" for k, _v, _t in pairs), pairs
    cf = find_conflicts(pairs)
    assert cf and set(cf[0]["values"]) == {"60", "15"}


def test_no_conflict_for_unrelated_keys():
    """键不同 → 不是冲突（实测教训：别把所有技术词塞进一个「技术选型」键）。"""
    cons = [{"text": "端口 = 11434", "ts": "a"},
            {"text": "候选数 = 15", "ts": "b"}]
    assert find_conflicts(extract_pairs(cons)) == []


def test_extension_and_stopword_keys_rejected():
    """`py`/`md`/`txt` 这类文件后缀、`结论` 这类泛词不能当冲突键。"""
    for bad in ("py", "md", "txt", "结论", "最终", "根因"):
        assert not _valid_key(bad), bad
    for good in ("默认候选数", "端口", "预算", "阈值"):
        assert _valid_key(good), good


def test_file_line_pairs_no_longer_pollute():
    """`search_service.py:144` 这类不该产生 `py:144` 冲突（实测曾报 40 个）。"""
    cons = [{"text": "改 [search_service.py:144](x) 里的过滤逻辑，改为精确匹配。", "ts": "a"}]
    pairs = extract_pairs(cons)
    assert not any(k.lower() == "py" for k, _v, _t in pairs), pairs


# ── 渲染 ─────────────────────────────────────────────────────────────────
def test_render_contains_timeline_and_conflicts():
    tl = {"entity": "E", "intent": "I", "sessions": 2, "with_conclusions": 2,
          "entries": [{"session_key": "k1", "agent": "dsh", "title": "t1",
                       "started_at": "2026-10-01T00:00:00Z",
                       "conclusions": [{"text": "默认候选数 = 60。", "ts": "2026-10-01",
                                        "status": "decision", "why": "改为"}]},
                      {"session_key": "k2", "agent": "dsh", "title": "t2",
                       "started_at": "2026-11-02T00:00:00Z",
                       "conclusions": [{"text": "默认候选数 = 15。", "ts": "2026-11-02",
                                        "status": "decision", "why": "改为"}]}],
          "conflicts": [{"key": "默认候选数", "values": {"60": ["2026-10-01"],
                                                       "15": ["2026-11-02"]}}]}
    out = render(tl)
    assert "2026-10-01" in out and "2026-11-02" in out
    assert "跨会话冲突" in out and "默认候选数" in out
