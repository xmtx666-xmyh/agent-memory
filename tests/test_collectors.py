# -*- coding: utf-8 -*-
"""采集器契约：四种真实格式都要能解析出"人说的话"与"agent 的结论"。

夹具用**真实样本片段**（各取 2~3 行，字段与线上一致），不用手编理想格式 ——
否则测的是我的想象，不是采集器。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.base import clean_text, is_injected_context, texts_from_blocks  # noqa: E402
from collectors import claude, codex, hermes                                    # noqa: E402


def test_texts_from_blocks_skips_reasoning():
    blocks = [{"type": "reasoning", "text": "内部思考"},
              {"type": "text", "text": "可见结论"}]
    assert texts_from_blocks(blocks) == "可见结论"


def test_injected_context_detected():
    """agent 注入的"伪 user 消息"必须被识别（实测来源各一例）。"""
    assert is_injected_context("<system-reminder> x</system-reminder>")
    assert is_injected_context("Current runtime context. This snapshot …")
    assert is_injected_context("# AGENTS.md instructions\n<INSTRUCTIONS>")
    assert is_injected_context("<app-context>\n# Codex desktop context")
    # 人说的话不能被误杀
    assert not is_injected_context("你好，请用一句话介绍自己")
    assert not is_injected_context("刚才的测试2次都用了很长实际")


def test_clean_text_truncates():
    s = clean_text("x" * 30000)
    assert len(s) < 20100 and s.endswith("[截断]")


def test_codex_parses_message_and_counts_tools(tmp_path):
    p = tmp_path / "rollout-x.jsonl"
    lines = [
        {"timestamp": "2026-10-31T08:22:16Z", "type": "session_meta",
         "payload": {"session_id": "abc123", "cwd": "C:\\proj", "model_provider": "deepseek",
                     "timestamp": "2026-10-31T08:20:00Z"}},
        {"timestamp": "2026-10-31T08:22:17Z", "type": "response_item",
         "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "系统注入"}]}},
        {"timestamp": "2026-10-31T08:22:18Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "帮我审计这个仓库"}]}},
        {"timestamp": "2026-10-31T08:22:19Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell"}},
        {"timestamp": "2026-10-31T08:22:20Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "先看目录结构。"}]}},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    res = codex.read_session(str(p))
    assert res.meta.session_id == "abc123"
    assert res.meta.cwd == "C:\\proj"
    assert [r.role for r in res.records] == ["user", "assistant"]
    assert res.records[0].text == "帮我审计这个仓库"
    assert res.meta.tool_call_count == 1


def test_claude_parses_text_blocks_and_skips_noise(tmp_path):
    p = tmp_path / "s.jsonl"
    lines = [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-06-20T01:25:07Z",
         "sessionId": "s1"},
        {"type": "user", "timestamp": "2026-06-20T01:25:08Z", "sessionId": "s1",
         "cwd": "c:\\proj",
         "message": {"role": "user", "content": [{"type": "text", "text": "你好"}]}},
        {"type": "assistant", "timestamp": "2026-06-20T01:25:09Z", "sessionId": "s1",
         "message": {"role": "assistant",
                     "content": [{"type": "thinking", "thinking": "…"},
                                 {"type": "text", "text": "你好！"}]}},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    res = claude.read_session(str(p))
    assert [r.text for r in res.records] == ["你好", "你好！"]
    assert res.meta.session_id == "s"          # 来自文件名
    assert res.meta.title == "你好"            # 首条 user 兜底


def test_hermes_parses_md_sections(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("\n".join([
        "---",
        'session_id: "20260611_133723_9721b1"',
        'title: "测试标题"',
        'source: "tui"',
        'created_at: "2026-06-11T05:37:26Z"',
        "message_count: 2",
        "---",
        "",
        "## Messages",
        "",
        "### User — 2026-06-11T05:37:28Z",
        "",
        "为什么后台停了？",
        "",
        "### Assistant — 2026-06-11T05:38:13Z",
        "",
        "因为参数写错了。",
        "",
        "## Tool calls",
        "```json",
        "[]",
        "```",
    ]), encoding="utf-8")
    res = hermes.read_session(str(p))
    assert res.meta.title == "测试标题"
    assert [r.role for r in res.records] == ["user", "assistant"]
    assert res.records[0].text == "为什么后台停了？"
    assert res.records[1].text == "因为参数写错了。"
