"""演变时间线（第二阶段 B）：把某个「实体 × 意图」话题下的会话按时间排开，
从每个会话里抽出**结论句**，并标出状态与跨会话冲突。

## 为什么不接 LLM

1. LLM 摘要无法复核，容易产出"看起来对"的结论——本仓纪律要求可复盘；
2. 先用规则把**结论句定位**做出来（这一步只需匹配），人工/后续 LLM 只在候选上判断，
   候选错了能一眼看出。

## 抽取规则（基于实测标记词分布，见 tools/probe_conclusion_markers.py）

只认两类：
  A. **标题锚定**：行首带 `结论 / 决定 / 根因 / 最终 / 已验证 / 已修复 / 定稿` 的段落；
  B. **强决策短语**：`改为 / 改成 / 改用 / 不再用 / 废弃 / 回退到 / 验证通过 / 实测 / 判定为`。
不认 `修复`（实测 251 次命中里绝大多数是「Bug 修复」这类菜单项）与 `确认`（多为动作过程）。

## 状态判定

  superseded_candidate  含 废弃/不再用/回退/推翻/作废 —— 可能推翻前面的结论
  experiment            含 实验/试验/临时/A-B —— 试验性，不应被当成现状
  verified              含 实测/验证通过 —— 有实测支撑
  decision              其余（默认）
"""
from __future__ import annotations

import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: 项目根 = 本文件所在目录（timeline.py 在根目录，不是 tools/ 下，别再 dirname 一次）
ROOT = os.path.dirname(os.path.abspath(__file__))

#: 标题锚定词：出现在行首（可带 #、*、- 前缀）才算
_HEAD_WORDS = ("结论", "决定", "根因", "最终", "已验证", "已修复", "定稿", "定案",
               "结论是", "判定")
#: 强决策短语：出现在行内即算
_DECISION_RE = re.compile(
    r"(改为|改成|改用|不再用|已废弃|废弃|回退到|回退成|验证通过|实测|判定为|"
    r"从.+?换成|替换为)")
_HEAD_RE = re.compile(r"^[\s#>*\-]*(?:%s)" % "|".join(_HEAD_WORDS))

_STATUS_RULES = (
    # ⚠️ 别把裸「回退」算成推翻决定：实测代码语境里「回退到 PyMuPDF」是**降级路径**，
    # 不是"推翻上个决定"。只认明确的撤销措辞。
    ("superseded_candidate", re.compile(r"废弃|不再用|推翻|作废|改回|回退到旧|恢复旧|弃用")),
    ("experiment", re.compile(r"实验|试验|临时方案|A/B|对比一下|先这样")),
    ("verified", re.compile(r"实测|验证通过|已验|跑通")),
)

#: 数值/取值冲突：`默认候选数 = 60` / `端口: 11434`
_PAIR_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9_\- ]{1,14}?)\s*"
    r"(?:=|:|：|为|是|改为|设为)\s*"
    r"(\d+(?:\.\d+)?\s*(?:万?元|个日历日|日历日|工作日|天|小时|分钟|秒|%|分|年|个月|周)?)")

#: 键黑名单：实测这些"键"全是噪音，导致 40 个不同 `py` 值被当成冲突
_KEY_STOPWORDS = {
    "结论", "最终", "建议", "根因", "结果", "以上", "下面", "总计", "合计", "共",
    "第", "行", "页", "版本", "时间", "日期", "数量", "比例", "说明", "注意",
    "py", "md", "txt", "json", "yaml", "yml", "js", "ts", "html", "csv", "db",
    "line", "line 号", "行号",
}
#: 参数味儿的键：只有出现这些词才认为"可比的参数"（否则 `结论 14.2` 这种也会进冲突）
_PARAM_HINTS = ("候选", "端口", "超时", "阈值", "并发", "预算", "金额", "分数", "得分",
                "长度", "大小", "条数", "数量", "比例", "率", "窗口", "上限", "下限",
                "chunk", "token", "默认", "版本", "天数", "工期")
#: 带这些单位的数值本身就够具体（`预算 927800 元`）
_UNIT_RE = re.compile(r"(万?元|元|个日历日|日历日|工作日|天|小时|分钟|秒|%|分|年|个月|周)$")


def _valid_key(key: str) -> bool:
    k = re.sub(r"\s+", "", key)
    if not (2 <= len(k) <= 12):
        return False
    if k.lower() in _KEY_STOPWORDS:
        return False
    if re.fullmatch(r"[A-Za-z]{1,4}", k):        # py / md / txt 这类文件后缀
        return False
    if re.fullmatch(r"[\d.]+", k):
        return False
    return True


def extract_pairs(conclusions) -> list[tuple[str, str, str]]:
    """从结论句里抽 (键, 值, ts) —— 用于跨会话冲突检测。

    只保留**可比的参数**（键像参数名，或值带单位）。实测不做这两道过滤时，
    冲突列表会把 40 个 `py:行号` 当成冲突、把 ollama/streamlit/chroma 全塞进
    一个「技术选型」键 —— 完全不可用。
    """
    out = []
    for c in conclusions:
        t = c["text"]
        for m in _PAIR_RE.finditer(t):
            raw_key = m.group(1)
            key = re.sub(r"\s+", "", raw_key)[-12:]
            val = re.sub(r"\s+", "", m.group(2))
            if not _valid_key(key):
                continue
            has_param = any(h in key.lower() for h in _PARAM_HINTS)
            if not has_param and not _UNIT_RE.search(val):
                continue
            out.append((key, val, c["ts"]))
    return out


