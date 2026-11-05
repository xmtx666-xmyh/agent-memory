"""查：本机会话库里，哪些会话在讨论 agent-memory？它们被标成了什么？

用来回答一个真实问题：正在讨论 F:\\agent-memory 的会话，
为什么在话题视图里可能被归到「demo-kb」。
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

print("=== 索引里 cwd 的分布（前 12）===")
for r in con.execute("""
    SELECT COALESCE(NULLIF(cwd,''),'(空)') AS cwd, COUNT(*) AS n
    FROM sessions GROUP BY 1 ORDER BY -n LIMIT 12"""):
    print("  %-52s %4d 会话" % (r["cwd"][:50], r["n"]))

print()
print("=== 提到 agent-memory 的会话 ===")
rows = list(con.execute("""
    SELECT DISTINCT s.session_key, s.agent, s.cwd, s.title, s.started_at,
           s.started_at AS st
    FROM sessions s JOIN messages m ON m.session_key = s.session_key
    WHERE LOWER(m.text) LIKE '%agent-memory%'
    ORDER BY s.started_at DESC LIMIT 10"""))
if not rows:
    print("  （索引里还没有任何会话提到 agent-memory —— 本项目是今天才建的）")
for r in rows:
    labels = [x["label"] for x in con.execute(
        "SELECT label FROM session_topics WHERE session_key=? AND kind='entity' "
        "ORDER BY hits DESC", (r["session_key"],))]
    intents = [x["label"] for x in con.execute(
        "SELECT label FROM session_topics WHERE session_key=? AND kind='intent' "
        "ORDER BY hits DESC", (r["session_key"],))]
    print("  %s %-7s cwd=%-26s %s" % ((r["started_at"] or "")[:10], r["agent"],
                                      (r["cwd"] or "(空)")[:24], (r["title"] or "")[:40]))
    print("       实体=%s ｜ 意图=%s" % (labels, intents))

print()
print("=== 索引的最新会话时间（看索引是否包含今天）===")
print(" ", con.execute("SELECT MAX(started_at) FROM sessions").fetchone()[0])
con.close()
