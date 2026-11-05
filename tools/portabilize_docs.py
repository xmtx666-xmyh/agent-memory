"""把技能文档里的本机硬编码改成通用写法（换机器可用）。

替换内容：
  · `F:\\agent-memory\\.venv\\Scripts\\python.exe F:\\agent-memory\\cli.py X` → `<skill>\\scripts\\am.ps1 X`
  · `python cli.py X` → `am.ps1 X`
  · 残留的 `F:\\agent-memory` → `<工程目录>`
  · 在文件开头插一句"实体名/路径都是本机示例"

用二进制读写，避免 CRLF 变化把整文件算成改动。
"""
import io
import os
import re

SKILL = r"F:\agent-memory\skill\agent-memory"
FILES = [os.path.join(SKILL, "references", "cli.md"),
         os.path.join(SKILL, "references", "verdicts.md")]

NOTE = ("> 本文出现的**实体名与项目路径都是本机示例**（每台机器不同）；"
        "换机器请先用 `am.ps1 topics --top 20` 查本机实际有哪些实体。\n\n")

SUBS = [
    (re.compile(r"F:\\agent-memory\\\.venv\\Scripts\\python\.exe\s+F:\\agent-memory\\cli\.py\s*"),
     "<skill>\\scripts\\am.ps1 "),
    (re.compile(r"F:\\agent-memory\\\.venv\\Scripts\\python\.exe\s*"),
     "<skill>\\scripts\\am.ps1 "),
    (re.compile(r"python\s+cli\.py\s+"), "am.ps1 "),
    (re.compile(r"F:\\agent-memory"), "<工程目录>"),
]

for path in FILES:
    if not os.path.exists(path):
        print("missing: %s" % path)
        continue
    raw = open(path, "rb").read().decode("utf-8")
    new = raw
    for rx, rep in SUBS:
        # 必须用 lambda：replacement 里的 `\s`（来自 <skill>\scripts）会被 re 当转义（踩过两次）
        new = rx.sub(lambda m, _r=rep: _r, new)
    if NOTE not in new:
        # 插到一级标题之后（第一行 # 标题）
        lines = new.splitlines(True)
        idx = 1 if lines and lines[0].startswith("# ") else 0
        lines.insert(idx, "\n" + NOTE)
        new = "".join(lines)
    if new != raw:
        open(path, "wb").write(new.replace("\r\n", "\n").encode("utf-8"))
        print("updated: %s" % os.path.basename(path))
    else:
        print("unchanged: %s" % os.path.basename(path))

# 复查残留
import subprocess
for path in FILES:
    txt = open(path, "rb").read().decode("utf-8")
    left = txt.count("F:\\agent-memory")
    print("%-12s 残留 F:\\agent-memory: %d 处" % (os.path.basename(path), left))
