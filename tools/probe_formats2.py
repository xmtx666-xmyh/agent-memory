"""探 DSH 事件类型分布 + Hermes 导出 md 的正文结构。"""
import collections
import glob
import io
import json
import os

import zstandard

HOME = os.path.expanduser("~")


def dsh_lines(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read() \
        .decode("utf-8", errors="replace").splitlines()


files = glob.glob(os.path.join(HOME, ".dsh", "sessions", "*", "*", "session.v4.jsonl.zstd"))
types = collections.Counter()
samples = {}
for p in files[:40]:
    try:
        for ln in dsh_lines(p):
            try:
                obj = json.loads(ln)
            except Exception:                             # noqa: BLE001
                continue
            t = obj.get("type")
            types[t] += 1
            if t not in samples and isinstance(obj.get("data"), dict):
                samples[t] = obj
    except Exception:                                     # noqa: BLE001
        continue

print("=== DSH 事件类型（前 40 个会话）===")
for t, n in types.most_common(20):
    print("  %-28s %d" % (t, n))

print()
print("=== 消息类事件的 data 结构样例 ===")
for t in types:
    if t and any(k in t for k in ("message", "user", "assistant", "text")):
        d = samples.get(t, {}).get("data", {})
        print("  [%s] data 键=%s" % (t, list(d.keys())[:8]))
        for k, v in list(d.items())[:4]:
            print("      %-12s %s" % (k, str(v)[:150]))

print()
print("=== Hermes 导出 md 正文（前 40 行，跳过 frontmatter）===")
md = sorted(glob.glob(r"F:\hermes-export\sessions\*.md"))
if md:
    with open(md[0], encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    end = next((i for i, l in enumerate(lines) if l.strip() == "---" and i > 0), 0)
    for i, ln in enumerate(lines[end + 1:end + 40], end + 1):
        print("  [%d] %s" % (i, ln.rstrip()[:170]))
