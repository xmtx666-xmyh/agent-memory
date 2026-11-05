"""Hermes 会话采集器（读 `hermes sessions export --format md` 的产物）。

为什么读导出而不是它的 state.db：
  · state.db 是 226 MB 私有库、schema 60+ 列且随版本变；导出 md 是**稳定文本契约**。
  · 导出已有 `--redact` 脱敏，读导出顺带继承了脱敏。

md 结构（实测 2026-11-02）：
  ---（YAML frontmatter: session_id / title / source / created_at / model / cwd / message_count …）
  # <title>
  Session ID: `…`   Source: `…`   Working directory: `…`
  ## Messages
  ### User — 2026-06-11T05:37:28.493106Z
  <正文>
  ### Assistant — <ts>
  <正文>
  ## Tool calls
  ```json [ ... ] ```
"""
from __future__ import annotations

import glob
import json
import os
import re

from collectors.base import (CollectResult, Record, SessionMeta, clean_text,
                             path_dirs_from_args, session_key, top_dirs)

AGENT = "hermes"
_H3 = re.compile(r"^###\s+(User|Assistant|System|Tool)\s+—\s+(\S+)\s*$")


def default_root() -> str:
    # Hermes 没有固定导出目录（由 `hermes sessions export <dir>` 指定），
    # 所以这里只给**家目录相对**的约定位置，并允许 env 覆盖。
    # ⚠️ 不能写死某个盘上的路径：实测曾写死 F:\hermes-export\sessions，
    # 换台机器时 find_sessions 返回空、ingest 只打印"新增 0"**不报错**，
    # Hermes 的历史就静默丢失了。
    env = os.environ.get("AGENT_MEMORY_HERMES_ROOT")
    if env:
        return env
    for cand in (os.path.join(os.path.expanduser("~"), "hermes-export", "sessions"),
                 os.path.join(os.path.expanduser("~"), ".hermes", "sessions")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(os.path.expanduser("~"), "hermes-export", "sessions")


def find_sessions(root: str | None = None) -> list[str]:
    root = root or default_root()
    return sorted(glob.glob(os.path.join(root, "*.md")))


def _parse_frontmatter(lines: list[str]) -> tuple[dict, int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = {}
            for ln in lines[1:i]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"').strip("'")
            return fm, i + 1
    return {}, 0


def read_session(path: str) -> CollectResult | None:
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    fm, start = _parse_frontmatter(lines)
    meta = SessionMeta(agent=AGENT, source_path=path,
                       session_id=fm.get("session_id", "") or os.path.basename(path),
                       title=fm.get("title", ""),
                       cwd=fm.get("cwd", ""),
                       model=fm.get("model", ""),
                       provider=fm.get("provider", ""),
                       origin=fm.get("source", ""),
                       started_at=fm.get("created_at", ""),
                       ended_at=fm.get("ended_at", ""))
    records: list[Record] = []
    seq = 0
    role = ""
    ts = ""
    buf: list[str] = []
    in_tool_section = False
    tool_buf: list[str] = []

    def flush():
        nonlocal seq, buf
        if role in ("user", "assistant"):
            txt = clean_text("\n".join(buf))
            if txt:
                records.append(Record(session_key=session_key(AGENT, meta.session_id),
                                      role=role, text=txt, ts=ts, seq=seq))
                seq += 1
        buf = []

    for ln in lines[start:]:
        if ln.startswith("## "):
            flush()
            in_tool_section = "tool" in ln.lower()
            role = ""
            continue
        if in_tool_section:
            tool_buf.append(ln)
            continue
        m = _H3.match(ln)
        if m:
            flush()
            kind, ts = m.group(1), m.group(2)
            role = kind.lower()
            if role not in ("user", "assistant"):
                role = ""          # System / Tool 不入索引
            continue
        if role:
            buf.append(ln)
    flush()

    if not records:
        return None
    meta.started_at = meta.started_at or records[0].ts
    meta.message_count = int(fm.get("message_count") or len(records))
    meta.tool_call_count = int(fm.get("tool_call_count") or 0)
    # `## Tool calls` 段是一个 fenced json 数组；从中抽项目目录（用于实体归属）
    dir_hits: dict[str, int] = {}
    blob = "\n".join(tool_buf)
    for chunk in re.findall(r"\[.*?\]", blob, re.S):
        try:
            calls = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        for call in calls if isinstance(calls, list) else [calls]:
            if not isinstance(call, dict):
                continue
            args = (call.get("function") or {}).get("arguments") or call.get("arguments") or ""
            for d in path_dirs_from_args(args):
                dir_hits[d] = dir_hits.get(d, 0) + 1
    return CollectResult(meta=meta, records=records, tool_dirs=top_dirs(dir_hits))


def collect(root: str | None = None, limit: int = 0):
    files = find_sessions(root)
    if limit:
        files = files[:limit]
    for p in files:
        try:
            res = read_session(p)
        except Exception as e:                            # noqa: BLE001
            print("  [hermes] 跳过 %s: %s: %s" % (os.path.basename(p), type(e).__name__, e))
            continue
        if res:
            yield res
