# -*- coding: utf-8 -*-
"""技能包装脚本契约：**未初始化**时必须给可操作提示 + 退出码 3。

依据（2026-11-04 平台反馈）：装了这个技能的人里有没跑 bootstrap 的，旧版只抛一句
`agent-memory home not found. Set AGENT_MEMORY_HOME ...`（英文、无下一步）。新版必须：
① 退出码 3（区别于查询错误 2）；② 正文直接给三种修法（设环境变量 / install.ps1 / bootstrap.ps1）。
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "skill", "agent-memory", "scripts")


@pytest.mark.skipif(not shutil.which("powershell"), reason="需要 Windows PowerShell")
def test_uninitialised_exits_3_with_actionable_message(tmp_path):
    dst = tmp_path / "skill" / "scripts"
    dst.mkdir(parents=True)
    for f in os.listdir(SCRIPTS):
        if f.endswith(".ps1"):
            shutil.copy2(os.path.join(SCRIPTS, f), dst / f)

    env = dict(os.environ)
    env.pop("AGENT_MEMORY_HOME", None)
    env["USERPROFILE"] = str(tmp_path)          # 兜底目录指向空 tmp，确保解析失败
    for k in ("HOMEDRIVE", "HOMEPATH"):
        env.pop(k, None)

    p = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(dst / "am.ps1"), "stats"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(tmp_path), timeout=60)

    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 3, (p.returncode, out)
    assert "NOT initialised" in out, out
    assert "AGENT_MEMORY_HOME" in out, out
    assert "bootstrap.ps1" in out, out
    assert "install.ps1" in out, out
