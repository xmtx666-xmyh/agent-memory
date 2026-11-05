"""更硬的判据：会话的**工具调用**真的碰过幽灵目录吗？（而不只是正文提到）

`session_paths` 只记工具调用参数里的路径 —— 这是"真去操作"的证据。
若迁移后仍有会话在工具调用里指向 `f:\\demo-wiki`，说明 agent 真的在往不存在的目录干活（真踩坑）。
"""
import collections
import os
import sqlite3

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

GHOSTS = ["f:\\demo-wiki", "f:\\demo-system", "d:\\demo-wiki"]

for ghost in GHOSTS:
    rows = list(con.execute("""
        SELECT p.session_key, s.started_at, s.agent, s.title
        FROM session_paths p JOIN sessions s ON s.session_key=p.session_key
        WHERE LOWER(p.dir)=? ORDER BY s.started_at""", (ghost,)))
    print("=" * 96)
    print("[%s] 工具调用碰过该目录的会话：%d 个" % (ghost, len(rows)))
    if rows:
        by_agent = collections.Counter(r["agent"] for r in rows)
        by_month = collections.Counter((r["started_at"] or "")[:7] for r in rows)
        print("  按 agent：%s" % dict(by_agent))
        print("  按月份：  %s" % dict(sorted(by_month.items())))
        print("  最近 5 个：")
        for r in rows[-5:]:
            print("     %s %-8s %s" % ((r["started_at"] or "")[:10], r["agent"],
                                       (r["title"] or "")[:44]))
    # 对照：同项目的新目录被碰过多少会话
    for new in ("f:\\demo-base", "f:\\demo-next"):
        n = con.execute("SELECT COUNT(DISTINCT session_key) FROM session_paths "
                        "WHERE LOWER(dir)=?", (new,)).fetchone()[0]
        print("  对照 %-16s 被 %d 个会话的工具调用碰过" % (new, n))
con.close()
