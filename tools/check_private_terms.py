"""打包前敏感词扫描：扫 stage 目录（= 将要进 zip 的文件）里的真实项目/客户名与内部路径。

规则：命中任一即 **PACK FAIL**，并逐条打印 `文件: 词`。
词表放在仓库根的 `.private-terms.txt`（**gitignore，不进包、不进公开仓**）：
一行一个词，`#` 开头为注释，大小写不敏感。

为什么必须放在打包流程里（而不是靠自觉）：2026-11-04 上传的 v1.4.0/v1.5.0 就把
真实项目名与客户名带进了平台包（14/28 个文件命中），我们是事后才发现 —— 没有机检就等于没有规则。
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMS_FILE = os.path.join(REPO, ".private-terms.txt")
STAGE = os.path.join(REPO, "dist", "stage")
TEXT_EXT = {".py", ".md", ".txt", ".ps1", ".json", ".yml", ".yaml", ".cfg", ".ini"}


def load_terms() -> list[str]:
    if not os.path.isfile(TERMS_FILE):
        return []
    out = []
    with open(TERMS_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    terms = load_terms()
    if not terms:
        print("private-terms: 词表缺失或为空（%s）—— 本机没配词表时跳过扫描" % TERMS_FILE)
        return 0

    if "--zip" in sys.argv:
        return scan_zip(terms)

    if not os.path.isdir(STAGE):
        print("private-terms: stage 目录不存在：%s" % STAGE, file=sys.stderr)
        return 2

    hits: list[tuple[str, str]] = []
    scanned = 0
    for root, _dirs, files in os.walk(STAGE):
        for name in files:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, STAGE).replace("\\", "/")
            scanned += 1
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read().lower()
            for term in terms:
                if term.lower() in text:
                    hits.append((rel, term))

    print("private-terms: 扫描 %d 个文本文件 ｜ 词表 %d 条 ｜ 命中 %d" %
          (scanned, len(terms), len(hits)))
    for rel, term in hits:
        print("  HIT  %-32s %s" % (rel, term))
    if hits:
        print("\nPACK FAIL: 包内含有私有词。改掉或用 .private-terms.txt 里的白名单机制，别直接发。",
              file=sys.stderr)
        return 1
    return 0


def scan_zip(terms: list[str]) -> int:
    """直接核对**已产出的 zip**（发布前最后一道：防止 stage 扫过之后又被改动）。"""
    import zipfile

    zip_path = os.path.join(REPO, "dist", "agent-memory.zip")
    if not os.path.isfile(zip_path):
        print("private-terms: zip 不存在：%s" % zip_path, file=sys.stderr)
        return 2
    hits = []
    scanned = 0
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith("/") or os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            scanned += 1
            text = z.read(name).decode("utf-8", "replace").lower()
            for term in terms:
                if term.lower() in text:
                    hits.append((name, term))
    print("private-terms(zip): 扫描 %d 个文本文件 ｜ 词表 %d 条 ｜ 命中 %d" %
          (scanned, len(terms), len(hits)))
    for name, term in hits:
        print("  HIT  %-32s %s" % (name, term))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
