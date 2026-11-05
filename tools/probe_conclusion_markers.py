"""探：某话题下的会话里，有没有可识别的"结论句"（决定/废弃/实验/实测）。

目的是让抽取规则基于真实文本，不是我凭空列词。
抽 1 个话题（demo-kb × 检索与排序），看 assistant 正文里的标记词分布。
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")

MARKERS = ["结论", "决定", "定稿", "改为", "改成", "改用", "采用", "不再", "废弃",
           "回退", "改回", "验证通过", "实测", "判定", "确认", "修复", "实验", "对比",
           "推翻", "作废", "推荐"]

con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

topic = (sys.argv[1] if len(sys.argv) > 1 else "demo-kb",
         sys.argv[2] if len(sys.argv) > 2 else "检索与排序")
rows = con.execute("""
SELECT s.session_key, s.started_at, s.title
FROM sessions s
JOIN session_topics e ON e.session_key=s.session_key AND e.kind='entity' AND e.label=?
JOIN session_topics i ON i.session_key=s.session_key AND i.kind='intent' AND i.label=?
ORDER BY s.started_at LIMIT 12
""", topic).fetchall()
print("话题 %s × %s ｜ 抽前 %d 个会话" % (topic[0], topic[1], len(rows)))

hits = collections.Counter()
examples = collections.defaultdict(list)
for r in rows:
    texts = [x[0] for x in con.execute(
        "SELECT text FROM messages WHERE session_key=? AND role='assistant' ORDER BY seq",
        (r["session_key"],))]
    for t in texts:
        for m in MARKERS:
            if m in t:
                hits[m] += 1
                if len(examples[m]) < 1:
                    i = t.find(m)
                    examples[m].append(t[max(0, i - 60):i + 90].replace("\n", " "))

print("\n标记词命中次数（assistant 正文）：")
for m, n in hits.most_common():
    print("  %-8s %5d   例：%s" % (m, n, examples[m][0][:110] if examples[m] else ""))
con.close()
