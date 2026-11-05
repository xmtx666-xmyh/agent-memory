"""各 agent 会话采集器共用的数据结构。

设计原则（来自对 Hermes `session_search` 的实测借鉴，见 docs/design.md）：
  · 只索引 **user / assistant 的正文**，丢掉 reasoning 与工具输出 ——
    工具输出动辄上千字符，是噪音大头；跨会话回忆要的是"人说了什么、agent 下了什么结论"。
  · 保留会话级元数据（agent / cwd / 时间 / 模型 / 父子关系），用于后续"话题演变"按时间与血缘归并。
  · 采集器只做"读 + 归一"，不做任何判断（不摘要、不打标）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class SessionMeta:
    """一个会话的元数据。

    注意：`session_id` 必须是**可空**的 —— 采集器在扫到文件开头之前还不知道 id
    （DSH 在首个事件、Codex 在 session_meta 行、Claude 在文件名），
    所以先构造再回填。写成必填会让所有"先构造后解析"的采集器直接 TypeError。
    """
    agent: str
    session_id: str = ""
    title: str = ""
    cwd: str = ""
    started_at: str = ""            # ISO8601（尽量带时区）
    ended_at: str = ""
    model: str = ""
    provider: str = ""
    parent_session: str = ""        # 血缘：父会话 id（subagent / 续接）
    origin: str = ""                # 来源：user / subagent / cron ……
    source_path: str = ""           # 原始文件路径（可溯源）
    message_count: int = 0
    tool_call_count: int = 0


@dataclass
class Record:
    """一条要进索引的消息（只含 user / assistant 正文）。"""
    session_key: str                # f"{agent}:{session_id}"，全局唯一
    role: str                       # user / assistant
    text: str
    ts: str = ""                    # ISO8601
    seq: int = 0                    # 会话内序号，保证稳定排序


@dataclass
class CollectResult:
    meta: SessionMeta
    records: list[Record] = field(default_factory=list)
    #: 本会话工具调用里碰过的**项目目录**（去重后按出现次数降序）。
    #: 只存目录级路径，不存工具输出正文 —— 用途是"用碰过哪些文件定实体归属"，
    #: 因为实测 cwd 不可靠（`F:\demo-main` 有 244 个会话，与话题无关）、正文提及也可靠不住
    #: （在 cwd=F:\demo-kb 里干活、产出却是 F:\agent-memory 新项目）。
    tool_dirs: list[tuple[str, int]] = field(default_factory=list)


def session_key(agent: str, session_id: str) -> str:
    return "%s:%s" % (agent, session_id)


#: 从工具参数里抽路径：先试结构化字段，再用绝对路径正则兜底
#: （Codex 的 `exec_command` 把路径塞在 `cmd` 字符串里、MCP 工具塞在 `prompt` 里）。
_PATH_KEYS = ("file_path", "path", "notebook_path", "target_file", "cwd",
              "directory", "dir", "file")
_ABS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'`<>|*?\n]{2,240}")
#: 中文标点/空白：路径常被写进中文句子里（实测 `F:\demo-wiki，python` / `F:\demo-wiki；作业清单`）
_CJK_STOP_RE = re.compile(r"[，。；：、（）「」【】《》\s]")
#: 看起来像文件名的段（有扩展名），不能当项目目录
_LOOKS_LIKE_FILE = re.compile(r"\.[A-Za-z0-9]{1,8}$")

#: 纯噪音目录：系统盘根、程序目录，跟"哪个项目在干活"无关（实测 c:\program 命中 147 次）
_NOISE_DIRS = {"c:\\windows", "c:\\programdata", "c:\\perflogs", "c:\\$recycle.bin",
               "c:\\temp", "c:\\program files", "c:\\program files (x86)"}
#: agent 自身的内部目录（会话/缓存），不是"项目"（实测 Claude 大量路径在 .claude 下）
_AGENT_INTERNAL = {".claude", ".codex", ".dsh", ".workbuddy", ".codebuddy", ".git"}
#: 用户目录下的"容器"层，真正项目在更深一层（`C:\Users\demo\Desktop\某项目`）
_USER_CONTAINERS = {"desktop", "documents", "downloads", "projects", "source",
                    "repos", "code", "work"}


def _project_dir(cand: str) -> str:
    """把一条绝对路径压成"项目目录"。

    规则（用显式分段，不用正则 —— 正则里可选段会贪婪多吃一层，实测踩过）：
      F:\\agent-memory\\collectors\\base.py  →  f:\\agent-memory
      C:\\Users\\demo\\Desktop\\某项目\\a.py  →  c:\\users\\demo\\desktop\\某项目
      C:\\Users\\demo\\.claude\\projects\\x    →  （空，agent 内部目录）
      C:\\Windows\\System32\\x               →  （空，噪音）
    """
    parts = [p for p in cand.replace("/", "\\").split("\\") if p != ""]
    if len(parts) < 2 or len(parts[0]) != 2 or parts[0][1] != ":":
        return ""
    drive = parts[0].lower()
    segs = [p.lower() for p in parts[1:]]
    # agent 内部目录：任意一层出现就丢
    if any(s in _AGENT_INTERNAL for s in segs):
        return ""
    base = drive + "\\" + segs[0]
    if any(base == n or base.startswith(n) for n in _NOISE_DIRS):
        return ""
    if segs[0] == "users":
        # c:\users\<name>[ \<container>\<proj> ]
        out = [drive, "users"]
        if len(segs) >= 2:
            out.append(segs[1])
        if len(segs) >= 4 and segs[2] in _USER_CONTAINERS:
            out.append(segs[2])
            if not _LOOKS_LIKE_FILE.search(segs[3]):     # 第 4 段是文件名就别当目录
                out.append(segs[3])
        return "\\".join(out)
    return base


def _all_strings(obj, out: list, depth: int = 0) -> None:
    """递归收集 dict/list 里所有字符串值（用于在**解码后**的文本上找路径）。"""
    if depth > 4:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _all_strings(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _all_strings(v, out, depth + 1)


def path_dirs_from_args(args) -> list[str]:
    """从一次工具调用的参数里抽出**项目目录**（形如 `F:\\agent-memory`）。

    `args` 可以是 dict，也可以是 JSON 字符串（DSH/Codex 都是字符串）。
    返回去重后的目录列表；解析不了就返回空。

    ⚠️ 踩坑记录：**正则必须在 json 解析后的字符串上跑**，不能直接跑原始 JSON 串 ——
    JSON 里路径是双反斜杠（`F:\\\\agent-memory`），`^[A-Za-z]:\\([^\\]+)` 会因
    第二个反斜杠而匹配失败（实测 Codex `exec_command` 用例就是这样漏掉的）。
    """
    raw = ""
    obj = None
    if isinstance(args, dict):
        obj = args
        raw = json.dumps(args, ensure_ascii=False)
    elif isinstance(args, str):
        raw = args
        try:
            obj = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            obj = None

    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _PATH_KEYS and isinstance(v, str) and v:
                found.append(v)
    # 兜底：在**解码后**的字符串值里找绝对路径（覆盖 cmd / prompt 两种塞法）
    decoded: list[str] = []
    if obj is not None:
        _all_strings(obj, decoded)
    if not decoded:
        decoded.append(raw.replace("\\\\", "\\"))
    for s in decoded:
        found.extend(_ABS_PATH_RE.findall(s))

    dirs: list[str] = []
    for p in found:
        # 先剥掉常见的尾部标点：路径常出现在 `...x.py;` / `...x.py,` / `...x.py)` 里，
        # 实测不剥会出现 `f:\demo-wiki;` 这种脏目录名
        cand = p.strip().strip('"').rstrip(";,.):]}'")
        # 再在中文标点处截断：`F:\demo-wiki，python` 只保留到 `F:\demo-wiki`
        cand = _CJK_STOP_RE.split(cand, 1)[0].rstrip(";,.):]}'")
        d = _project_dir(cand)
        if d and d not in dirs:
            dirs.append(d)
    return dirs


def top_dirs(counter, limit: int = 3) -> list[tuple[str, int]]:
    """按出现次数取前 N 个项目目录。"""
    return sorted(counter.items(), key=lambda kv: -kv[1])[:limit]


def clean_text(s: Optional[str]) -> str:
    """去掉纯空白与超长噪音：单条正文上限 20000 字符（借鉴 Hermes 的内容上限思路）。

    超长单条（往往是粘贴进来的整文件）对"话题回忆"贡献低，却会把索引和后续上下文撑爆。
    """
    if not s:
        return ""
    t = s.strip()
    if len(t) > 20000:
        t = t[:20000] + "\n…[截断]"
    return t


def texts_from_blocks(blocks: Iterable) -> str:
    """从 [{type:'text', text:...}, ...] 里拼出正文，跳过 reasoning / tool 块。"""
    out = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") in ("text", "input_text", "output_text"):
            t = b.get("text") or ""
            if t:
                out.append(t)
    return "\n".join(out)


#: agent 自己注入给模型的"伪 user 消息"——不是人说的话，进索引只会制造噪音。
#: 实测来源：DSH 的 `<system-reminder>` / `Current runtime context.` / `# AGENTS.md instructions`，
#: Codex 的 `# AGENTS.md instructions` / `<app-context>`。
_INJECT_PREFIXES = (
    "<system-reminder>",
    "<app-context>",
    "Current runtime context.",
    "# AGENTS.md instructions",
    "Additional instructions from:",
    "The following workspace instructions may be relevant",
)


def is_injected_context(text: str) -> bool:
    """判断一条 user 消息是否是 agent 注入的上下文（而非人类输入）。"""
    t = (text or "").lstrip()
    return any(t.startswith(p) for p in _INJECT_PREFIXES)
