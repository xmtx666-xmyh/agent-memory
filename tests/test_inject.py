# -*- coding: utf-8 -*-
"""注入块契约：压缩、正确后继、预算、不产生荒谬规则。

## 为什么这几条必须钉住

注入块是**唯一真正进到 agent 上下文里的东西**——它错了就是主动误导，比不注入更糟。
实测踩过的两个错：
  ① 后继目录按字母序 → 写成 `f:\\demo-wiki2`，正确答案是 `f:\\demo-base`（最近在用的那个）
  ② 容器目录混进规则表 → 产生 `c:\\users → f:\\demo-base` 这种荒谬规则
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inject import _collapse, _render_dead, build_injection, MARKER   # noqa: E402
from topics import ENTITIES                            # noqa: E402

#: 真库用例依赖**本机数据**（`index/sessions.db` + 本机实体表）。
#: 换台机器装完 install 后，实体名是新机器的目录名，这些断言无从成立——
#: 所以显式 skip 并说明原因（不是静默跳过，也不是让它永久红）。
#: 不依赖真库的 `_collapse` 用例照常跑。
_REAL_DB_ENTITY = "demo-kb"
_HAS_REAL_DATA = _REAL_DB_ENTITY in ENTITIES and os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "index", "sessions.db"))
needs_real_db = pytest.mark.skipif(
    not _HAS_REAL_DATA,
    reason="本机没有 %r 实体（换机后正常）；真库类用例跳过，"
           "_collapse 等纯逻辑用例仍然有效" % _REAL_DB_ENTITY)


DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")


def _items(*paths, verdict="dead_with_successor", when="2026-10-28"):
    return [{"verdict": verdict, "paths": [p], "when": when, "note": "", "text": ""}
            for p in paths]


# ── 压缩：同目录多条路径 → 一条规则 ─────────────────────────────────────
def test_collapse_by_old_dir():
    live = {"E": ["f:\\new"]}
    items = _items("F:\\old\\a.py", "F:\\old\\b.py", "F:\\other\\c.py")
    rules = _collapse(items, live, "E")
    assert set(rules) == {"f:\\old", "f:\\other"}
    assert rules["f:\\old"]["n"] == 2


def test_collapse_skips_container_dirs():
    """`c:\\users` 是容器不是项目，不能变成「已迁移」规则。"""
    live = {"E": ["f:\\new"]}
    rules = _collapse(_items("C:\\Users\\demo\\.codex\\x.json"), live, "E")
    assert rules == {}


def test_collapse_whole_dir_ref_not_counted_as_resolved():
    """整目录引用（`F:\\old` 后无子路径）不能算"可解析"——那会让提示说"相对路径多不变"。"""
    live = {"E": ["f:\\new"]}
    rules = _collapse(_items("F:\\old"), live, "E")
    assert rules["f:\\old"]["resolved"] == 0


# ── 失效清单：只能说"真的没了"的路径 ───────────────────────────────────
def test_dead_render_skips_container_dirs():
    """容器不是项目：`c:\\users` 不能作为「已不存在」的结论出现。"""
    items = _items("C:\\Users\\demo\\.codex\\gone.json", verdict="dead_no_successor")
    assert _render_dead(items) == []


def test_dead_render_skips_paths_that_still_exist(monkeypatch):
    """路径还在就不能说"已不存在"（同一条结论里没死的那条也不能报）。"""
    monkeypatch.setattr("inject.os.path.exists", lambda p: True)
    items = _items("F:\\gone-proj-fake\\x.py", verdict="dead_no_successor")
    assert _render_dead(items) == []


def test_dead_render_keeps_really_missing_project():
    items = _items("F:\\gone-proj-fake\\x.py", verdict="dead_no_successor")
    lines = _render_dead(items)
    assert len(lines) == 1 and "gone-proj-fake" in lines[0]


# ── 后继选择：要按证据，不能按顺序/字母序（两次踩坑） ──────────────────
def test_per_rule_successor_picks_dir_where_files_exist(tmp_path):
    """谁能真正解析出文件谁就是后继。

    实测两次坑：① 字母序选到 `f:\\demo-wiki2`；② "最近使用"选到 `f:\\demo-kb`
    （那是跑采集的会话 cwd，天然最新），正确答案 `f:\\demo-base` 被挤掉。
    """
    d_has = tmp_path / "has"
    d_no = tmp_path / "no"
    (d_has / "server" / "api").mkdir(parents=True)
    (d_has / "server" / "api" / "wiki.py").write_text("x", encoding="utf-8")
    d_no.mkdir()
    old = "F:\\old-proj-fake"           # 不能用 tmp_path：它在 C:\Users 下会被容器规则过滤
    live = {"E": [str(d_no), str(d_has)]}      # 故意把"没有的"排在前面
    rules = _collapse(_items(old + "\\server\\api\\wiki.py"), live, "E")
    rule = list(rules.values())[0]
    assert rule["succ"] == str(d_has), rule
    assert rule["evidence"] > 0


def test_no_evidence_rule_points_nowhere():
    """一条都解析不出来时不能瞎指：succ 留空。"""
    old = "F:\\nonexistent-proj-xyz"
    rules = _collapse(_items(old + "\\server\\api\\wiki.py"), {"E": ["f:\\something"]}, "E")
    rule = list(rules.values())[0]
    assert rule["succ"] == "", rule
    assert rule["evidence"] == 0


# ── 真实库上的注入块 ─────────────────────────────────────────────────────
@needs_real_db
def test_injection_shape_and_budget():
    r = build_injection(DB, "demo-kb", max_chars=1400)
    t = r["text"]
    assert MARKER in t and "check_at=" in t
    assert "→" in t, "必须有旧目录→新目录的换算表"
    assert len(t) <= 1400, "必须遵守字符预算"
    assert "c:\\users" not in t.lower(), "容器目录不能出现在规则表里"


@needs_real_db
def test_injection_points_to_right_successor():
    """后继必须是「最近还在用的」目录（f:\\demo-base），不是字母序第一个。"""
    r = build_injection(DB, "demo-kb")
    line = [ln for ln in r["text"].splitlines() if "demo-wiki" in ln and "→" in ln]
    assert line, r["text"]
    assert "demo-base" in line[0], line[0]


@needs_real_db
def test_injection_is_much_smaller_than_item_count():
    """40 条迁移条目必须压成个位数规则（否则注入就是灌上下文）。"""
    r = build_injection(DB, "demo-kb")
    assert r["stats"]["migrate_items"] >= 10
    assert r["stats"]["rules"] <= 5, r["stats"]
    assert r["stats"]["est_tokens"] <= 500, r["stats"]


@needs_real_db
def test_dead_section_present():
    r = build_injection(DB, "demo-kb")
    assert "已确认失效" in r["text"]
    assert "勿照做" in r["text"]
