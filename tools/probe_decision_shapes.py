"""量：同一项目里「决策」有多少种形态——同题异解、被推翻、失败实验。

目的：为「错误思路 / 思路递进」的建模提供实测依据，而不是凭直觉设计。
只看结论句（timeline.extract_conclusions），按项目（实体）聚合。
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

from timeline import (extract_conclusions, extract_pairs, _STATUS_RULES)  # noqa: E402

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

entity = sys.argv[1] if len(sys.argv) > 1 else "demo-kb"
rows = list(con.execute("""
SELECT s.session_key, s.agent, s.started_at, s.title
FROM sessions s
JOIN session_topics t ON t.session_key=s.session_key AND t.kind='entity' AND t.label=?
ORDER BY s.started_at""", (entity,)))
print("项目 %s ｜ 会话 %d" % (entity, len(rows)))

status_cnt = collections.Counter()
all_pairs = []                      # (key, value, ts, agent, sid)
concl_total = 0
for r in rows:
    msgs = [(x["role"], x["ts"], x["text"]) for x in con.execute(
        "SELECT role, ts, text FROM messages WHERE session_key=? ORDER BY seq",
        (r["session_key"],))]
    cons = extract_conclusions(msgs)
    concl_total += len(cons)
    for c in cons:
        status_cnt[c["status"]] += 1
    for k, v, ts in extract_pairs(cons):
        all_pairs.append((k, v, (r["started_at"] or "")[:10], r["agent"], r["session_key"]))

print("结论句 %d" % concl_total)
print("\n状态分布：")
for k, n in status_cnt.most_common():
    print("   %-22s %d" % (k, n))

print("\n同一决策键出现多个取值（= 思路递进的候选）：")
by_key = collections.defaultdict(list)
for k, v, d, agent, sid in all_pairs:
    by_key[k].append((v, d, agent))
shown = 0
for k, items in sorted(by_key.items(), key=lambda kv: -len(kv[1])):
    vals = {v for v, _d, _a in items}
    if len(vals) < 2:
        continue
    shown += 1
    if shown > 8:
        break
    print("  【%s】%d 个取值" % (k, len(vals)))
    for v, d, agent in sorted(items, key=lambda x: x[1])[:8]:
        print("      %s  %-10s %s=%s" % (d, agent, k, v))
con.close()
