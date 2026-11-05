"""从 Codex rollout 日志里提取每次调用的 token 用量（用于 A/B 的成本对比）。

rollout 是 JSONL，事件类型里有 `event_msg` 的 token_count / turn_context 等。
本脚本：按 thread id 找到对应 rollout 文件，累计 input/output token。
"""
import json
import os
import sys

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".codex", "sessions")

THREADS = {
    "base@demo-base": "01a1a060-9422-7871-861e-cd06bd78b0c8",
    "inject@demo-base": "01a1a061-ac4a-7292-96b0-d9bb1fe6712c",
    "base@F-root": "01a1a061-f5f5-7881-a2b2-51893f80c242",
    "inject@F-root": "01a1a063-d940-7d10-995c-75615599a622",
}

files = []
for dirpath, _d, fs in os.walk(ROOT):
    for f in fs:
        if f.startswith("rollout-") and f.endswith(".jsonl"):
            files.append(os.path.join(dirpath, f))

print("rollout 文件总数: %d" % len(files))
found = {}
for tid in THREADS.values():
    hit = [p for p in files if tid in os.path.basename(p)]
    if hit:
        found[tid] = hit[0]

if not found:
    print("按 thread id 未找到；列出今天修改过的 rollout：")
    import time
    today = time.strftime("%Y-%m-%d")
    for p in files:
        if time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(p))) == today:
            print("  ", os.path.basename(p))
    sys.exit(0)


def usage(path):
    tot = {"input": 0, "output": 0, "cached": 0, "reasoning": 0}
    keys = set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = ev.get("payload") or {}
            if isinstance(payload, dict):
                u = payload.get("usage") or (payload.get("info") or {}).get("usage")
                if isinstance(u, dict):
                    keys.update(u.keys())
                    tot["input"] = max(tot["input"], u.get("input_tokens") or 0)
                    tot["output"] = max(tot["output"], u.get("output_tokens") or 0)
                    tot["cached"] = max(tot["cached"], u.get("cached_input_tokens") or 0)
                    tot["reasoning"] = max(tot["reasoning"],
                                           u.get("reasoning_output_tokens") or 0)
    return tot, keys


print("%-16s %10s %8s %10s %s" % ("臂", "input", "output", "cached", "文件"))
for label, tid in THREADS.items():
    p = found.get(tid)
    if not p:
        print("%-16s   （没找到 rollout）" % label)
        continue
    u, keys = usage(p)
    print("%-16s %10d %8d %10d %s" % (label, u["input"], u["output"], u["cached"],
                                      os.path.basename(p)[:46]))
print()
print("（若 usage 全 0，说明该版本 rollout 的 token 字段名不同；已见字段：%s）" % (keys or "无"))
