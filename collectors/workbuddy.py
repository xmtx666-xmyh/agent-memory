"""WorkBuddy 会话采集器（同家族：CodeBuddy，见 codebuddy.py）。

格式（实测 2026-11-04）：`<root>/<project-slug>/<uuid>.jsonl`，**逐行一个事件**：
  {"type":"message","role":"user","content":[{"type":"input_text","text":"..."}],
   "sessionId","cwd","timestamp"(毫秒),"id","parentId"}
  {"type":"message","role":"assistant","content":[{"type":"output_text","text":"..."}], ...}
  {"type":"reasoning"|"function_call"|"function_call_result"|"file-history-snapshot"|"custom-title"} ← 噪音/工具

## 三个实测坑（不处理就会污染索引）

1. **user 正文被 `<system-reminder>` 包住**：身份文件（SOUL/IDENTITY/USER）、项目快照、
   automation 说明全在里面，单行最大实测 **87,136 字符**；真正的提问在 `<user_query>` 里。
   所以先取 `<user_query>`，再退化为"剥掉 reminder 块"。**不提取的后果是把系统提示当人话灌进索引**
   （一条 4 万字符），检索与话题全被污染。
   ⚠️ 别指望 `base.is_injected_context()` 兜底：本采集器**不调用**它；而且它的前缀是
   `"<system-reminder>"`（`startswith` 精确匹配），**匹配不了实测里带属性的
   `<system-reminder data-role="x">`** —— 这是那几份采集器的既有坑，与本文件无关。
2. **cwd 可能只在非 message 事件上**：workbuddy-ai 的 message 记录缺 cwd（实测 20 条），
   要扫全文件的任意事件兜底；**不按目录 slug 反猜**（slug 把 `\\` 和 `-` 混在一起，不可逆）。
3. **一行超长**：87 KB 是 system-reminder 撑的，不是正文；`clean_text` 的 20000 上限管的是正文。
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

from collectors.base import (CollectResult, Record, SessionMeta, clean_text,
                             path_dirs_from_args, session_key, texts_from_blocks,
                             top_dirs)

AGENT = "workbuddy"
_ROOTS = ("~/.workbuddy/projects", "~/.workbuddy-ai/projects")
_MS_MIN = 10 ** 12          # ≥ 1e12 视为毫秒时间戳（秒级只有 1e9 量级）

_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S)
_REMINDER_RE = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S)


def default_roots() -> list[str]:
    return [p for p in (os.path.expanduser(r) for r in _ROOTS) if os.path.isdir(p)]


def find_sessions(roots) -> list[str]:
    files: list[str] = []
    for root in roots:
        files.extend(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
    return sorted(set(files))


def _ms_to_iso(ts) -> str:
    """毫秒 epoch → ISO8601（UTC）；已经是字符串就原样返回。"""
    if isinstance(ts, (int, float)) and ts > _MS_MIN:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000.0))
    return ts if isinstance(ts, str) else ""


def extract_user_text(text: str) -> str:
    """从 user 消息里取出**人类真正说的那句话**。

    优先 `<user_query>`（automation / 定时任务）；否则剥掉 `<system-reminder>` 块。
    两者都没有就原样返回。
    """
    m = _USER_QUERY_RE.search(text or "")
    if m:
        return m.group(1).strip()
    out = _REMINDER_RE.sub("", text or "").strip()
    return out


def read_session(path: str, agent: str = AGENT) -> CollectResult | None:
    meta = SessionMeta(agent=agent, source_path=path)
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
            # cwd / model 可能挂在任意事件上（坑 2）
            if not meta.cwd and ev.get("cwd"):
                meta.cwd = ev["cwd"]
            prov = ev.get("providerData") or {}
            if not meta.model and prov.get("model"):
                meta.model = prov["model"]
            if t == "custom-title":
                meta.title = meta.title or str(ev.get("title") or "")[:120]
                continue
            if t == "function_call":
                meta.tool_call_count += 1
                for d in path_dirs_from_args(ev.get("arguments") or {}):
                    dir_hits[d] = dir_hits.get(d, 0) + 1
                continue
            if t != "message":
                continue
            role = (ev.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            txt = texts_from_blocks(ev.get("content"))
            if role == "user":
                txt = extract_user_text(txt)       # 坑 1
            txt = clean_text(txt)
            if not txt:
                continue
            records.append(Record(session_key=session_key(agent, meta.session_id),
                                  role=role, text=txt, ts=_ms_to_iso(ev.get("timestamp")),
                                  seq=seq))
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


def collect(limit: int = 0):
    """采集 WorkBuddy（中文版 + 国际版）。返回 CollectResult 生成器。"""
    files = find_sessions(default_roots())
    if limit:
        files = files[:limit]
    for p in files:
        try:
            res = read_session(p, AGENT)
        except Exception as e:                            # noqa: BLE001
            print("  [workbuddy] 跳过 %s: %s: %s" % (os.path.basename(p), type(e).__name__, e))
            continue
        if res:
            yield res
