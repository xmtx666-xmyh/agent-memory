"""诊断：每个意图关键词各命中多少会话，找出把标签顶上去的"元凶词"。

判据用**会话数**（不是消息数）：一个词只要在会话里出现一次就会给整个会话打上标签，
所以某个词出现在 300 个会话里，就等于给了 300 个会话该标签。
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topics import INTENTS, _kw_matcher          # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")

con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
rows = list(con.execute("SELECT session_key, text FROM messages"))
con.close()

# 每个 (label, kw) 命中的会话集合
hits = collections.defaultdict(set)
matchers = {(lb, kw): _kw_matcher(kw) for lb, kws in INTENTS.items() for kw in kws}
for sk, text in rows:
    low = (text or "").lower()
    for key, mt in matchers.items():
        if mt(low):
            hits[key].add(sk)

print("总会话数（去重）: %d" % len({sk for sk, _t in rows}))
print()
for label in INTENTS:
    kws = [(len(hits[(label, kw)]), kw) for kw in INTENTS[label]]
    kws.sort(reverse=True)
    total = len(set().union(*[hits[(label, kw)] for kw in INTENTS[label]]))
    print("[%s] 合计 %d 会话" % (label, total))
    for n, kw in kws[:5]:
        print("     %-22s %4d 会话" % (kw, n))
    print()
