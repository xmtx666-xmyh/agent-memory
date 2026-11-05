"""pytest 公共夹具：载入实体同义词表。

## 为什么

实体同义词表是**数据**（`index/entities.json`，由 `cli.py init` 按本机会话生成），
不是代码。为了让测试在任何机器、任何 CI 上都可复现，本仓自带一份
`tests/fixtures/entities.json`（全是 demo 实体名），本夹具优先载入它；
没有夹具时退化为 `index/entities.json`（本机真实数据）。

依赖真实索引库（`index/sessions.db`）的用例在缺少该库时显式 skip，见 test_inject.py。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from topics import load_entities  # noqa: E402


def _entities_path() -> str:
    fixture = os.path.join(ROOT, "tests", "fixtures", "entities.json")
    if os.path.exists(fixture):
        return fixture
    return os.path.join(ROOT, "index", "entities.json")


def pytest_configure(config):
    path = _entities_path()
    n = load_entities(path)
    # 只用 ASCII 打印：CI 的 Windows runner 控制台是 cp1252，中文 print 会
    # UnicodeEncodeError 把整轮测试打成 INTERNALERROR。
    print("\n[conftest] entities loaded: %d (%s)" % (n, path))


@pytest.fixture(scope="session")
def repo_root():
    return ROOT
