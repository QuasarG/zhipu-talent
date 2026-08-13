"""grill 画像澄清会话持久化测试：repository CRUD + 收敛判定 + owner 隔离。

sqlite 内存库 + monkeypatch repository.get_session 指向内存引擎，不打外网。
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, GrillSessionORM, UserORM
from agi_talent_radar.grill import repository


class GrillPipelineBase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._orig_get_session = repository.get_session
        repository.get_session = self._ctx  # type: ignore[assignment]
        with self._ctx() as s:
            owner = UserORM(username="hr1", password_hash="x")
            other = UserORM(username="hr2", password_hash="x")
            s.add(owner)
            s.add(other)
            s.commit()
            s.refresh(owner)
            s.refresh(other)
            self.owner_id = owner.id
            self.other_id = other.id

    @contextmanager
    def _ctx(self):
        session = self.Session()
        try:
            yield session
        finally:
            session.close()

    def tearDown(self) -> None:
        repository.get_session = self._orig_get_session  # type: ignore[assignment]


class TestSessionCRUD(GrillPipelineBase):
    def test_create_and_get(self) -> None:
        sess = repository.create_session(self.owner_id)
        sid = sess["session_id"]
        self.assertTrue(sid)
        again = repository.get_session_by_id(sid)
        self.assertIsNotNone(again)
        self.assertFalse(again["converged"])  # type: ignore[index]
        self.assertEqual(again["outline"], [])  # type: ignore[index]

    def test_save_profile_and_converged(self) -> None:
        sess = repository.create_session(self.owner_id)
        sid = sess["session_id"]
        # 必填字段全部拉满置信度 → 收敛
        profile = repository.empty_profile()
        for f in profile["required_fields"].values():
            f["confidence"] = 0.9
        converged = repository.check_converged(profile)
        repository.save_session(sid, profile=profile, converged=converged)
        loaded = repository.get_session_by_id(sid)
        self.assertTrue(loaded["converged"])  # type: ignore[index]

    def test_title_from_position(self) -> None:
        sess = repository.create_session(self.owner_id)
        profile = sess["profile"]
        profile["required_fields"]["position_name"]["value"] = "资深后端工程师"
        repository.save_session(sess["session_id"], profile=profile)
        loaded = repository.get_session_by_id(sess["session_id"])
        self.assertEqual(repository.title_of(loaded), "资深后端工程师")  # type: ignore[arg-type]

    def test_title_fallback_to_first_message(self) -> None:
        sess = repository.create_session(self.owner_id)
        repository.save_session(sess["session_id"], messages=[{"role": "user", "text": "招个前端", "tools": []}])
        loaded = repository.get_session_by_id(sess["session_id"])
        self.assertEqual(repository.title_of(loaded), "招个前端")  # type: ignore[arg-type]


class TestOwnerIsolation(GrillPipelineBase):
    def test_list_only_own_sessions(self) -> None:
        repository.create_session(self.owner_id)
        repository.create_session(self.owner_id)
        repository.create_session(self.other_id)
        self.assertEqual(len(repository.list_sessions(self.owner_id)), 2)
        self.assertEqual(len(repository.list_sessions(self.other_id)), 1)

    def test_delete_only_own(self) -> None:
        mine = repository.create_session(self.owner_id)["session_id"]
        # other 用户删我的会话 → 删不掉
        self.assertEqual(repository.delete_sessions([mine], self.other_id), 0)
        self.assertIsNotNone(repository.get_session_by_id(mine))
        # 自己删 → 成功
        self.assertEqual(repository.delete_sessions([mine], self.owner_id), 1)
        self.assertIsNone(repository.get_session_by_id(mine))


class TestRunningGuard(GrillPipelineBase):
    def test_try_set_running_mutex(self) -> None:
        sess = repository.create_session(self.owner_id)
        sid = sess["session_id"]
        self.assertTrue(repository.try_set_running(sid))
        self.assertFalse(repository.try_set_running(sid))  # 已抢占
        repository.clear_running(sid)
        self.assertTrue(repository.try_set_running(sid))  # 清零后可再抢


class TestConverged(GrillPipelineBase):
    def test_partial_not_converged(self) -> None:
        profile = repository.empty_profile()
        # 只确认部分必填字段
        keys = list(profile["required_fields"])
        for k in keys[:3]:
            profile["required_fields"][k]["confidence"] = 0.9
        self.assertFalse(repository.check_converged(profile))

    def test_all_required_converged(self) -> None:
        profile = repository.empty_profile()
        for f in profile["required_fields"].values():
            f["confidence"] = 0.8
        self.assertTrue(repository.check_converged(profile))


if __name__ == "__main__":
    unittest.main()
