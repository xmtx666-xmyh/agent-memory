"""看 superseded_candidate / experiment 这两类结论的真实内容。

判断依据：如果它们能带出"为什么被推翻/为什么是实验"，那"错误思路"就是可留档的资产；
如果只是零散一句，就只能当线索，不能当结论。
"""
import os
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

from timeline import extract_conclusions   # noqa: E402

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

rows = list(con.execute("""
SELECT s.session_key, s.agent, s.started_at, s.title
FROM sessions s
JOIN session_topics t ON t.session_key=s.session_key AND t.kind='entity' AND t.label='demo-kb'
ORDER BY s.started_at"""))

want = ("superseded_candidate", "experiment")
n = 0
for r in rows:
    msgs = [(x["role"], x["ts"], x["text"]) for x in con.execute(
        "SELECT role, ts, text FROM messages WHERE session_key=? ORDER BY seq",
        (r["session_key"],))]
    for c in extract_conclusions(msgs):
        if c["status"] not in want:
            continue
        n += 1
        if n > 12:
            break
        print("[%s] %s ｜ %s" % (c["status"], (r["started_at"] or "")[:10], r["agent"]))
        print("   %s" % c["text"][:190])
    if n > 12:
        break
print("\n共展示 %d 条" % min(n, 12))
con.close()
