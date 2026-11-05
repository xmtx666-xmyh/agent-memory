"""实测本机 Ollama 的吞吐与显存占用（判断本地模型够不够用）。

同时测两个模型：qwen3.5:9b（今天 eval 用的）与 qwen3:8b（更省内存的备选）。
输出：加载后是否全上 GPU、首 token 延迟、生成 tok/s。
"""
import json
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
PROMPT = ("请用一句话判断：下面两条结论是否在讨论同一个技术决策？"
          "A: 默认候选数从 60 改为 15，实测金标送达率不降反升。"
          "B: 精排取前 15 条候选就够了，60 条是浪费。"
          "只回答「同一决策」或「不同决策」，不要解释。")


def gen(model, prompt, timeout=180):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "num_predict": 80}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    wall = time.perf_counter() - t0
    n_out = d.get("eval_count") or 0
    eval_ns = d.get("eval_duration") or 1
    load_ns = d.get("load_duration") or 0
    return {"text": (d.get("response") or "").strip()[:80], "wall": wall,
            "load_s": load_ns / 1e9, "tok_s": n_out / (eval_ns / 1e9) if eval_ns else 0,
            "n_out": n_out}


def ps():
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=30) as r:
        d = json.loads(r.read())
    out = []
    for m in d.get("models") or []:
        total = m.get("size") or 1
        vram = m.get("size_vram") or 0
        out.append((m.get("name"), total / 1e9, 100.0 * vram / total,
                    m.get("context_length")))
    return out


for model in ("qwen3.5:9b", "qwen3:8b"):
    print("=" * 90)
    print("[%s] 首次调用（含加载）" % model)
    try:
        r = gen(model, PROMPT)
        print("   回答: %r" % r["text"])
        print("   加载 %.1fs ｜ 生成 %d tokens ｜ %.1f tok/s ｜ 墙钟 %.1fs"
              % (r["load_s"], r["n_out"], r["tok_s"], r["wall"]))
    except Exception as e:                                  # noqa: BLE001
        print("   失败: %s: %s" % (type(e).__name__, e))
        continue
    for name, total_gb, vram_pct, ctx in ps():
        print("   已加载: %-16s 体积 %.1fGB ｜ VRAM 占比 %.0f%% ｜ ctx %s"
              % (name, total_gb, vram_pct, ctx))
    print("   第二次调用（已加载，测纯生成速度）")
    r2 = gen(model, PROMPT)
    print("   生成 %d tokens ｜ %.1f tok/s ｜ 墙钟 %.1fs"
          % (r2["n_out"], r2["tok_s"], r2["wall"]))
