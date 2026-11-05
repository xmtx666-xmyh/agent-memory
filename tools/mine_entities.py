"""从已入库的会话里挖"实体候选"：路径名 + 业务项目名，统计会话数与消息数。

目的：让实体词典**基于真实数据**，而不是我拍脑袋列几个名字。
判据：一个候选在多少个**不同会话**里出现过（会话数是话题广度的可靠度量，
消息数会被个别长会话带偏）。
"""
import collections
import os
import re
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "index", "sessions.db")

# ① 路径型实体：F:\xxx、C:\Users\...\xxx、D:\xxx
PATH_RE = re.compile(r"\b[FCDE]:\\\\(?:[^\\\\\s\"'`<>|:*?\n]{1,40}\\\\)*([A-Za-z0-9_\u4e00-\u9fa5.-]{2,40})")
# ② 已知业务项目（demo-base 金标题库里的项目名，作为种子）
BIZ_SEEDS = ["示例街道A", "示例客户B", "示例客户C", "示例客户D", "示例客户E", "DEMO2021", "示例客户F", "示例客户G",
             "示例客户H", "示例客户I", "示例客户J", "示例园区"]
# ③ 系统/仓库型关键词（可能以裸名出现，不一定带路径）
SYS_SEEDS = ["demo-base", "demo-wiki", "demo-next", "demo-wiki2", "demo-kb", "hermes",
             "demo-shield", "dsh", "codex", "workbuddy", "codebuddy", "pageindex",
             "ollama", "llama-server"]


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    rows = list(con.execute("SELECT session_key, agent, text FROM messages"))
    con.close()
    print("扫描 %d 条消息" % len(rows))

    sess_paths = collections.defaultdict(set)     # 候选 -> {session_key}
    msg_paths = collections.Counter()
    for sk, _agent, text in rows:
        for m in PATH_RE.finditer(text or ""):
            name = m.group(1).rstrip(".")
            if len(name) < 2:
                continue
            sess_paths[name].add(sk)
            msg_paths[name] += 1

    print()
    print("=== 路径型候选（按出现的会话数排序，前 25）===")
    for name, sks in sorted(sess_paths.items(), key=lambda kv: -len(kv[1]))[:25]:
        print("  %-34s %4d 会话 ｜ %5d 条消息" % (name, len(sks), msg_paths[name]))

    print()
    print("=== 种子命中（业务项目 + 系统名）===")
    low = [(sk, (text or "").lower()) for sk, _a, text in rows]
    for seed in BIZ_SEEDS + SYS_SEEDS:
        s = seed.lower()
        hits = {sk for sk, t in low if s in t}
        print("  %-16s %4d 会话" % (seed, len(hits)))


if __name__ == "__main__":
    main()
