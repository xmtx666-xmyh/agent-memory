"""生成 docs/releases/v<版本>.md：上架说明 + 哈希 + 变更，一次成型。

## 为什么要有它

平台只给一个 build id（`os_…`），本地只有一个 zip；两者对不上时，事后无法回答
"用户装的是不是这个包"。所以每发一版都留一份 release note，字段固定、机器可生成：

    version / 包文件 / 条目数 / zip_sha256 / content_sha256 / built_at / git commit
    + 可直接粘到平台的上架说明
    + 该版本的 changelog 段落

## 用法

    python tools/release_note.py                       # 用 dist/.last-package.json 当前戳
    python tools/release_note.py --platform-build os_xxxxxxxx   # 上传后回填平台 build id

数据来源（都是本仓既有产物，不新增真相源）：
    skill/agent-memory/SKILL.md      → version / name / description
    skill/agent-memory/references/changelog.md → 该版本条目
    dist/.last-package.json          → content_sha256 / zip_sha256 / built_at（pack 时写入）
    dist/agent-memory.zip            → 条目数（交叉核对）
    git                              → 提交号与日期（无 git 时留空，不报错）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = os.path.join(HOME, "skill", "agent-memory", "SKILL.md")
CHANGELOG = os.path.join(HOME, "skill", "agent-memory", "references", "changelog.md")
STAMP = os.path.join(HOME, "dist", ".last-package.json")
ZIP = os.path.join(HOME, "dist", "agent-memory.zip")
OUT_DIR = os.path.join(HOME, "docs", "releases")


def read_frontmatter(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"\'')
    return out


def changelog_section(version: str) -> str:
    """从 changelog 里截出 `## [x.y.z]` 这一段（到下一个 `## [` 或文件尾）。"""
    with open(CHANGELOG, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out, take = [], False
    for line in lines:
        if line.startswith("## ["):
            take = line.startswith("## [%s]" % version)
            if take:
                out.append(line)
            continue
        if take:
            out.append(line)
    return "\n".join(out).strip()


def git(*args: str) -> str:
    try:
        p = subprocess.run(["git", "-C", HOME, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="生成 release note（上架说明 + 哈希）")
    ap.add_argument("--platform-build", default="", help="平台 build id（如 os_e8ac2aed…）")
    ap.add_argument("--note", default="", help="额外附注（一句话，可空）")
    args = ap.parse_args(argv)

    fm = read_frontmatter(SKILL_MD)
    version = fm.get("version") or ""
    if not version:
        print("SKILL.md 缺 version", file=sys.stderr)
        return 1
    if not os.path.isfile(STAMP) or not os.path.isfile(ZIP):
        print("缺 dist/.last-package.json 或 dist/agent-memory.zip：先跑 pack_platform.ps1", file=sys.stderr)
        return 1
    with open(STAMP, encoding="utf-8") as fh:
        stamp = json.load(fh)
    if stamp.get("version") != version:
        print("戳里的版本(%s) 与 SKILL.md(%s) 不一致：重新打包" % (stamp.get("version"), version),
              file=sys.stderr)
        return 1
    entries = 0
    with zipfile.ZipFile(ZIP) as z:
        entries = len(z.namelist())
    commit = git("rev-parse", "--short", "HEAD")
    commit_date = git("log", "-1", "--format=%ad", "--date=iso")

    section = changelog_section(version)
    zip_sha = stamp.get("zip_sha256", "")
    content_sha = stamp.get("content_sha256", "")
    built = stamp.get("built_at", "")

    md = []
    md.append("# v%s 上架说明（release note）" % version)
    md.append("")
    md.append("> 本文件由 `tools/release_note.py` 生成；字段固定，便于与平台 build 对照。"
              "打包时间见下表（**不写生成时间**，保证同一包重复生成内容一致）。")
    md.append("")
    md.append("## 版本信息")
    md.append("")
    md.append("| 字段 | 值 |")
    md.append("|---|---|")
    md.append("| 版本 | **v%s** |" % version)
    md.append("| 包文件 | `dist/agent-memory.zip` |")
    md.append("| 条目数 | %d |" % entries)
    md.append("| zip sha256 | `%s` |" % zip_sha)
    md.append("| 内容 sha256 | `%s` |" % content_sha)
    md.append("| 打包时间 | %s |" % (built or "（未知）"))
    md.append("| 代码提交 | `%s`（%s） |" % (commit or "（无 git）", commit_date or "—"))
    md.append("| 平台 build | %s |" % (args.platform_build or "（待上传后回填）"))
    md.append("")
    md.append("## 上架说明（可直接粘到平台）")
    md.append("")
    md.append("> **v%s** %s" % (version, (args.note or "见下方变更条目。")))
    md.append("> 发布物 SHA256：`%s…`。建议已安装用户更新。" % zip_sha[:12])
    md.append("")
    md.append("## 变更")
    md.append("")
    md.append(section or "（changelog 里没有该版本条目——补上后再发版）")
    md.append("")
    md.append("## 核对方式")
    md.append("")
    md.append("```powershell")
    md.append("# 1) 本地包哈希（应与上表一致）")
    md.append("(Get-FileHash dist\\agent-memory.zip -Algorithm SHA256).Hash")
    md.append("# 2) 装好后自检（退出码 0 = 能用）")
    md.append(".\\scripts\\am.ps1 doctor")
    md.append("# 3) 版本号（应与本文件名一致）")
    md.append("Select-String -Path .\\SKILL.md -Pattern '^version:'")
    md.append("```")
    if args.note:
        md.append("")
        md.append("## 附注")
        md.append("")
        md.append(args.note)
    md.append("")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "v%s.md" % version)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md))
    print("已生成 -> %s（%d 条目，zip %s…）" % (out, entries, zip_sha[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
