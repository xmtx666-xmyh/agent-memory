"""验证 personaSuffix 是否生效（权威通道：会话日志里实际的 system/message）。

## 为什么要扫所有会话

DSH 把系统提示**当作历史消息写一次**（`request/context` 里显示 `systemPromptUpdate: in-history`），
不是在每轮重建。所以：
  · 老会话恢复后，系统提示仍是创建时那份 —— 用它验证会得到假阴性（我踩过）；
  · 真正的证据在**重启之后新建的会话**里。

本脚本扫全部会话，报出**最新一条 system/message** 的写入时间与是否包含注入指引。

## 用法

    F:\\agent-memory\\.venv\\Scripts\\python.exe tools\\verify_persona_effective.py

判定：
  ✅ 最新 system/message 在配置修改时间之后 且 含指引 → 已生效
  ⏳ 最新 system/message 早于配置修改时间 → 还没有新会话，需要新开一个
"""
import datetime
import glob
import io
import json
import os

import zstandard

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".dsh", "sessions")
CFG = os.path.join(HOME, ".dsh", "profiles", "desktop", "cordis.patch.yml")
NEEDLE = ".agent-memory/context.md"


def cfg_mtime() -> datetime.datetime:
    return datetime.datetime.fromtimestamp(os.path.getmtime(CFG))


def events(path):
    raw = open(path, "rb").read()
    reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
    for line in io.TextIOWrapper(reader, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def sys_text(ev) -> str:
    data = ev.get("data") or {}
    msg = data.get("message") or {}
    content = msg.get("content") or []
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text") or "")
    return "\n".join(out)


rows = []          # (写入时间, 会话目录, 是否含指引, 长度)
for p in glob.glob(os.path.join(ROOT, "*", "*", "session.v4.jsonl.zstd")):
    try:
        for ev in events(p):
            if (ev.get("type") or "") != "system/message":
                continue
            ts = ev.get("time")
            if not ts:
                continue
            when = datetime.datetime.fromtimestamp(ts / 1000)
            text = sys_text(ev)
            rows.append((when, os.path.basename(os.path.dirname(p)), NEEDLE in text, len(text)))
    except Exception:                                      # noqa: BLE001
        continue

if not rows:
    print("没有找到任何 system/message 事件")
    raise SystemExit(1)

rows.sort()
cm = cfg_mtime()
newest = rows[-1]
hits = [r for r in rows if r[2]]
print("配置修改时间: %s" % cm.strftime("%Y-%m-%d %H:%M:%S"))
print("system/message 事件总数: %d（含注入指引的 %d 条）" % (len(rows), len(hits)))
print("\n最近 5 条 system/message：")
for when, sess, has, n in rows[-5:]:
    print("  %s  %-46s %s  (%d 字符)"
          % (when.strftime("%m-%d %H:%M:%S"), sess, "✅含指引" if has else "—", n))

print()
if hits:
    when, sess, _has, _n = hits[-1]
    print("✅ 已生效：%s 的 system 提示含注入指引" % when.strftime("%Y-%m-%d %H:%M:%S"))
    raise SystemExit(0)

if newest[0] < cm:
    print("⏳ 尚未生效（预期）：最新的 system/message 是 %s，早于配置修改时间。"
          % newest[0].strftime("%m-%d %H:%M:%S"))
    print("   ⇒ DSH 把系统提示存成历史消息、重启不重建；**新开一个会话**后再跑本脚本即可确认。")
    raise SystemExit(2)

print("❌ 未生效但时间顺序正常 —— 说明配置没被加载，请检查：")
print("   · cordis.patch.yml 的 system-prompt 段是否在 `- id: system-prompt` 下")
print("   · 进程是否真的重启（StartTime 应晚于配置修改时间）")
raise SystemExit(1)
