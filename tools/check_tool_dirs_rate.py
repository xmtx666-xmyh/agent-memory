"""统计三个采集器的 tool_dirs 命中率与 top 目录（验证路径索引真的有用）。"""
import collections
import sys

sys.path.insert(0, r"F:\agent-memory")

from collectors import claude, codex, dsh, hermes   # noqa: E402

for name, mod, limit in (("dsh", dsh, 40), ("codex", codex, 20),
                         ("claude", claude, 40)):
    n = with_dirs = 0
    agg = collections.Counter()
    samples = []
    for res in mod.collect(limit=limit):
        n += 1
        if res.tool_dirs:
            with_dirs += 1
            for d, c in res.tool_dirs:
                agg[d] += c
            if len(samples) < 3:
                samples.append((res.meta.session_id[:12], res.tool_dirs[:2]))
    print("=" * 92)
    print("[%s] 抽样 %d 个会话 ｜ 有工具路径 %d (%.0f%%)" % (name, n, with_dirs, 100.0 * with_dirs / max(1, n)))
    for sid, dirs in samples:
        print("   %s → %s" % (sid, dirs))
    print("   top 目录:")
    for d, c in agg.most_common(6):
        print("     %-44s %d 次" % (d, c))
