"""量化「失效前提」：结论句里引用的路径/端口，现在还有效吗？

思路：一条结论如果引用了 `F:\\demo-wiki\\xxx` 而该路径已不存在，它就是**过期**的；
如果一个字都没引用（纯观点），就**无法机械判定**，只能标注"未验证"。
这决定了"判断讨论是否失效"能自动化到什么程度。
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

from timeline import extract_conclusions   # noqa: E402

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'`<>|*?\n，。；）、]{3,200}")
PORT_RE = re.compile(r"(?:端口|port)[^\d]{0,6}(\d{2,5})")
entity = sys.argv[1] if len(sys.argv) > 1 else "demo-kb"

rows = list(con.execute("""
SELECT s.session_key, s.started_at FROM sessions s
JOIN session_topics t ON t.session_key=s.session_key AND t.kind='entity' AND t.label=?
ORDER BY s.started_at""", (entity,)))

stats = collections.Counter()
missing_paths = collections.Counter()
checked_paths = 0
examples = []

for r in rows:
    msgs = [(x["role"], x["ts"], x["text"]) for x in con.execute(
        "SELECT role, ts, text FROM messages WHERE session_key=? ORDER BY seq",
        (r["session_key"],))]
    for c in extract_conclusions(msgs):
        t = c["text"]
        stats["结论总数"] += 1
        paths = PATH_RE.findall(t)
        ports = PORT_RE.findall(t)
        if paths:
            stats["引用路径的结论"] += 1
        if ports:
            stats["引用端口的结论"] += 1
        if not paths and not ports:
            stats["无可验证前提（只能标未验证）"] += 1
        for p in paths:
            p = p.rstrip("\\.,:;)")
            checked_paths += 1
            # 只查盘符存在 + 前两层（避免逐层全查太慢）
            if not os.path.exists(p):
                missing_paths[p.lower()] += 1
                stats["路径已不存在"] += 1
                if len(examples) < 6:
                    examples.append((p, t[:100]))

print("项目 %s ｜ 会话 %d" % (entity, len(rows)))
for k, v in stats.most_common():
    print("  %-26s %d" % (k, v))
if checked_paths:
    print("  %-26s %.0f%%" % ("路径失效占比", 100.0 * stats["路径已不存在"] / checked_paths))
print("\n最常失效的路径（前 8）：")
for p, n in missing_paths.most_common(8):
    print("  %-52s %d 次" % (p, n))
print("\n失效样例：")
for p, t in examples:
    print("  [不存在] %s" % p)
    print("     结论: %s" % t)
con.close()