def _sentences(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过表格行（实测表格里的"改为/结论"多是字段名，不是决策）与代码块围栏
        if line.count("|") >= 2 or line.startswith("```"):
            continue
        # 剥掉 markdown 前缀（`> **结论：` / `- 结论：` / `### 结论`）
        line = re.sub(r"^[#>\-*+\s]+", "", line)
        line = line.replace("**", "").strip()
        if len(line) < 12:
            continue
        for s in re.split(r"(?<=[。！？])", line):
            s = re.sub(r"^[#>\-*+\s]+", "", s).strip(" \t")
            if 12 <= len(s) <= 220:
                yield s


def extract_conclusions(messages) -> list[dict]:
    """从 [(role, ts, text)] 里抽结论句。返回 [{text, ts, status, why}]。"""
    out, seen = [], set()
    for role, ts, text in messages:
        if role != "assistant":          # 结论主要由 agent 给出；user 的是指令
            continue
        for s in _sentences(text):
            is_head = bool(_HEAD_RE.match(s))
            m = _DECISION_RE.search(s)
            if not (is_head or m):
                continue
            key = s[:60]
            if key in seen:
                continue
            seen.add(key)
            status = "decision"
            for label, rx in _STATUS_RULES:
                if rx.search(s):
                    status = label
                    break
            out.append({"text": s, "ts": ts or "", "status": status,
                        "why": "title" if is_head else (m.group(1) if m else "")})
    return out


def find_conflicts(pairs) -> list[dict]:
    """同一话题内，同一键出现多个不同值 → 冲突（后者可能是推翻前者）。"""
    by_key = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, val, ts in pairs:
        by_key[key][val].append(ts)
    conflicts = []
    for key, vals in by_key.items():
        if len(vals) < 2:
            continue
        conflicts.append({
            "key": key,
            "values": {v: sorted(t for t in ts if t) for v, ts in vals.items()},
        })
    return conflicts


def build_timeline(db_path: str, entity: str, intent: str = "",
                   limit: int = 200) -> dict:
    """取该话题下所有会话（按时间），逐会话抽结论。"""
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    if intent:
        rows = list(con.execute("""
        SELECT s.session_key, s.agent, s.title, s.started_at
        FROM sessions s
        JOIN session_topics e ON e.session_key=s.session_key AND e.kind='entity' AND e.label=?
        JOIN session_topics i ON i.session_key=s.session_key AND i.kind='intent' AND i.label=?
        ORDER BY s.started_at LIMIT ?""", (entity, intent, limit)))
    else:
        rows = list(con.execute("""
        SELECT s.session_key, s.agent, s.title, s.started_at
        FROM sessions s
        JOIN session_topics e ON e.session_key=s.session_key AND e.kind='entity' AND e.label=?
        ORDER BY s.started_at LIMIT ?""", (entity, limit)))

    entries, all_pairs = [], []
    for r in rows:
        msgs = [(x["role"], x["ts"], x["text"]) for x in con.execute(
            "SELECT role, ts, text FROM messages WHERE session_key=? ORDER BY seq",
            (r["session_key"],))]
        cons = extract_conclusions(msgs)
        pairs = extract_pairs(cons)
        all_pairs.extend(pairs)
        if cons:
            entries.append({"session_key": r["session_key"], "agent": r["agent"],
                            "title": r["title"], "started_at": r["started_at"],
                            "conclusions": cons})
    con.close()
    return {"entity": entity, "intent": intent, "sessions": len(rows),
            "with_conclusions": len(entries), "entries": entries,
            "conflicts": find_conflicts(all_pairs)}


def render(tl: dict, max_concl: int = 3) -> str:
    lines = ["# 演变时间线：%s%s" % (tl["entity"],
                                    (" × " + tl["intent"]) if tl["intent"] else ""), "",
             "- 会话 %d 个 ｜ 抽到结论 %d 个" % (tl["sessions"], tl["with_conclusions"]),
             "- 时间跨度：%s → %s"
             % ((tl["entries"][0]["started_at"] or "")[:10] if tl["entries"] else "-",
                (tl["entries"][-1]["started_at"] or "")[:10] if tl["entries"] else "-"),
             ""]
    for e in tl["entries"]:
        lines.append("## %s ｜ %s ｜ %s" % ((e["started_at"] or "")[:10], e["agent"],
                                            (e["title"] or "(无标题)")[:52]))
        for c in e["conclusions"][:max_concl]:
            lines.append("- `%s` %s" % (c["status"], c["text"]))
        lines.append("")
    if tl["conflicts"]:
        lines.append("## ⚠️ 跨会话冲突（同一键出现不同值）")
        for c in tl["conflicts"]:
            vals = "；".join("%s（%s）" % (v, ",".join(t[:10] for t in ts if t) or "?")
                             for v, ts in c["values"].items())
            lines.append("- **%s**：%s" % (c["key"], vals))
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    argv = argv or sys.argv[1:]
    db = os.path.join(ROOT, "index", "sessions.db")
    entity = argv[0] if argv else "demo-kb"
    intent = argv[1] if len(argv) > 1 else "检索与排序"
    tl = build_timeline(db, entity, intent)
    out = render(tl)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
