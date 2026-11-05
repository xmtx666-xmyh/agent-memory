"""探工具调用里的路径结构（为"用碰过的文件定实体归属"做准备）。

三种来源各取一个会话，打印 tool call 的原始结构，找出路径字段在哪。
"""
import glob
import io
import json
import os

import zstandard

HOME = os.path.expanduser("~")


def dsh_events(path):
    raw = open(path, "rb").read()
    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) \
        .read().decode("utf-8", errors="replace").splitlines()


print("=" * 100)
print("① DSH tool/call 结构")
f = sorted(glob.glob(os.path.join(HOME, ".dsh", "sessions", "*", "*",
                                  "session.v4.jsonl.zstd")))[0]
n = 0
for ln in dsh_events(f):
    try:
        ev = json.loads(ln)
    except Exception:                                     # noqa: BLE001
        continue
    if ev.get("type") == "tool/call":
        print("  键:", list(ev.get("data", {}).keys()))
        d = ev.get("data", {})
        print("  name=%r" % d.get("name"))
        print("  结构:", json.dumps(d, ensure_ascii=False)[:450])
        n += 1
        if n >= 2:
            break

print()
print("=" * 100)
print("② Codex function_call 结构")
cx = sorted(glob.glob(os.path.join(HOME, ".codex", "sessions", "**", "rollout-*.jsonl"),
                      recursive=True))
n = 0
for p in cx[-3:]:
    for ln in open(p, encoding="utf-8", errors="replace"):
        try:
            ev = json.loads(ln)
        except Exception:                                 # noqa: BLE001
            continue
        if ev.get("type") == "response_item":
            pl = ev.get("payload") or {}
            if pl.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
                print("  payload 键:", list(pl.keys()))
                print("  ", json.dumps(pl, ensure_ascii=False)[:420])
                n += 1
                if n >= 2:
                    break
    if n >= 2:
        break

print()
print("=" * 100)
print("③ Claude tool_use 结构")
cl = sorted(glob.glob(os.path.join(HOME, ".claude", "projects", "**", "*.jsonl"),
                      recursive=True))
n = 0
for p in cl[-5:]:
    for ln in open(p, encoding="utf-8", errors="replace"):
        try:
            ev = json.loads(ln)
        except Exception:                                 # noqa: BLE001
            continue
        if ev.get("type") == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    print("  name=%r  input 键=%s" % (b.get("name"), list((b.get("input") or {}).keys())))
                    print("  ", json.dumps(b.get("input"), ensure_ascii=False)[:400])
                    n += 1
                    if n >= 2:
                        break
        if n >= 2:
            break
    if n >= 2:
        break
