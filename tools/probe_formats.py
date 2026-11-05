"""摸清四种 agent 会话的真实格式，供写采集器用。

原则：不猜格式，每个来源都抓一条真实记录打印结构。
"""
import collections
import glob
import io
import json
import os
import sys

HOME = os.path.expanduser("~")


def head_lines(path, n=3):
    """读 zstd 或纯文本文件的前 n 行。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:4] == b"\x28\xb5\x2f\xfd":                     # zstd magic
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        # 多帧：用 stream_reader 逐帧解
        try:
            raw = dctx.stream_reader(io.BytesIO(raw)).read()
        except Exception as e:                            # noqa: BLE001
            return ["<zstd err: %s>" % e]
    text = raw.decode("utf-8", errors="replace")
    return text.splitlines()[:n]


def show(title, path, n=2):
    print("=" * 100)
    print("%s\n  %s" % (title, path))
    try:
        lines = head_lines(path, n)
    except Exception as e:                                # noqa: BLE001
        print("  读取失败: %s: %s" % (type(e).__name__, e))
        return
    for i, ln in enumerate(lines):
        print("  [%d] %s" % (i, ln[:600]))
    # 键结构统计（前 3 行）
    keys = collections.Counter()
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:                                 # noqa: BLE001
            continue
        if isinstance(obj, dict):
            keys.update(obj.keys())
    if keys:
        print("  顶层键: %s" % dict(keys))


# ① DSH
dsh = glob.glob(os.path.join(HOME, ".dsh", "sessions", "*", "*", "session.v4.jsonl.zstd"))
if dsh:
    show("① DSH", dsh[0], 3)

# ② Codex rollout
cx = sorted(glob.glob(os.path.join(HOME, ".codex", "sessions", "**", "rollout-*.jsonl"),
                      recursive=True))
if cx:
    show("② Codex", cx[-1], 3)

# ③ Claude
cl = sorted(glob.glob(os.path.join(HOME, ".claude", "projects", "**", "*.jsonl"),
                      recursive=True))
if cl:
    show("③ Claude", cl[-1], 3)

# ④ Hermes（已导出为 md，但原始在 state.db；这里看导出 md 的头部）
md = sorted(glob.glob(r"F:\hermes-export\sessions\*.md"))
if md:
    print("=" * 100)
    print("④ Hermes（导出的 md）\n  %s" % md[0])
    with open(md[0], encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh):
            if i > 12:
                break
            print("  [%d] %s" % (i, ln.rstrip()[:200]))
