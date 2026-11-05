"""抽验：某个意图标签下的会话，标题/首条正文是否真的符合该意图。

防止"标签看起来对、实际错"——按纪律，标签必须能人工复核。
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row


def sample(label, n=5):
    rows = con.execute("""
    SELECT s.session_key, s.agent, s.title, s.started_at
    FROM sessions s JOIN session_topics t ON t.session_key=s.session_key
    WHERE t.kind='intent' AND t.label=?
    ORDER BY s.started_at DESC LIMIT ?
    """, (label, n)).fetchall()
    print("=" * 96)
    print("[%s] 最近 %d 个会话" % (label, len(rows)))
    for r in rows:
        first = con.execute(
            "SELECT text FROM messages WHERE session_key=? AND role='user' "
            "ORDER BY seq LIMIT 1", (r["session_key"],)).fetchone()
        snippet = (first["text"] if first else "").replace("\n", " ")[:110]
        print("  %s %-7s %-34s %s" % ((r["started_at"] or "")[:10], r["agent"],
                                      (r["title"] or "(无标题)")[:32], snippet))


for lb in sys.argv[1:] or ["文档解析", "合规与风险"]:
    sample(lb)
con.close()
