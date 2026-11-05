"""实测：本地模型关掉 thinking 后，在"窄任务"（同决策判定 + 写一句原因）上够不够用。

背景：首次测速时 qwen3.5:9b / qwen3:8b 的回答都是空字符串 —— num_predict=80 全被
thinking 吃掉（thinking 模型默认先思考）。这会静默浪费 token，也会让"本地可用"的结论失真。

本脚本对比 thinking 开/关，并给出对窄任务的实际答案质量。
"""
import json
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

CASES = [
    ("同一决策", "默认候选数从 60 改为 15，实测金标送达率不降反升。",
     "精排取前 15 条候选就够了，60 条是浪费。"),
    ("不同决策", "分块策略改为 150-300 token/chunk。",
     "把 L2 精排的候选数从 60 降到 15。"),
]

PROMPT_TMPL = ("判断下面两条结论是否在讨论同一个技术决策。\nA: {a}\nB: {b}\n"
               "只回答一行：`同一决策` 或 `不同决策`。")


def gen(model, prompt, think=None, num_predict=200, timeout=180):
    opts = {"temperature": 0, "num_predict": num_predict}
    body = {"model": model, "prompt": prompt, "stream": False, "options": opts}
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(OLLAMA + "/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return {"text": (d.get("response") or "").strip(),
            "think": (d.get("thinking") or ""),
            "n_out": d.get("eval_count") or 0,
            "tok_s": (d.get("eval_count") or 0) / ((d.get("eval_duration") or 1) / 1e9),
            "wall": time.perf_counter() - t0}


MODEL = "qwen3.5:9b"
for think in (None, False):
    print("=" * 92)
    print("[%s] think=%s" % (MODEL, think))
    for want, a, b in CASES:
        p = PROMPT_TMPL.format(a=a, b=b)
        try:
            r = gen(MODEL, p, think=think)
        except Exception as e:                             # noqa: BLE001
            print("   %-8s 失败 %s: %s" % (want, type(e).__name__, e))
            continue
        ans = r["text"].replace("\n", " ")[:60]
        ok = ("同一" in ans and want == "同一决策") or ("不同" in ans and want == "不同决策")
        print("   期望=%-6s 得到=%-58r %s ｜ %2d tok %.0f tok/s"
              % (want, ans, "OK" if ok else "WRONG", r["n_out"], r["tok_s"]))
        if r["think"]:
            print("      ⚠️ thinking 占 %d 字符（吃 token 的主因）" % len(r["think"]))
