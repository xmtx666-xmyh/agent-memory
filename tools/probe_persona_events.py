"""定位 `.agent-memory/context.md` 出现在哪类事件里、是不是重启后写的。

目的：区分两种情况
  A. 本会话（11-01 创建）恢复时不重建系统提示 ⇒ 要看新会话才为准
  B. 配置没被加载 ⇒ 需要排查
"""
import collections
import datetime
import glob
import io
import json
import os

import zstandard

HOME = os.path.expanduser("~")
files = glob.glob(os.path.join(HOME, ".dsh", "sessions", "*", "*", "session.v4.jsonl.zstd"))
files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
target = files[0]

NEEDLE = ".agent-memory/context.md"
RESTART = "2026-11-03T17:19"          # 重启时刻（本地时间，日志时间戳为本地/epoch 混合）

by_type = collections.Counter()
hit_by_type = collections.Counter()
time_hits = []
sys_times = []

raw = open(target, "rb").read()
reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
for line in io.TextIOWrapper(reader, encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    t = ev.get("type") or "?"
    by_type[t] += 1
    s = json.dumps(ev, ensure_ascii=False)
    has = NEEDLE in s
    if has:
        hit_by_type[t] += 1
    if t == "system/message":
        ts = ev.get("time")
        if ts:
            try:
                sys_times.append(datetime.datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M:%S"))
            except Exception:                              # noqa: BLE001
                pass
    if has and t not in ("user/message", "assistant/message"):
        ts = ev.get("time")
        try:
            stamp = datetime.datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M:%S") if ts else "?"
        except Exception:                                  # noqa: BLE001
            stamp = "?"
        time_hits.append((t, stamp))

print("事件类型统计（总数 / 含 .agent-memory/context.md）：")
for t, n in by_type.most_common():
    print("  %-34s %5d ｜ 命中 %d" % (t, n, hit_by_type.get(t, 0)))

print("\nsystem/message 的写入时间：")
for x in sys_times[:12]:
    print("   ", x)

print("\n非对话消息里的命中（类型, 时间）：")
for t, stamp in time_hits[:12]:
    print("   %-30s %s" % (t, stamp))
if not time_hits:
    print("   （只有对话消息里出现 —— 说明是我自己说的话，不是系统提示）")
