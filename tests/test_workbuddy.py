# -*- coding: utf-8 -*-
"""WorkBuddy / CodeBuddy 采集契约：system-reminder 必须剥掉、user_query 必须取出。

依据（2026-11-04 实测 686 个 JSONL）：user 正文被 `<system-reminder>` 包住（单行最大 87 KB，
装的是身份文件/项目快照/automation 说明），真正的提问在 `<user_query>` 里；
assistant 正文在 `content:[{type:"output_text"}]`；cwd 可能只挂在 function_call 上。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors import codebuddy, workbuddy                    # noqa: E402


def _write_session(tmp_path, name="s1.jsonl"):
    p = tmp_path / name
    lines = [
        # 1) user：system-reminder + user_query（automation 那种）
        {"type": "message", "role": "user", "timestamp": 1790160481322,
         "sessionId": "s1", "cwd": "F:\\proj",
         "content": [{"type": "input_text",
                      "text": "<system-reminder data-role=\"x\">\n身份文件……\n</system-reminder>\n"
                              "<user_query>帮我把质保期改成两年</user_query>"}]},
        # 2) reasoning：噪音
        {"type": "reasoning", "timestamp": 1790160490000,
         "providerData": {"model": "glm-5.3-flash"}, "content": []},
        # 3) function_call：cwd 可能挂这里；顺带贡献 tool_dirs
        {"type": "function_call", "timestamp": 1790160500000, "name": "Read",
         "arguments": json.dumps({"file_path": "F:\\proj\\server\\api\\wiki.py"}),
         "cwd": "F:\\proj"},
        # 4) assistant：正文
        {"type": "message", "role": "assistant", "timestamp": 1790160510000,
         "providerData": {"model": "glm-5.3-flash"},
         "content": [{"type": "output_text", "text": "已把质保期改成两年。"}]},
        # 5) 噪音事件
        {"type": "file-history-snapshot", "timestamp": 1790160520000},
    ]
    with open(p, "w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(json.dumps(ln, ensure_ascii=False) + "\n")
    return str(p)


def test_workbuddy_extracts_user_query_and_strips_reminder(tmp_path):
    path = _write_session(tmp_path)
    res = workbuddy.read_session(path, "workbuddy")
    assert res is not None
    assert [r.role for r in res.records] == ["user", "assistant"]
    user = res.records[0].text
    assert user == "帮我把质保期改成两年", user
    assert "system-reminder" not in user and "身份文件" not in user
    assert res.meta.session_id == "s1"
    assert res.meta.cwd == "F:\\proj"
    assert res.meta.model == "glm-5.3-flash"
    assert res.meta.title == "帮我把质保期改成两年"
    assert res.meta.tool_call_count == 1
    assert res.meta.started_at.startswith("2026-")          # 毫秒 → ISO
    assert res.tool_dirs and res.tool_dirs[0][0] == "f:\\proj"


def test_workbuddy_plain_user_message_keeps_text(tmp_path):
    p = tmp_path / "s2.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "message", "role": "user", "timestamp": 1790160481322,
                             "content": [{"type": "input_text",
                                          "text": "<system-reminder>快照</system-reminder>"
                                                  "这个项目为什么要改默认值？"}]},
                            ensure_ascii=False) + "\n")
        fh.write(json.dumps({"type": "message", "role": "assistant", "timestamp": 1790160482000,
                             "content": [{"type": "output_text", "text": "因为召回成本。"}]},
                            ensure_ascii=False) + "\n")
    res = workbuddy.read_session(str(p), "workbuddy")
    assert res.records[0].text == "这个项目为什么要改默认值？"


def test_workbuddy_empty_session_returns_none(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text('{"type":"file-history-snapshot"}\n', encoding="utf-8")
    assert workbuddy.read_session(str(p), "workbuddy") is None


def test_codebuddy_reuses_parser(tmp_path, monkeypatch):
    path = _write_session(tmp_path)
    monkeypatch.setattr(codebuddy, "default_roots", lambda: [os.path.dirname(path)])
    got = list(codebuddy.collect())
    assert len(got) == 1
    assert got[0].meta.agent == "codebuddy"
    assert got[0].records[0].role == "user"
    assert got[0].records[0].session_key.startswith("codebuddy:")
