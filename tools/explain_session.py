"""诊断单条会话：为什么被打上某个标签（打印触发词）+ 实体归并是否生效。

用法：python tools/explain_session.py <session_key 片段>
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topics import ENTITIES, INTENTS, _kw_matcher, detect_entities   # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

needle = sys.argv[1] if len(sys.argv) > 1 else "14.2G"
row = con.execute("SELECT session_key, agent, title FROM sessions WHERE title LIKE ? "
                  "OR session_key LIKE ? LIMIT 1",
                  ("%%%s%%" % needle, "%%%s%%" % needle)).fetchone()
if not row:
    print("没找到含 %r 的会话" % needle)
    sys.exit(1)

sk = row["session_key"]
print("会话: %s ｜ %s ｜ %s" % (sk, row["agent"], row["title"]))
texts = [r["text"] for r in con.execute(
    "SELECT text FROM messages WHERE session_key=? ORDER BY seq", (sk,))]
joined = "\n".join(texts).lower()
print("正文: %d 条 / %d 字符" % (len(texts), len(joined)))

print("\n== 实体命中（归并后）==")
ents = detect_entities(joined)
print("  归属实体: %s" % (ents or "（无）"))
for canon, aliases in ENTITIES.items():
    hit = [a for a in aliases if a.lower() in joined]
    if hit:
        print("    %-22s ← 原文出现: %s" % (canon, hit))

print("\n== 意图命中（每个标签是哪些词触发的）==")
for label, kws in INTENTS.items():
    fired = [kw for kw in kws if _kw_matcher(kw)(joined)]
    if fired:
        print("  [%s] ← %s" % (label, fired))
con.close()
