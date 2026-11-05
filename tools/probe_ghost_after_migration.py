"""B 的关键问题：迁移发生**之后**，还有会话在引用旧路径吗？

若"最近仍在引用" → 注入迁移提示有真实价值（现在还在踩）；
若"迁移后没人再提" → 注入只是历史卫生，不是活跃收益。

迁移时点用「首次出现新目录名」近似（demo-base / demo-next 第一次出现在会话里）。
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

GHOSTS = [("F:\\demo-wiki", ["F:\\demo-base", "F:\\demo-next"]),
          ("F:\\demo-system", ["F:\\demo-base", "F:\\demo-next"]),
          ("D:\\demo-wiki", ["F:\\demo-base", "F:\\demo-next"])]

for ghost, successors in GHOSTS:
    sessions = list(con.execute(
        "SELECT DISTINCT s.session_key, s.started_at, s.agent FROM sessions s "
        "JOIN messages m ON m.session_key=s.session_key "
        "WHERE LOWER(m.text) LIKE ? ORDER BY s.started_at",
        ("%" + ghost.lower() + "%",)))
    if not sessions:
        print("[%s] 无会话引用" % ghost)
        continue
    # 后续者目录首次出现时间
    first_new = None
    for succ in successors:
        row = con.execute(
            "SELECT MIN(s.started_at) FROM sessions s JOIN messages m ON m.session_key=s.session_key "
            "WHERE LOWER(m.text) LIKE ?", ("%" + succ.lower() + "%",)).fetchone()
        if row and row[0] and (first_new is None or row[0] < first_new):
            first_new = row[0]
    after = [x for x in sessions if first_new and x["started_at"] > first_new]
    print("=" * 92)
    print("[%s] 引用会话 %d 个 ｜ 首 %s ｜ 末 %s"
          % (ghost, len(sessions), sessions[0]["started_at"][:10],
             sessions[-1]["started_at"][:10]))
    print("  迁移时点（首次出现新目录）≈ %s" % (first_new[:10] if first_new else "未知"))
    print("  **迁移后仍引用的会话：%d 个**" % len(after))
    for x in after[-6:]:
        print("     %s %-8s %s" % (x["started_at"][:10], x["agent"], x["session_key"][:44]))
con.close()
