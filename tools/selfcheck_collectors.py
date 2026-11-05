"""逐个采集器自检：找到了几个文件、第一个会话解析出什么。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors import claude, codex, dsh, hermes               # noqa: E402

for name, mod in (("dsh", dsh), ("codex", codex), ("claude", claude), ("hermes", hermes)):
    print("=" * 90)
    print("[%s] root=%s" % (name, mod.default_root()))
    files = mod.find_sessions()
    print("  找到文件: %d" % len(files))
    if files:
        print("  首个: %s" % files[0][:110])
    n = 0
    for res in mod.collect(limit=1):
        n += 1
        print("  解析: session_id=%s 标题=%r 消息=%d 工具调用=%d"
              % (res.meta.session_id, (res.meta.title or "")[:40],
                 res.meta.message_count, res.meta.tool_call_count))
        for r in res.records[:3]:
            print("     [%s] %s" % (r.role, r.text.replace("\n", " ")[:100]))
    if n == 0:
        print("  **没有产出任何会话**")
