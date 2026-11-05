"""构建话题标签：给每个会话打「实体 × 意图」（第二阶段 A）。

用法：
    python cli.py topics --build        # 重算全部会话的标签（幂等）
    python cli.py topics                # 看聚合结果
    python cli.py topics --pairs 3      # 只看 >=3 个会话的 (实体×意图) 组合
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import Store                                       # noqa: E402
from topics import label_session_scored                       # noqa: E402


def build(store: Store, verbose: bool = True) -> dict:
    """遍历所有会话，用其消息正文打标签并写库（标签带命中次数，供排序）。"""
    keys = [r[0] for r in store.con.execute("SELECT session_key FROM sessions")]
    t0 = time.perf_counter()
    n_ent = n_itn = 0
    for key in keys:
        texts = [r[0] for r in store.con.execute(
            "SELECT text FROM messages WHERE session_key=? ORDER BY seq", (key,))]
        dirs = store.paths_for(key)                  # 工具路径 = 实体归属的硬信号
        ents, intents = label_session_scored(texts, dirs)
        store.set_topics(key, ents, intents)
        n_ent += bool(ents)
        n_itn += bool(intents)
    store.con.commit()
    return {"sessions": len(keys), "with_entity": n_ent, "with_intent": n_itn,
            "sec": round(time.perf_counter() - t0, 1)}
