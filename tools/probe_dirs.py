"""诊断：session_paths 里现存目录的会话数分布（为什么 init 只找到一个候选）。"""
import os
import sys

sys.path.insert(0, r"F:\agent-memory")

from store import Store
from paths import DB_FILE

st = Store(DB_FILE)
rows = list(st.con.execute("""
    SELECT p.dir AS dir, COUNT(DISTINCT p.session_key) AS n
    FROM session_paths p GROUP BY p.dir ORDER BY n DESC"""))
print("session_paths 目录数: %d" % len(rows))
print("%-46s %6s %s" % ("目录", "会话", "现在存在"))
for r in rows[:18]:
    d = r["dir"]
    print("%-46s %6d %s" % (d, r["n"], "是" if os.path.isdir(d) else "否"))
st.close()
