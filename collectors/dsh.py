"""DSH（DeepSeek Harness）会话采集器。

格式（实测 2026-11-02）：`~/.dsh/sessions/<slug>/<uuid>/session.v4.jsonl.zstd`
多帧 zstd 压缩的 JSONL，逐行事件：
  {"type":"session", "id","createdAt","cwd","origin","parentSession",...}
  {"type":"session/title",     "data":{"title":...}}
  {"type":"request/context",   "data":{"provider","model","contextWindow"}}
  {"type":"user/message",      "data":{"role","content":[{type:"text",text}],"source"}}
  {"type":"assistant/message", "data":{"message":{"content":[{type:"text"|"reasoning",...}]},"usage"}}
  {"type":"tool/call"|"tool/result", ...}
"""
from __future__ import annotations

import glob
import io
import json
import os
from datetime import datetime, timezone

import zstandard

from collectors.base import (CollectResult, Record, SessionMeta, clean_text,
                             is_injected_context, path_dirs_from_args, session_key,
                             texts_from_blocks, top_dirs)

AGENT = "dsh"


def default_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".dsh", "sessions")


def find_sessions(root: str | None = None) -> list[str]:
    root = root or default_root()
    return sorted(glob.glob(os.path.join(root, "*", "*", "session.v4.jsonl.zstd")))


def _iter_events(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()
    reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
    for line in io.TextIOWrapper(reader, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _iso_from_ms(ms) -> str:
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:                                     # noqa: BLE001
        return ""


def read_session(path: str) -> CollectResult | None:
    meta = SessionMeta(agent=AGENT, source_path=path)
    records: list[Record] = []
    seq = 0
    dir_hits: dict[str, int] = {}
    for ev in _iter_events(path):
        et = ev.get("type") or ""
        data = ev.get("data") or {}
        if et == "session":
            meta.session_id = ev.get("id") or ""
            meta.cwd = ev.get("cwd") or ""
            meta.origin = ev.get("origin") or ""
            meta.parent_session = ev.get("parentSession") or ""
            meta.started_at = _iso_from_ms(ev.get("createdAt"))
        elif et == "session/title":
            meta.title = data.get("title") or meta.title
        elif et == "request/context":
            meta.provider = data.get("provider") or meta.provider
            meta.model = data.get("model") or meta.model
        elif et == "tool/call":
            meta.tool_call_count += 1
            for d in path_dirs_from_args(data.get("arguments") or ""):
                dir_hits[d] = dir_hits.get(d, 0) + 1
        elif et == "user/message":
            txt = clean_text(texts_from_blocks(data.get("content")))
            if txt and not is_injected_context(txt):
                records.append(Record(session_key=session_key(AGENT, meta.session_id),
                                      role="user", text=txt, ts=_iso_from_ms(ev.get("time")),
                                      seq=seq))
                seq += 1
        elif et == "assistant/message":
            msg = data.get("message") or {}
            txt = clean_text(texts_from_blocks(msg.get("content")))
            if txt:
                records.append(Record(session_key=session_key(AGENT, meta.session_id),
                                      role="assistant", text=txt,
                                      ts=_iso_from_ms(ev.get("time")), seq=seq))
                seq += 1
    if not meta.session_id:
        return None
    if not meta.started_at and records:
        meta.started_at = records[0].ts
    if records:
        meta.ended_at = records[-1].ts
    meta.message_count = len(records)
    return CollectResult(meta=meta, records=records, tool_dirs=top_dirs(dir_hits))


def collect(root: str | None = None, limit: int = 0):
    """逐个会话产出 CollectResult。limit>0 时只取前 N 个（调试用）。"""
    files = find_sessions(root)
    if limit:
        files = files[:limit]
    for p in files:
        try:
            res = read_session(p)
        except Exception as e:                            # noqa: BLE001
            print("  [dsh] 跳过 %s: %s: %s" % (os.path.basename(os.path.dirname(p)),
                                              type(e).__name__, e))
            continue
        if res:
            yield res
