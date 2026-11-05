"""CodeBuddy 会话采集器（与 WorkBuddy 同家族格式，复用其解析器）。

实测（2026-11-04）：`~/.codebuddy/projects/<slug>/<uuid>.jsonl` 的事件结构与 WorkBuddy
逐字一致（`type=message` + `content:[{type:"input_text"|"output_text"}]`；
user 正文同样可能被 `<system-reminder>` 包住）。所以这里只做"换根目录 + 换 agent 标签"，
解析逻辑单一来源在 `collectors/workbuddy.py`，避免两份实现漂移。
"""
from __future__ import annotations

import os

from collectors import workbuddy as _wb

AGENT = "codebuddy"
_ROOTS = ("~/.codebuddy/projects", "~/.codebuddycn/projects")


def default_roots() -> list[str]:
    return [p for p in (os.path.expanduser(r) for r in _ROOTS) if os.path.isdir(p)]


def collect(limit: int = 0):
    files = _wb.find_sessions(default_roots())
    if limit:
        files = files[:limit]
    for p in files:
        try:
            res = _wb.read_session(p, AGENT)
        except Exception as e:                            # noqa: BLE001
            print("  [codebuddy] 跳过 %s: %s: %s"
                  % (os.path.basename(p), type(e).__name__, e))
            continue
        if res:
            yield res
