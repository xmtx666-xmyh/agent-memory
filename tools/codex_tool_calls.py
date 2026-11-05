"""从 rollout 里数「工具调用次数与内容」——这是不受 prompt 缓存影响的硬指标。

token 数会因缓存状态波动（同前缀的第二次调用 cache 命中高），
但"为了找这个文件一共发起几次工具调用、分别做了什么"是稳定的行为度量。
"""
import collections
import json
import os

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".codex", "sessions")

THREADS = [
    ("base@demo-base", "01a1a060-9422-7871-861e-cd06bd78b0c8"),
    ("inject@demo-base", "01a1a061-ac4a-7292-96b0-d9bb1fe6712c"),
    ("base@F-root", "01a1a061-f5f5-7881-a2b2-51893f80c242"),
    ("inject@F-root", "01a1a063-d940-7d10-995c-75615599a622"),
]

files = []
for dirpath, _d, fs in os.walk(ROOT):
    for f in fs:
        if f.startswith("rollout-") and f.endswith(".jsonl"):
            files.append(os.path.join(dirpath, f))


def analyze(path):
    calls = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = ev.get("payload") or {}
            if not isinstance(p, dict):
                continue
            if p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") or ""
                try:
                    a = json.loads(args) if isinstance(args, str) else (args or {})
                except Exception:                          # noqa: BLE001
                    a = {}
                target = (a.get("path") or a.get("file_path") or a.get("cmd")
                          or a.get("pattern") or a.get("query") or "")
                calls.append((p.get("name") or "?", str(target)[:80]))
    return calls


print("%-16s %s" % ("臂", "工具调用（次数 ｜ 明细）"))
print("-" * 100)
for label, tid in THREADS:
    hit = [p for p in files if tid in os.path.basename(p)]
    if not hit:
        print("%-16s （无 rollout）" % label)
        continue
    calls = analyze(hit[0])
    print("%-16s %d 次" % (label, len(calls)))
    for i, (name, target) in enumerate(calls, 1):
        print("     %d. %-14s %s" % (i, name, target))
    kinds = collections.Counter(n for n, _t in calls)
    print("     小结: %s" % dict(kinds))
    print()
