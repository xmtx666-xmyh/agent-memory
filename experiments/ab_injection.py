"""A/B 实验：注入「迁移提示」能否让 agent 少走弯路、少烧 token？

## 实验设计

**同一个任务**：找到 `server/api/wiki.py` 并回答"该文件用什么创建路由对象"（真值 `router = APIRouter()`）。

| 组 | 提示差异 |
|---|---|
| 基线 | 只给"上次结论说文件在 `F:\\demo-wiki\\server\\api\\wiki.py`"（**该目录已不存在**） |
| 注入 | 同上 + agent-memory 生成的「环境事实」块（把旧目录换算成 `f:\\demo-base`） |

**测量**：步数（工具调用次数）、累计 prompt 字符（≈ token）、
首次工具调用是否失败、是否找到文件、答案是否正确。

## 为什么自建 loop 而不用现成 agent

要精确测"步数 / prompt token"，且实验必须可重复、免费。
本地 qwen3.5:9b + 简单 JSON 动作协议（比原生 tool call 可靠）。

⚠️ 必须 `think=false`：实测 qwen3.5:9b 默认开 thinking 时，200 token 全被思考吃掉、
`response` 为空 → 答案全错（见 tools/bench_local_llm2.py）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen3.5:9b"
OLD_ROOT = "F:\\demo-wiki"
NEW_ROOT = "F:\\demo-base"
REL = "server\\api\\wiki.py"
MAX_STEPS = 8

SYSTEM = """你是一个编码 agent。只能输出**一行 JSON**，描述你的下一个动作，不要解释。
可用动作：
{"action":"list","path":"目录绝对路径"}
{"action":"read","path":"文件绝对路径"}
{"action":"grep","path":"文件或目录","pattern":"正则"}
{"action":"answer","text":"最终答案"}
规则：找到并读过目标文件后才能 answer。"""

TASK = """任务：找到项目里的 `{rel}` 文件，读它，然后回答：
「该文件用什么创建路由对象？请写出那一行代码。」

背景（上次会话留下的结论，可能已过时）：
- 该文件位于 `{old}\\{rel}`"""

#: 对照组 C：直接给**正确**路径（不含迁移块）。
#: 没有它就无法区分「基线失败是因为旧路径」还是「9B 本来就干不成」。
TASK_FRESH = """任务：找到项目里的 `{rel}` 文件，读它，然后回答：
「该文件用什么创建路由对象？请写出那一行代码。」

