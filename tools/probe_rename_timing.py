"""查 F:\\demo-wiki → F:\\demo-base 的真实切换时点（哪个会话之后就不再碰旧目录）。"""
import os
import sqlite3

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

for d in ("f:\\demo-wiki", "f:\\demo-base", "f:\\demo-next"):
    rows = list(con.execute("""
        SELECT s.started_at, s.agent, s.session_key
        FROM session_paths p JOIN sessions s ON s.session_key=p.session_key
        WHERE LOWER(p.dir)=? ORDER BY s.started_at""", (d,)))
    if not rows:
        print("[%s] 无记录" % d)
        continue
    print("[%-14s] 会话 %3d ｜ 首 %s ｜ 末 %s"
          % (d, len(rows), (rows[0]["started_at"] or "")[:19],
             (rows[-1]["started_at"] or "")[:19]))
    print("   最后 3 个碰它的会话：")
    for r in rows[-3:]:
        print("      %s %-8s %s" % ((r["started_at"] or "")[:19], r["agent"],
                                    r["session_key"][:40]))

print()
print("=== 按天看两者的交替（最近 12 天有活动的）===")
rows = list(con.execute("""
    SELECT substr(s.started_at,1,10) AS day,
           SUM(CASE WHEN LOWER(p.dir)='f:\\demo-wiki' THEN 1 ELSE 0 END) AS old_n,
           SUM(CASE WHEN LOWER(p.dir)='f:\\demo-base' THEN 1 ELSE 0 END) AS new_n
    FROM session_paths p JOIN sessions s ON s.session_key=p.session_key
    WHERE LOWER(p.dir) IN ('f:\\demo-wiki','f:\\demo-base')
    GROUP BY day ORDER BY day DESC LIMIT 12"""))
for r in rows:
    print("  %s  旧 demo-wiki %3d 会话 ｜ 新 demo-base %3d 会话"
          % (r["day"], r["old_n"], r["new_n"]))
con.close()
