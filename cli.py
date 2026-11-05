"""agent-memory CLI：把多个 agent 的会话汇成一份可检索的库。

用法：
    python cli.py ingest [--agent dsh|codex|claude|hermes|all] [--limit N]
    python cli.py search "查询词" [--limit 10] [--trigram] [--peer 仓库名]
    python cli.py peers [--backfill] [--top 20]
    python cli.py stats

设计边界（见 docs/design.md）：
  · 只做「采集 + 索引 + 检索」；话题归并/演变时间线是第二阶段，不在这里。
  · 索引不调用任何 LLM。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 控制台编码兜底：Windows 默认控制台是 GBK(cp936)，打印 ⚠️ 之类字符会抛
# UnicodeEncodeError 把命令**直接打断**（实测 topics 因此在全新机器上失败，
# install.ps1 随之中止）。这里把 stdout/stderr 切成 utf-8 + errors='replace'，
# 不依赖调用方设置 PYTHONIOENCODING。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        pass

from store import QueryError, Store, ingest            # noqa: E402

DEFAULT_DB = None    # 由 paths.DB_FILE 决定（见 main()），避免出现"第二个真相源"

COLLECTORS = {}


def _load_collectors():
    from collectors import claude, codebuddy, codex, dsh, hermes, workbuddy
    COLLECTORS.update({"dsh": dsh, "codex": codex, "claude": claude, "hermes": hermes,
                       "workbuddy": workbuddy, "codebuddy": codebuddy})


def cmd_ingest(args):
    _load_collectors()
    store = Store(args.db)
    agents = list(COLLECTORS) if args.agent == "all" else [args.agent]
    grand = {"added": 0, "skipped": 0, "by_agent": {}, "sec": 0.0}
    for name in agents:
        mod = COLLECTORS[name]
        print("== 采集 %s ==" % name, flush=True)
        t0 = time.perf_counter()
        try:
            res = ingest(store, mod.collect(limit=args.limit), verbose=True)
        except Exception as e:                            # noqa: BLE001
            print("  [%s] 采集失败: %s: %s" % (name, type(e).__name__, e))
            continue
        print("  新增 %d 会话，跳过 %d，耗时 %.1fs"
              % (res["added"], res["skipped"], time.perf_counter() - t0), flush=True)
        grand["added"] += res["added"]
        grand["skipped"] += res["skipped"]
        grand["sec"] += res["sec"]
        for k, v in res["by_agent"].items():
            grand["by_agent"][k] = grand["by_agent"].get(k, 0) + v
    print("\n===== 汇总 =====")
    print("  新增会话 %d ｜ 已存在跳过 %d ｜ 耗时 %.1fs"
          % (grand["added"], grand["skipped"], grand["sec"]))
    # 已存在的会话不会重写：新能力（peer）必须显式补，否则老会话永远没有归属
    from peers import peer_for_cwd
    bf = store.backfill_peers(peer_for_cwd)
    if bf["updated"]:
        print("  补算 peer %d 个（扫描 %d 个空 peer 会话）" % (bf["updated"], bf["scanned"]))
    _print_stats(store.stats())
    store.close()


def cmd_search(args):
    store = Store(args.db)
    t0 = time.perf_counter()
    try:
        rows = store.search(args.query, limit=args.limit, use_trigram=args.trigram,
                            peer=args.peer or "")
    except QueryError as exc:
        store.close()
        # 语法错误 ≠ 没命中：必须让调用方看见（2026-11-04 glm-5.3 复核）
        sys.stderr.write("%s\n" % exc)
        sys.exit(2)
    dt = (time.perf_counter() - t0) * 1000
    via = store.last_search_via or ("trigram" if args.trigram else "fts5")
    print("查询: %r ｜ 命中 %d ｜ %.1f ms ｜ 索引=%s%s"
          % (args.query, len(rows), dt, via,
             (" ｜ peer=%s" % args.peer) if args.peer else ""))
    if store.last_query_relaxed:
        print("  ⚠ 查询含 FTS5 语法字符（`-`/`:`/`.`），已自动按短语处理（不是语法错误）")
    if via == "like":
        print("  ⚠ 索引未命中，已回退 LIKE 全表扫描：1~2 字中文在 trigram 上无法命中"
              "（换成 3 字以上的词才会走索引）")
    elif not rows and not args.trigram:
        print("  提示：中文查询请加 --trigram（unicode61 不切分中文，默认索引查不到中文）")
    for r in rows:
        print("-" * 96)
        print("[%s] %s" % (r["agent"], (r["title"] or "(无标题)")[:60]))
        print("  %s ｜ %s ｜ %s%s"
              % (r["started_at"], r["role"], r["session_key"],
                 (" ｜ peer=%s" % r["peer"]) if r.get("peer") else ""))
        print("  %s" % (r["snippet"] or "").replace("\n", " ")[:300])
    store.close()


def cmd_peers(args):
    """工作区身份（peer）列表与补算：同一仓库的 clone/worktree 共享一个 peer。"""
    store = Store(args.db)
    if args.backfill:
        from peers import peer_for_cwd
        print("== 补算 peer（只补空值；按 cwd 缓存，反复跑幂等）==")
        r = store.backfill_peers(peer_for_cwd)
        print("  扫描 %d 个会话 ｜ 写入 peer %d 个" % (r["scanned"], r["updated"]))
    st = store.stats()["peers"]
    print("\n== peer 覆盖 ==")
    print("  %d 个 peer ｜ 覆盖 %d 个会话" % (st["distinct"], st["sessions"]))
    rows = store.peer_summary(limit=args.top)
    if not rows:
        print("  （空：没有会话落在 git 仓库里，或还没跑 `peers --backfill`）")
    else:
        print("\n== peer TOP（会话数 ｜ 时间跨度 ｜ 代表 cwd）==")
        for r in rows:
            print("  %-44s %4d 会话 ｜ %s → %s"
                  % (r["peer"][:44], r["sessions"],
                     (r["first_at"] or "")[:10], (r["last_at"] or "")[:10]))
            if r["top_cwd"]:
                print("      cwd: %s" % r["top_cwd"])
    store.close()


def cmd_stats(args):
    store = Store(args.db)
    _print_stats(store.stats())
    store.close()


def cmd_doctor(args):
    """环境自检：让"装了但没跑通"一眼可见（借鉴 openviking-server doctor / npm doctor）。

    退出码：0 = 没有阻塞问题（允许 warn）；1 = 有 error（必须处理后才能用）。
    """
    import platform
    import re

    from paths import DB_FILE, HOME

    checks = []

    def add(level, name, detail):
        checks.append((level, name, detail))

    add("OK", "工程目录", HOME)
    py = platform.python_version()
    if sys.version_info >= (3, 10):
        add("OK", "Python", py)
    else:
        add("ERROR", "Python", "%s（需要 3.10+）" % py)
    for mod in ("zstandard", "yaml"):
        try:
            __import__(mod)
            add("OK", "依赖 %s" % mod, "可导入")
        except Exception as exc:                      # noqa: BLE001
            add("ERROR", "依赖 %s" % mod, "导入失败：%s: %s" % (type(exc).__name__, exc))

    db = args.db or DB_FILE
    if not os.path.exists(db):
        add("ERROR", "索引库", "不存在：%s（先跑一次 ingest，约 90 秒）" % db)
    else:
        st = Store(db)
        lib_ver, code_ver = st.schema_version()
        add("OK" if lib_ver == code_ver else "ERROR", "数据 schema",
            "库 v%d / 代码 v%d" % (lib_ver, code_ver))
        stats = st.stats()
        if stats["sessions"]:
            add("OK", "会话 / 消息", "%d / %d" % (stats["sessions"], stats["messages"]))
        else:
            add("ERROR", "会话 / 消息", "0 / 0（索引是空的，先跑 ingest）")
        peers = stats.get("peers") or {}
        add("OK" if peers.get("sessions") else "WARN", "peer 覆盖",
            "%d 个 peer / %d 会话（没有就跑一次 peers --backfill）"
            % (peers.get("distinct", 0), peers.get("sessions", 0)))
        last = st.con.execute("SELECT MAX(indexed_at) FROM sessions").fetchone()[0] or ""
        add("OK" if last else "WARN", "最近入库", last or "（无记录）")
        st.close()

    skill_md = ""
    for cand in (os.path.join(HOME, "SKILL.md"),
                 os.path.join(HOME, "skill", "agent-memory", "SKILL.md")):
        if os.path.isfile(cand):
            skill_md = cand
            break
    if skill_md:
        with open(skill_md, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        m = re.search(r'(?m)^version:\s*"([^"]+)"', txt)
        add("OK", "技能版本", m.group(1) if m else "未标注")
    else:
        add("WARN", "技能版本", "找不到 SKILL.md（git 工程形态下正常）")

    width = max(len(n) for _l, n, _d in checks)
    print("=== agent-memory doctor ===")
    for level, name, detail in checks:
        print("  [%-5s] %-*s  %s" % (level, width, name, detail))
    errors = sum(1 for level, _n, _d in checks if level == "ERROR")
    warns = sum(1 for level, _n, _d in checks if level == "WARN")
    print("\n结果：%d error / %d warn" % (errors, warns))
    return 1 if errors else 0


def cmd_init(args):
    from init_cmd import init
    store = Store(args.db)
    r = init(store, force=args.force)
    print("=== 初始化本机数据 ===")
    print("  实体表: %s（%d 个实体）"
          % ("已生成" if r["entities_created"] else "已存在（未改）", r["entities"]))
    print("  注入目标: %s" % ("已生成" if r["targets_created"] else "已存在（未改）"))
    if r["candidates"]:
        print("  候选项目（按会话数）：")
        for d, n in r["candidates"]:
            print("    %-40s %d 会话" % (d, n))
    store.close()
    print("\n提示：历史改名（旧名→新名）脚本不猜，请手工补到 index/entities.json。")


def cmd_topic(args):
    store = Store(args.db)
    if args.build:
        from topic_build import build
        print("== 构建话题标签 ==", flush=True)
        res = build(store)
        print("  %d 会话 ｜ 有实体 %d ｜ 有意图 %d ｜ 耗时 %.1fs"
              % (res["sessions"], res["with_entity"], res["with_intent"], res["sec"]))
    cov = store.coverage()
    tot = max(1, cov["sessions"])
    print("\n== 标签覆盖 ==")
    print("  会话 %d ｜ 有实体 %d (%.0f%%) ｜ 有意图 %d (%.0f%%)"
          % (cov["sessions"], cov["with_entity"], 100.0 * cov["with_entity"] / tot,
             cov["with_intent"], 100.0 * cov["with_intent"] / tot))
    print("\n== 实体 TOP（会话数 ｜ 首末时间）==")
    tot_s = max(1, cov["sessions"])
    for r in store.topic_summary("entity")[:args.top]:
        flag = "  ⚠️粗" if r["sessions"] > tot_s * 0.5 else ""
        print("  %-26s %4d 会话 (%2.0f%%) ｜ %s → %s%s"
              % (r["label"], r["sessions"], 100.0 * r["sessions"] / tot_s,
                 (r["first_at"] or "")[:10], (r["last_at"] or "")[:10], flag))
    print("\n== 意图 TOP（覆盖率 >25% 标 ⚠️ 说明太粗，需拆分或收紧关键词）==")
    for r in store.topic_summary("intent")[:args.top]:
        pct = 100.0 * r["sessions"] / tot_s
        flag = "  ⚠️粗" if pct > 25 else ""
        print("  %-14s %4d 会话 (%2.0f%%)%s" % (r["label"], r["sessions"], pct, flag))
    print("\n== 话题组合 (实体 × 意图)，会话数 >= %d ==" % args.pairs)
    for r in store.topic_pairs(min_sessions=args.pairs)[:args.top]:
        print("  %-26s × %-14s %3d 会话 ｜ %s → %s"
              % (r["entity"], r["intent"], r["sessions"],
                 (r["first_at"] or "")[:10], (r["last_at"] or "")[:10]))

    if args.entity:
        rows = store.sessions_for(args.entity, args.intent or "")
        print("\n== 时间线：%s%s（%d 个会话，按时间）=="
              % (args.entity, (" × " + args.intent) if args.intent else "", len(rows)))
        for r in rows[:args.top]:
            print("  %s  %-8s %s"
                  % ((r["started_at"] or "")[:10], r["agent"], (r["title"] or "(无标题)")[:60]))
    store.close()


def cmd_timeline(args):
    from timeline import build_timeline, render
    tl = build_timeline(args.db, args.entity, args.intent or "")
    out = render(tl, max_concl=args.per)
    print(out)
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out)
        print("\n已落盘 -> %s" % args.out)


def cmd_premises(args):
    from premises import check_conclusions
    r = check_conclusions(args.db, args.entity, limit=args.limit)
    s = r["stats"]
    print("=== 前提校验：%s ===" % r["entity"])
    print("  会话 %d ｜ 结论 %d ｜ check_at %s"
          % (r["sessions"], s.get("结论总数", 0), r["check_at"]))
    print("  活目录（该实体现存的）: %s" % (r["live_dirs"].get(r["entity"]) or "（无）"))
    print()
    total = max(1, s.get("结论总数", 0))
    for k, label in (("alive", "🟢 前提通过"),
                     ("dead_with_successor", "🟡 项目已迁移（带注，不劝退）"),
                     ("dead_no_successor", "🔴 真失效"),
                     ("unverified", "⚪ 无可验证前提 / 非项目资产")):
        n = s.get(k, 0)
        print("  %-32s %5d (%4.1f%%)" % (label, n, 100.0 * n / total))
    print()
    for verdict, title in (("dead_no_successor", "🔴 真失效清单"),
                           ("dead_with_successor", "🟡 迁移清单（带注，不劝退）")):
        rows = [it for it in r["items"] if it["verdict"] == verdict][:args.top]
        print("=== %s（%d 条，显示前 %d）===" % (title, s.get(verdict, 0), len(rows)))
        for it in rows:
            print("  [%s] %s" % (it["when"], ", ".join(it["paths"])))
            if it["note"]:
                print("     └ %s" % it["note"])
        print()


def cmd_inject(args):
    from inject import build_injection
    r = build_injection(args.db, args.entity, max_chars=args.max_chars)
    print(r["text"])
    st = r["stats"]
    print("--- 统计: 迁移条目 %d → 规则 %d 条 ｜ 失效 %d ｜ %d 字符（约 %d token）"
          % (st["migrate_items"], st["rules"], st["dead_items"],
             st["chars"], st["est_tokens"]))
    if args.write:
        parent = os.path.dirname(os.path.abspath(args.write))
        os.makedirs(parent, exist_ok=True)
        with open(args.write, "w", encoding="utf-8") as fh:
            fh.write(r["text"])
        print("已写入 -> %s" % args.write)


def _print_stats(st):
    print("  会话 %d ｜ 消息 %d" % (st["sessions"], st["messages"]))
    for row in st["by_agent"]:
        print("    %-8s %4d 会话 ｜ %6d 条" % (row["agent"], row["sessions"], row["msgs"] or 0))
    peers = st.get("peers") or {}
    if peers:
        print("  peer：%d 个 ｜ 覆盖 %d 个会话（其余 session 不在 git 仓库里，无 peer）"
              % (peers.get("distinct", 0), peers.get("sessions", 0)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agent-memory", description="多 agent 会话索引")
    ap.add_argument("--db", default=None, help="索引库路径（默认由 paths.DB_FILE 决定）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="采集并写入索引")
    p.add_argument("--agent", default="all",
                   choices=["all", "dsh", "codex", "claude", "hermes",
                            "workbuddy", "codebuddy"])
    p.add_argument("--limit", type=int, default=0, help="每个来源只取前 N 个会话（调试）")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("search", help="检索")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--trigram", action="store_true", help="用 trigram 索引（中文短语更准）")
    p.add_argument("--peer", default="",
                   help="只检索该工作区身份（git origin 派生，子串匹配，如 demo-base）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("peers", help="工作区身份（peer）列表 / 补算")
    p.add_argument("--backfill", action="store_true", help="给空 peer 的已入库会话补算（幂等）")
    p.add_argument("--top", type=int, default=20, help="显示前 N 个 peer")
    p.set_defaults(func=cmd_peers)

    p = sub.add_parser("stats", help="索引统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("doctor", help="环境自检（依赖 / 索引 / schema 版本 / 数据新鲜度）")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("topics", help="话题归并（实体 × 意图）")
    p.add_argument("--build", action="store_true", help="重算全部会话的标签（幂等）")
    p.add_argument("--pairs", type=int, default=2, help="组合视图的最小会话数")
    p.add_argument("--top", type=int, default=15, help="每节显示前 N 条")
    p.add_argument("--entity", default="", help="列出该实体下的会话时间线")
    p.add_argument("--intent", default="", help="配合 --entity 限定意图")
    p.set_defaults(func=cmd_topic)

    p = sub.add_parser("init", help="首次安装/换机：生成本机实体表与注入目标")
    p.add_argument("--force", action="store_true", help="覆盖重建（会丢手工加的别名）")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("timeline", help="演变时间线（某话题的结论按时间排 + 冲突）")
    p.add_argument("entity", help="实体名，如 demo-kb / PageIndex")
    p.add_argument("intent", nargs="?", default="", help="可选：意图标签")
    p.add_argument("--per", type=int, default=3, help="每会话最多显示几条结论")
    p.add_argument("--out", default="", help="落盘路径（markdown）")
    p.set_defaults(func=cmd_timeline)

    p = sub.add_parser("premises", help="前提校验（三路判定：活 / 迁移 / 真失效）")
    p.add_argument("entity", help="实体名，如 demo-kb")
    p.add_argument("--limit", type=int, default=0, help="只查前 N 个会话")
    p.add_argument("--top", type=int, default=10, help="每类显示前 N 条")
    p.set_defaults(func=cmd_premises)

    p = sub.add_parser("inject", help="生成可粘贴进会话开头的「环境事实」块")
    p.add_argument("entity", help="实体名，如 demo-kb")
    p.add_argument("--max-chars", type=int, default=1400, help="字符预算（默认约 500 token）")
    p.add_argument("--write", default="", help="写入文件（如 .agent-memory/context.md）")
    p.set_defaults(func=cmd_inject)

    args = ap.parse_args(argv)
    # 索引库路径统一由 paths.DB_FILE 决定（env 优先），消除"两个真相源"：
    # 否则 AGENT_MEMORY_HOME 指向别处时，库写在代码目录而词典读 env 目录，实体表与库分家。
    if not getattr(args, "db", None):
        try:
            from paths import DB_FILE
            args.db = DB_FILE
        except Exception:                                  # noqa: BLE001
            args.db = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "index", "sessions.db")
    # 实体同义词表来自数据文件（每台机器不同），启动时载入；缺文件则退化为"目录名即实体"
    try:
        from topics import load_entities
        load_entities()
    except Exception:                                      # noqa: BLE001
        pass
    # doctor 等命令返回退出码；其余命令返回 None（视为 0）
    _rc = args.func(args)
    sys.exit(0 if _rc is None else _rc)


if __name__ == "__main__":
    main()