背景（当前事实）：
- 该文件位于 `{new}\\{rel}`"""

INJECT = """
## 环境事实（agent-memory 自动生成）
### 目录已改名（历史结论里的旧路径按下表换算）
- `f:\\demo-wiki` → `f:\\demo-base`（相对路径多数不变）
"""


# ── 工具实现（真实文件系统，只读） ──────────────────────────────────────
def _safe(p: str) -> str:
    return (p or "").replace("/", "\\").strip()


def do_action(act: dict) -> str:
    a = (act.get("action") or "").lower()
    if a == "list":
        p = _safe(act.get("path"))
        if not os.path.isdir(p):
            return "ERROR: 目录不存在: %s" % p
        items = sorted(os.listdir(p))[:40]
        return "OK: " + ", ".join(items)
    if a == "read":
        p = _safe(act.get("path"))
        if not os.path.isfile(p):
            return "ERROR: 文件不存在: %s" % p
        with open(p, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
        return "OK: 内容前 4000 字\n" + head
    if a == "grep":
        p, pat = _safe(act.get("path")), act.get("pattern") or ""
        if not os.path.exists(p):
            return "ERROR: 路径不存在: %s" % p
        try:
            rx = re.compile(pat, re.I)
        except re.error as e:
            return "ERROR: 正则错误 %s" % e
        files = []
        if os.path.isfile(p):
            files = [p]
        else:
            for root, _d, fs in os.walk(p):
                for f in fs:
                    if f.endswith((".py", ".md", ".txt", ".json", ".yml", ".yaml")):
                        files.append(os.path.join(root, f))
                if len(files) > 400:
                    break
        hits = []
        for fp in files[:400]:
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append("%s:%d: %s" % (fp, i, line.strip()[:120]))
                            if len(hits) >= 20:
                                break
            except OSError:
                continue
            if len(hits) >= 20:
                break
        return ("OK: 命中 %d\n" % len(hits)) + "\n".join(hits) if hits else "OK: 无命中"
    return "ERROR: 未知 action %r" % a


# ── 模型调用 ─────────────────────────────────────────────────────────────
def ask(prompt: str, num_predict: int = 200) -> str:
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "options": {"temperature": 0, "num_predict": num_predict},
    }).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return (json.loads(r.read()).get("response") or "").strip()


def parse_action(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"action": "answer", "text": text[:200]}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {"action": "answer", "text": text[:200]}
    except json.JSONDecodeError:
        return {"action": "answer", "text": text[:200]}


def run_once(arm: str) -> dict:
    """arm: 'base'（旧路径）/ 'inject'（旧路径+迁移块）/ 'fresh'（直接给新路径）。"""
    if arm == "fresh":
        task = TASK_FRESH.format(rel=REL, new=NEW_ROOT)
    else:
        task = TASK.format(rel=REL, old=OLD_ROOT)
        if arm == "inject":
            task += "\n" + INJECT
    convo = "SYSTEM:\n%s\n\nUSER:\n%s\n" % (SYSTEM, task)
    steps = 0
    prompt_chars = 0
    first_failed = False
    found = False
    answer = ""
    trace = []
    t0 = time.perf_counter()
    for _ in range(MAX_STEPS):
        prompt_chars += len(convo)
        out = ask(convo)
        act = parse_action(out)
        steps += 1
        if act.get("action") == "answer":
            answer = str(act.get("text") or "")
            trace.append({"step": steps, "action": "answer", "text": answer[:160]})
            break
        result = do_action(act)
        trace.append({"step": steps, "action": act.get("action"),
                      "path": str(act.get("path") or "")[:90],
                      "ok": result.startswith("OK"),
                      "result_head": result[:100]})
        if steps == 1 and result.startswith("ERROR"):
            first_failed = True
        if result.startswith("OK") and NEW_ROOT.lower() in str(act.get("path", "")).lower() \
                and REL.replace("\\", "/").split("/")[-1] in str(act.get("path", "")).lower():
            found = True
        convo += "\nASSISTANT:\n%s\n\nTOOL_RESULT:\n%s\n" % (out, result[:1500])
    return {"arm": arm, "inject": arm == "inject", "steps": steps,
            "prompt_chars": prompt_chars, "est_tokens": round(prompt_chars / 1.6),
            "first_call_failed": first_failed, "found_file": found,
            "correct": "APIRouter" in answer, "answer": answer[:120],
            "sec": round(time.perf_counter() - t0, 1), "trace": trace}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default="experiments/ab_result.json")
    a = ap.parse_args()
    rows = []
    for i in range(a.reps):
        for arm in ("base", "inject", "fresh"):
            r = run_once(arm)
            rows.append(r)
            print("[rep%d %-6s] 步数=%d ｜ prompt %d 字符(≈%d tok) ｜ 首调失败=%s ｜ 找到=%s ｜ 正确=%s ｜ %.0fs"
                  % (i + 1, arm, r["steps"], r["prompt_chars"], r["est_tokens"],
                     r["first_call_failed"], r["found_file"], r["correct"], r["sec"]),
                  flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print("\n已落盘 -> %s" % a.out)

    # 汇总（中位数）
    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0
    for arm in ("base", "inject", "fresh"):
        g = [r for r in rows if r["arm"] == arm]
        print("%-6s 步数中位 %s ｜ tok 中位 %s ｜ 首调失败 %d/%d ｜ 找到 %d/%d ｜ 正确 %d/%d"
              % (arm,
                 med([r["steps"] for r in g]), med([r["est_tokens"] for r in g]),
                 sum(r["first_call_failed"] for r in g), len(g),
                 sum(r["found_file"] for r in g), len(g),
                 sum(r["correct"] for r in g), len(g)))


if __name__ == "__main__":
    main()
