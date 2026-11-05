"""查证：那 177 个"碰过 f:\\demo-wiki"的会话，工具调用**到底在做什么**？

若多数是 `query`/`pattern`/`prompt` 里提到旧路径（而不是 file_path 指向它），
说明我的路径抽取把「提到」当成了「操作」——这影响两处：
  ① 前提校验的"真失效"判据
  ② 实体归属的"碰过哪些文件"语义
"""
import collections
import glob
import io
import json
import os
import sqlite3
import sys

import zstandard

sys.path.insert(0, r"F:\agent-memory")

from collectors.base import path_dirs_from_args   # noqa: E402

HOME = os.path.expanduser("~")
DB = os.path.join(r"F:\agent-memory", "index", "sessions.db")
con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)

sids = [r[0] for r in con.execute(
    "SELECT DISTINCT session_key FROM session_paths WHERE LOWER(dir)=?", ("f:\\demo-wiki",))]
con.close()
print("声称碰过 f:\\demo-wiki 的会话: %d" % len(sids))

sample = sids[:150]
kind = collections.Counter()
examples = collections.defaultdict(list)

for sk in sample:
    sid = sk.split(":", 1)[1]
    hits = glob.glob(os.path.join(HOME, ".dsh", "sessions", "*", sid,
                                  "session.v4.jsonl.zstd"))
    if not hits:
        continue
    raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(hits[0], "rb").read())) \
        .read().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except Exception:                                # noqa: BLE001
            continue
        if ev.get("type") != "tool/call":
            continue
        data = ev.get("data") or {}
        args = data.get("arguments") or ""
        if "demo-wiki" not in args.lower():
            continue
        try:
            obj = json.loads(args) if isinstance(args, str) else args
        except Exception:                                # noqa: BLE001
            obj = {}
        # 判断路径出现在哪个字段
        field = "其它"
        for k, v in (obj or {}).items():
            if isinstance(v, str) and "demo-wiki" in v.lower():
                if k in ("file_path", "path", "cwd", "notebook_path", "dir"):
                    field = "路径字段:%s" % k
                elif k in ("query", "pattern", "prompt", "cmd", "command"):
                    field = "查询/命令:%s" % k
                else:
                    field = "其它字段:%s" % k
                break
        kind[field] += 1
        if len(examples[field]) < 3:
            examples[field].append((data.get("name"), json.dumps(obj, ensure_ascii=False)[:150]))

print("\n路径出现在哪个字段：")
for k, n in kind.most_common():
    print("  %-22s %d" % (k, n))
print("\n样例：")
for k, exs in examples.items():
    print("  [%s]" % k)
    for name, a in exs:
        print("     %s %s" % (name, a))
