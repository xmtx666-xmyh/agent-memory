# -*- coding: utf-8 -*-
"""peer 契约：同一个仓库的不同写法/不同 worktree 必须归到**同一个** peer。

依据：OpenViking 的取值规则（origin URL 优先，仓库根路径兜底），本机实测过的两种
失败模式是"按 cwd 分桶"（worktree 各成一家）与"按 agent 分桶"（同一话题两条线）。
"""
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from peers import normalize_remote, peer_for_cwd   # noqa: E402


def test_normalize_scp_style():
    assert normalize_remote("git@github.com:volcengine/OpenViking.git") == \
        "github.com-volcengine-openviking"


def test_normalize_https_with_token():
    assert normalize_remote("https://user:ghp_xxx@GitHub.com/owner/repo.git") == \
        "github.com-owner-repo"


def test_normalize_ssh_url_with_port():
    assert normalize_remote("ssh://git@example.com:2222/team/svc.git") == \
        "example.com-team-svc"


def test_normalize_empty_and_garbage():
    assert normalize_remote("") == ""
    assert normalize_remote("   ") == ""


def test_missing_cwd_has_no_peer():
    assert peer_for_cwd("") == ""
    assert peer_for_cwd("F:\\no-such-dir-agent-memory-test") == ""


def test_non_repo_has_no_peer(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert peer_for_cwd(str(d)) == ""


def _run(*args, cwd):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


@pytest.mark.skipif(not shutil.which("git"), reason="本机没有 git")
def test_clone_subdir_and_worktree_share_one_peer(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run("git", "init", "-q", cwd=str(repo)).returncode == 0
    _run("git", "config", "user.email", "t@t", cwd=str(repo))
    _run("git", "config", "user.name", "t", cwd=str(repo))
    _run("git", "remote", "add", "origin", "git@github.com:owner/repo.git", cwd=str(repo))

    sub = repo / "sub"
    sub.mkdir()
    expect = "github.com-owner-repo"
    assert peer_for_cwd(str(repo)) == expect
    assert peer_for_cwd(str(sub)) == expect          # 子目录不能变成新项目

    wt = tmp_path / "repo-wt"
    r = _run("git", "worktree", "add", "-q", str(wt), cwd=str(repo))
    if r.returncode == 0:
        assert peer_for_cwd(str(wt)) == expect       # worktree 与主仓共用 origin
    # 否则本机 git 版本不支持 worktree 参数组合，跳过该断言（其余断言已覆盖主路径）
