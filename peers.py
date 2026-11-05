"""工作区身份（peer）：让**同一个仓库**的会话共用一份归属，而不串到别的项目。

## 为什么按 git 派生，而不是按 cwd / 按 agent

实测过的两种失败模式（本机 555 会话，2026-11-04 复核后定）：

- **按 cwd 分桶**：`F:\\demo-base`、`F:\\demo-base\\work`、各种 worktree 会变成不同"项目"，
  同一件事被拆成多条线；
- **按 agent 分桶**：同一件事在 DSH 与 Codex 里各存一份，跨 agent 检索就永远要人肉合并。

OpenViking 的取值规则（官方文档）：peer 先按 **git 归一化 origin URL**（`git@github.com:owner/repo.git`
→ `github.com-owner-repo`），其次仓库根路径，不在仓库里就不发 peer。本仓照抄这条 —— 因为
`git` 天然知道"同一个仓库"：多个 clone/worktree 共用同一个 origin 与 common-dir。

## 边界（这里只做"归属"，不改检索主路）

- peer **不参与** FTS5 检索与实体×意图打标，只用于过滤与分组（`search --peer`、`peers` 命令）；
- 非 git 目录（或 cwd 已不存在）**没有 peer**，返回空串 —— 不猜、不按盘符兜底；
- 无 origin 时回退 `path-<目录名>-<路径哈希8位>`：同一台机器稳定，但**换机就变**（无 origin 时只能如此）。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess

#: 网络/Git 异常都收敛成空串：这里绝不能让 ingest 因为一个坏仓库中断
_GIT_TIMEOUT = 2.0


def _git(cwd: str, *args: str) -> str:
    """在 cwd 里跑一条只读 git 命令；失败/超时/没装 git 都返回空串。"""
    cmd = ["git", "-C", cwd, *args]
    kwargs = {}
    if os.name == "nt":
        # 避免弹控制台窗口（Windows 上 subprocess 默认会闪一下）
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=_GIT_TIMEOUT,
                           encoding="utf-8", errors="replace", **kwargs)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def normalize_remote(url: str) -> str:
    """把各种 origin 写法归一成稳定的 peer id。

    >>> normalize_remote("git@github.com:volcengine/OpenViking.git")
    'github.com-volcengine-openviking'
    >>> normalize_remote("https://user:token@GitHub.com/owner/repo")
    'github.com-owner-repo'
    >>> normalize_remote("")
    ''
    """
    if not url:
        return ""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    # scp 风格 git@host:path → host + path
    m = re.match(r"^[^@/]+@([^:/]+):(.+)$", u)
    if m:
        host, path = m.group(1), m.group(2)
    else:
        # 任意协议（https/ssh/git/...）→ 去协议、去 userinfo（含 token）
        u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", u)
        head, _, path = u.partition("/")
        if "@" in head:
            head = head.split("@", 1)[1]
        host = re.sub(r":\d+$", "", head)                # 端口不是身份的一部分
    # 主机名保留点号（github.com-owner-repo 是 OpenViking 的写法），路径段统一成连字符
    host = re.sub(r"[^a-z0-9.]+", "-", host.lower()).strip("-")
    path = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    if not host:
        return ""
    return "%s-%s" % (host, path) if path else host


def common_root(cwd: str) -> str:
    """仓库的**共同根**：主仓与所有 worktree 指向同一个，用于"同仓库不同 worktree 归一个 peer"。"""
    d = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if d:
        # 主仓是 <root>/.git；linked worktree 的 common-dir 指向主仓的 .git
        return os.path.dirname(os.path.abspath(d))
    rel = _git(cwd, "rev-parse", "--git-common-dir")     # 老版 git 没有 --path-format
    if rel:
        return os.path.dirname(os.path.abspath(os.path.join(cwd, rel)))
    return _git(cwd, "rev-parse", "--show-toplevel")


def peer_for_cwd(cwd: str) -> str:
    """由会话的 cwd 派生 peer：origin URL 优先，回退仓库根路径哈希；非仓库返回空串。"""
    if not cwd or not os.path.isdir(cwd):
        return ""
    root = common_root(cwd)
    if not root:
        return ""
    peer = normalize_remote(_git(root, "config", "--get", "remote.origin.url"))
    if peer:
        return peer
    base = os.path.basename(root.rstrip("\\/")) or "repo"
    digest = hashlib.sha1(root.lower().encode("utf-8")).hexdigest()[:8]
    return "path-%s-%s" % (re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "repo", digest)


def peer_map(cwds) -> dict:
    """批量派生（同一 cwd 只算一次，避免 555 次 git 调用）。"""
    cache: dict = {}
    for cwd in cwds:
        c = cwd or ""
        if c not in cache:
            cache[c] = peer_for_cwd(c)
    return cache
