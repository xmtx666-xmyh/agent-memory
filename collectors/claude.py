"""Claude Code 会话采集器。

格式（实测 2026-11-02）：`~/.claude/projects/<slug>/<uuid>.jsonl`，逐行：
  {"type":"user"|"assistant", "message":{"role","content":[{type:"text"|"thinking"|"tool_use"|"tool_result",...}]},
   "timestamp","sessionId","cwd","gitBranch","uuid","parentUuid"}
  {"type":"queue-operation"|"summary"|...}  ← 噪音，跳过
正文取 `message.content` 里的 text 块（跳过 thinking / tool 块）。
"""
from __future__ import annotations

import glob
import json
import os

from collectors.base import (CollectResult, Record, SessionMeta, clean_text,
                             is_injected_context, path_dirs_from_args, session_key,
                             texts_from_blocks, top_dirs)

AGENT = "claude"
_KEEP = {"user", "assistant"}


def default_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def find_sessions(root: str | None = None) -> list[str]:
    root = root or default_root()
    # 实测有嵌套（`<project>/<subdir>/*.jsonl`），必须递归，否则会漏 3/4
    return sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))


def read_session(path: str) -> CollectResult | None:
    meta = SessionMeta(agent=AGENT, source_path=path)
    meta.session_id = os.path.basename(path).replace(".jsonl", "")
    records: list[Record] = []
    seq = 0
    dir_hits: dict[str, int] = {}
    first_user = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type") or ""
            if t not in _KEEP:
                if t == "summary":
                    meta.title = meta.title or (ev.get("summary") or "")[:120]
                continue
            msg = ev.get("message") or {}
            role = (msg.get("role") or t).lower()
            content = msg.get("content")
            if isinstance(content, str):
                txt = clean_text(content)
            else:
                # tool_use / tool_result 也计数，但正文只取 text
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") in ("tool_use", "tool_result"):
                        meta.tool_call_count += 1
                    if b.get("type") == "tool_use":
                        for d in path_dirs_from_args(b.get("input") or {}):
                            dir_hits[d] = dir_hits.get(d, 0) + 1
                txt = clean_text(texts_from_blocks(content))
            if not txt:
                continue
            if is_injected_context(txt):
                continue
            meta.cwd = meta.cwd or (ev.get("cwd") or "")
            ts = ev.get("timestamp") or ""
            records.append(Record(session_key=session_key(AGENT, meta.session_id),
                                  role=role, text=txt, ts=ts, seq=seq))
            seq += 1
            if role == "user" and not first_user:
                first_user = txt.splitlines()[0][:120]
    if not records:
        return None
    if not meta.title:
        meta.title = first_user
    meta.started_at = records[0].ts
    meta.ended_at = records[-1].ts
    meta.message_count = len(records)
    return CollectResult(meta=meta, records=records, tool_dirs=top_dirs(dir_hits))


def collect(root: str | None = None, limit: int = 0):
    files = find_sessions(root)
    if limit:
        files = files[:limit]
    for p in files:
        try:
            res = read_session(p)
        except Exception as e:                            # noqa: BLE001
            print("  [claude] 跳过 %s: %s: %s" % (os.path.basename(p), type(e).__name__, e))
            continue
        if res:
            yield res
