# -*- coding: utf-8 -*-
"""doctor 契约：装坏 / 没数据时必须报 ERROR 且退出码 1；装好后退出码 0。

依据（2026-11-04 平台反馈）：有人装了技能但没跑初始化，用户只能自己猜哪里不对。
doctor 是唯一能把"装了但没跑通"摊开给人看的地方（借鉴 openviking-server doctor / npm doctor）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import cmd_doctor                                    # noqa: E402
from collectors.base import CollectResult, Record, SessionMeta, session_key  # noqa: E402
from store import Store, ingest                               # noqa: E402


class _Args:
    def __init__(self, db):
        self.db = db


def _one_session():
    meta = SessionMeta(agent="dsh", session_id="doc1", title="t", cwd="F:\\proj",
                       message_count=1)
    sk = session_key("dsh", "doc1")
    rec = Record(session_key=sk, role="user", text="PageIndex 的节点怎么建", seq=0)
    return CollectResult(meta=meta, records=[rec])


def test_doctor_missing_db_is_error(tmp_path, capsys):
    rc = cmd_doctor(_Args(str(tmp_path / "nope.db")))
    out = capsys.readouterr().out
    assert rc == 1
    assert "索引库" in out and "不存在" in out


def test_doctor_empty_db_is_error(tmp_path, capsys):
    db = str(tmp_path / "empty.db")
    Store(db).close()
    rc = cmd_doctor(_Args(db))
    out = capsys.readouterr().out
    assert rc == 1
    assert "索引是空的" in out


def test_doctor_ok_after_ingest(tmp_path, capsys):
    db = str(tmp_path / "ok.db")
    st = Store(db)
    ingest(st, [_one_session()], peer_fn=lambda cwd: "path-proj-abc12345")
    st.close()
    rc = cmd_doctor(_Args(db))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "数据 schema" in out and "库 v1 / 代码 v1" in out
    assert "会话 / 消息" in out and "1 / 1" in out
