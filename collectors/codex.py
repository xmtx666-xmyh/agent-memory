"""Codex（OpenAI Codex CLI / 桌面版）rollout 采集器。

格式（实测 2026-11-02）：`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，逐行：
  {"timestamp","type","payload"}
  type=session_meta   payload:{session_id, cwd, originator, cli_version, source, model_provider}
  type=response_item  payload:{type:"message", role:"user"|"assistant"|"developer",
                              content:[{type:"input_text"|"output_text", text}]}
                       payload:{type:"function_call"|"function_call_output"|"reasoning", ...}
  type=event_msg      payload:{type:"task_started"|"token_count"|...}
"""
from __future__ import annotations

import glob
import json
import os

from collectors.base import (CollectResult, Record, SessionMeta, clean_text,
                             is_injected_context, path_dirs_from_args, session_key,
                             texts_from_blocks, top_dirs)

AGENT = "codex"
_SKIP_ROLES = {"developer", "system"}


def default_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".codex", "sessions")


def find_sessions(root: str | None = None) -> list[str]:
    root = root or default_root()
    return sorted(glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True))


def read_session(path: str) -> CollectResult | None:
    meta = SessionMeta(agent=AGENT, source_path=path)
    records: list[Record] = []
    seq = 0
    dir_hits: dict[str, int] = {}
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
            p = ev.get("payload") or {}
            ts = ev.get("timestamp") or ""
            if t == "session_meta":
                meta.session_id = p.get("session_id") or p.get("id") or ""
                meta.cwd = p.get("cwd") or ""
                meta.origin = p.get("originator") or ""
                meta.provider = p.get("model_provider") or ""
                meta.started_at = p.get("timestamp") or ts
            elif t == "response_item":
                pt = p.get("type") or ""
                if pt == "message":
                    role = (p.get("role") or "").lower()
                    if role in _SKIP_ROLES or role not in ("user", "assistant"):
                        continue
                    txt = clean_text(texts_from_blocks(p.get("content")))
                    if txt and is_injected_context(txt):
                        continue
                    if txt:
                        records.append(Record(
                            session_key=session_key(AGENT, meta.session_id),
                            role=role, text=txt, ts=ts, seq=seq))
                        seq += 1
                elif pt in ("function_call", "local_shell_call", "custom_tool_call"):
                    meta.tool_call_count += 1
                    for d in path_dirs_from_args(p.get("arguments") or ""):
                        dir_hits[d] = dir_hits.get(d, 0) + 1
            elif t == "turn_context":
                meta.model = p.get("model") or meta.model
    if not meta.session_id:
        # 兜底：从文件名取 uuid
        base = os.path.basename(path)
        meta.session_id = base.replace("rollout-", "").replace(".jsonl", "")[-36:]
    if not meta.started_at and records:
        meta.started_at = records[0].ts
    if records:
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
            print("  [codex] 跳过 %s: %s: %s" % (os.path.basename(p), type(e).__name__, e))
            continue
        if res:
            yield res
