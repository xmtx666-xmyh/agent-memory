"""注入块生成：把 42 条判定压成「可粘贴进会话开头的几行环境事实」。

## 为什么必须压缩

40 条 🟡 里一个目录（如 `F:\\demo-wiki`）就占了十几条（不同文件路径）。
按条目逐条注入 = 40 行 ≈ 800+ token，而**真正的信息只有 3 条规则**（旧目录→新目录）。
压缩后约 6 行，信息量不减。

## 注入块的三条纪律

1. **只放可执行的事实**（旧目录→新目录、失效路径），不放观点；
2. **必须带后继的正确路径**（按最近使用排序，实测按字母序会把 `f:\\demo-wiki2` 当前者，误导）；
3. **必须带 check_at**（存在性是检验时刻的函数，注入时可能已变）。
"""
from __future__ import annotations

import collections
import os
import sqlite3
import time

from premises import (DEAD_NO_SUCCESSOR, DEAD_WITH_SUCCESSOR, check_conclusions,
                      project_dir_of)

#: 注入块的稳定前缀（不含 check_at，便于下游按前缀识别/替换）
MARKER = "<!-- agent-memory:auto-generated"

#: 容器目录：不是项目，出现在规则表里是噪音（实测 `c:\users → f:\demo-base` 这种荒谬规则）
_CONTAINERS = {"c:\\users", "c:\\program files", "c:\\programdata", "c:\\windows"}


def _collapse(items, live_dirs: dict[str, list[str]], entity: str):
    """把条目按「旧目录 → 新目录」合并成规则。"""
    rules = collections.defaultdict(lambda: {"n": 0, "paths": [], "resolved": 0,
                                             "unresolved": []})
    live = live_dirs.get(entity) or []
    for it in items:
        for p in it["paths"]:
            old = project_dir_of(p)
            # `c:\users` 这类容器不是项目（实测被当成"已迁移"混进规则表，纯噪音）
            if not old or old in _CONTAINERS:
                continue
            r = rules[old]
            r["n"] += 1
            if p not in r["paths"]:
                r["paths"].append(p)
            # 该路径能否在后继目录里解析出来；**整目录引用（rest 为空）不算解析成功**
            rest = p[len(old):].lstrip("\\")
            if rest and any(os.path.exists(os.path.join(d, rest)) for d in live):
                r["resolved"] += 1
            elif rest:
                if rest not in r["unresolved"]:
                    r["unresolved"].append(rest)

    # 每条规则单独选后继：**谁能真正解析出这些文件，谁就是后继**。
    # 踩过两次坑：① 按字母序选到 f:\demo-wiki2；② 按"最近使用"选到 f:\demo-kb
    # （那是跑采集的这个会话的 cwd，天然最新）。只有"有证据"的才对。
    for old, r in rules.items():
        best, best_score = (live[0] if live else ""), -1
        for d in live:
            score = 0
            for p in r["paths"]:
                rest = p[len(old):].lstrip("\\")
                if rest and os.path.exists(os.path.join(d, rest)):
                    score += 1
            if score > best_score:
                best, best_score = d, score
        r["dir"] = old
        # 一条都解析不出来时不要瞎指：留空，渲染时写"未定位到具体位置"
        r["succ"] = best if best_score > 0 else ""
        r["evidence"] = best_score
    return rules


def _render_dead(items) -> list[str]:
    """「已确认失效」清单：只报**现在真的不存在**的路径。

    ⚠️ 一条结论只要有一个路径没了就会被标 dead，同一句里的**其它路径可能还活着**。
    实测（2026-11-04，平台包干净目录实测）把 `C:\\Users\\demo\\.codex` 折成
    `c:\\users` 写进"勿照做"——而 `C:\\Users` 明明存在，这是主动误导。
    所以：路径本身还存在 → 不提；折出来的项目目录是容器或还存在 → 也不提。
    """
    seen = set()
    out = []
    for it in items:
        for p in it["paths"]:
            if os.path.exists(p):
                continue
            d = project_dir_of(p) or p
            if d in _CONTAINERS or os.path.exists(d) or d in seen:
                continue
            seen.add(d)
            out.append("- `%s` 已不存在（%s 的结论基于它，需重新确认）" % (d, it["when"]))
    return out


def build_injection(db_path: str, entity: str, max_chars: int = 1400) -> dict:
    """生成注入块。返回 {text, stats, rules}。"""
    r = check_conclusions(db_path, entity)
    items = r["items"]
    live = r["live_dirs"]
    check_at = r["check_at"]
    succ = (live.get(entity) or [""])[0]

    migrate = [x for x in items if x["verdict"] == DEAD_WITH_SUCCESSOR]
    dead = [x for x in items if x["verdict"] == DEAD_NO_SUCCESSOR]

    lines = ["%s  check_at=%s -->" % (MARKER, check_at),
             "## 环境事实（agent-memory 自动生成，勿手改；check_at=%s）" % check_at, ""]

    rules = _collapse(migrate, live, entity)
    if rules:
        lines.append("### 目录已改名（历史结论里的旧路径按下表换算）")
        for old, info in sorted(rules.items(), key=lambda kv: -kv[1]["n"]):
            if info.get("succ"):
                hint = ("相对路径多数不变" if info["resolved"] >= info["n"] / 2
                        else "同名文件可能也改名，需确认")
                lines.append("- `%s` → `%s`（%d 条历史结论引用；%s）"
                             % (old, info["succ"], info["n"], hint))
            else:
                # 没有证据说明迁到哪：只报"旧目录没了 + 本项目现存哪些目录"，不瞎指
                lines.append("- `%s` 已不存在（%d 条历史结论引用）；本项目现存目录：%s，"
                             "具体位置需确认"
                             % (old, info["n"],
                                "、".join("`%s`" % d for d in (live.get(entity) or [])[:3])))
            if info["unresolved"]:
                hmm = info["unresolved"][:2]
                lines.append("  - 在新位置没找到：%s" % ", ".join("`%s`" % x for x in hmm))
        lines.append("")

    entries = _render_dead(dead)
    if entries:
        lines.append("### 已确认失效（勿照做）")
        lines.extend(entries)
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    # 超预算时优先砍"新位置没找到"的细节行，保留规则行
    if len(text) > max_chars:
        keep = [ln for ln in lines if not ln.startswith("  - 在新位置没找到")]
        text = "\n".join(keep).rstrip() + "\n"

    return {"text": text, "check_at": check_at,
            "stats": {"migrate_items": len(migrate), "dead_items": len(dead),
                      "rules": len(rules), "chars": len(text),
                      "est_tokens": round(len(text) / 1.6)},
            "rules": {k: v["n"] for k, v in rules.items()}}


def main(argv=None):
    import sys
    argv = argv or sys.argv[1:]
    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index", "sessions.db")
    entity = argv[0] if argv else "demo-kb"
    out = build_injection(db, entity)
    print(out["text"])
    print("--- 统计: %s" % out["stats"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
