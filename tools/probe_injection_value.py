"""证伪实验（B）：注入「迁移提示」到底有没有价值？

两个可机的判据，都不需要跑 agent、不花钱：

① **重复踩坑率**：同一个幽灵路径被多少个**不同会话**引用过？跨多少天？
   若只有 1 个会话提过一次 → 后来者本来就没重复踩，注入价值低。
   若被多会话反复提 → 说明"不知道已迁移"是真实成本。

② **迁移可解析率**：🟡 说"已迁移至 X"，把原路径的后半段接到 X 下，**X 里真有这个文件吗**？
   解析得通 → 注入"去 X 找"直接有用；
   解析不通（文件也改名了）→ 注入"迁移至 X"反而会让 agent 在 X 里白找，属**误导**。
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, r"F:\agent-memory")

from premises import (DEAD_NO_SUCCESSOR, DEAD_WITH_SUCCESSOR, check_conclusions,
                      live_dirs_by_entity, project_dir_of)   # noqa: E402

DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
ENTITY = sys.argv[1] if len(sys.argv) > 1 else "demo-kb"

r = check_conclusions(DB, ENTITY)
live = live_dirs_by_entity(DB)
items = [it for it in r["items"]
         if it["verdict"] in (DEAD_WITH_SUCCESSOR, DEAD_NO_SUCCESSOR)]
print("待验证的失效/迁移条目: %d（🟡%d ｜ 🔴%d）"
      % (len(items),
         sum(1 for x in items if x["verdict"] == DEAD_WITH_SUCCESSOR),
         sum(1 for x in items if x["verdict"] == DEAD_NO_SUCCESSOR)))

con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
con.row_factory = sqlite3.Row

rows = []
for it in items:
    for p in it["paths"]:
        pdir = project_dir_of(p)
        # ① 该路径被多少个不同会话引用过（在结论句里）
        sid = con.execute("""
            SELECT COUNT(DISTINCT session_key) FROM messages
            WHERE LOWER(text) LIKE ?""", ("%" + p.lower() + "%",)).fetchone()[0]
        # ② 迁移可解析：把后半段接到新目录下试
        rest = p[len(pdir):].lstrip("\\")
        resolved = ""
        for d in live.get(ENTITY, []):
            cand = os.path.join(d, rest)
            if os.path.exists(cand):
                resolved = cand
                break
        rows.append({"path": p, "verdict": it["verdict"], "sessions": sid,
                     "rest": rest, "resolved": resolved, "when": it["when"]})

print()
print("%-52s %-4s %-5s %s" % ("幽灵路径", "判定", "会话", "迁移后可解析"))
print("-" * 108)
resolvable = 0
repeat = 0
for x in rows:
    mark = "🟡" if x["verdict"] == DEAD_WITH_SUCCESSOR else "🔴"
    rs = ("✅ " + x["resolved"][:34]) if x["resolved"] else "❌ 也找不到"
    if x["resolved"]:
        resolvable += 1
    if x["sessions"] >= 2:
        repeat += 1
    print("%-52s %-4s %-5d %s" % (x["path"][:52], mark, x["sessions"], rs))

print()
print("=== 两个判据 ===")
print("  ① 被 ≥2 个会话引用的幽灵路径：%d / %d（%.0f%%）"
      % (repeat, len(rows), 100.0 * repeat / max(1, len(rows))))
print("  ② 迁移后可解析（注入'去 X 找'真能用）：%d / %d（%.0f%%）"
      % (resolvable, len(rows), 100.0 * resolvable / max(1, len(rows))))
con.close()
