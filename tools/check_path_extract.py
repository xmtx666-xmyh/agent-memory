"""L1 验证：path_dirs_from_args 在三种真实参数形态上都能抽出项目目录。

三种形态都是实测抓到的（见 tools/probe_tool_paths.py）：
  DSH   `{"file_path": "F:\\\\demo-main\\\\work\\\\..."}`
  Codex `exec_command` 的 `{"cmd": "python -c ..."}`（路径藏在命令字符串里）
  Claude `{"pattern": "**/*.md", "path": "C:\\\\Users\\\\..."}`
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.base import path_dirs_from_args, top_dirs   # noqa: E402

CASES = [
    ("DSH read",
     '{"file_path": "F:\\\\agent-memory\\\\collectors\\\\base.py"}',
     ["f:\\agent-memory"]),
    ("DSH 多路径",
     '{"file_path": "F:\\\\agent-memory\\\\store.py", "cwd": "F:\\\\demo-kb"}',
     ["f:\\agent-memory", "f:\\demo-kb"]),
    ("Codex exec_command（路径在命令里）",
     '{"cmd": "python F:\\\\agent-memory\\\\cli.py --help"}',
     ["f:\\agent-memory"]),
    ("Claude Glob（agent 内部目录 → 噪音，应为空）",
     '{"pattern": "**/*.md", "path": "C:\\\\Users\\\\demo\\\\.claude\\\\projects"}',
     []),
    ("Claude 桌面项目",
     '{"file_path": "C:\\\\Users\\\\demo\\\\Desktop\\\\demo-kb\\\\a.py"}',
     ["c:\\users\\demo\\desktop\\demo-kb"]),
    ("系统目录（噪音）",
     '{"cmd": "C:\\\\Windows\\\\System32\\\\cmd.exe /c dir"}',
     []),
    ("dict 入参",
     {"file_path": "F:\\agent-memory\\README.md"},
     ["f:\\agent-memory"]),
    ("无路径",
     '{"query": "hello"}',
     []),
    ("非法 JSON 但有绝对路径",
     'not json but F:\\agent-memory\\x.py here',
     ["f:\\agent-memory"]),
]

ok = True
for name, args, expect in CASES:
    got = path_dirs_from_args(args)
    good = got == expect
    ok = ok and good
    print("  %-32s %s  得到=%s 期望=%s" % (name, "OK  " if good else "FAIL", got, expect))

print()
print("  top_dirs 排序:", top_dirs({"f:\\b": 1, "f:\\a": 5, "f:\\c": 3}, 2))
print()
print("全部通过" if ok else "**有用例失败**")
sys.exit(0 if ok else 1)
