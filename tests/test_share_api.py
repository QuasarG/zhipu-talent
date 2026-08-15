"""分享链接 API 契约测试：创建复用 / 公开只读 / 吊销 / 隔离。

进程内先钉死 DATABASE_URL 为内存 SQLite（load_dotenv 会在 import 时读 .env
连上真实 MySQL，必须抢在 workbench import 之前覆盖）。
"""
from __future__ import annotations

import os

_SAVED_URL = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite://"  # noqa: E402 — 必须在 app import 前

import unittest
from unittest.mock import patch

from agi_talent_radar.web.workbench import create_app
from agi_talent_radar.core.db.orm import Base, PersonORM
from agi_talent_radar.core.db.runtime import get_engine
from agi_talent_radar.core.database import get_session


def _seed_person() -> str:
    # get_session 返回裸 Session（非 contextmanager）：必须显式 commit，否则 with 退出即回滚
    Base.metadata.create_all(get_engine())
    session = get_session()
    try:
        existing = session.get(PersonORM, "person-share-test")
        if existing is not None:
            return existing.id
        p = PersonORM(id="person-share-test", name="分享测试", fingerprint="fp-share")
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


class ShareApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pid = _seed_person()
        self._auth = patch("agi_talent_radar.web.auth.is_authenticated", return_value=True)
        self._auth.start()
        self.client = create_app().test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        # 还原 env，避免本模块的内存库设置泄漏污染同进程其他测试
        if _SAVED_URL is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _SAVED_URL

    def tearDown(self) -> None:
        self._auth.stop()

    def test_create_then_public_read(self) -> None:
        r = self.client.post(f"/api/persons/{self.pid}/share")
        self.assertEqual(r.status_code, 200)
        token = r.get_json()["token"]

        # 公开读取（无鉴权上下文）：拿得到该人档案
        pub = create_app().test_client()
        r2 = pub.get(f"/api/share/{token}")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["name"], "分享测试")

    def test_create_is_idempotent(self) -> None:
        t1 = self.client.post(f"/api/persons/{self.pid}/share").get_json()["token"]
        t2 = self.client.post(f"/api/persons/{self.pid}/share").get_json()["token"]
        self.assertEqual(t1, t2)

    def test_revoke_blocks_access(self) -> None:
        token = self.client.post(f"/api/persons/{self.pid}/share").get_json()["token"]
        self.assertEqual(self.client.delete(f"/api/persons/{self.pid}/share").status_code, 200)
        pub = create_app().test_client()
        self.assertEqual(pub.get(f"/api/share/{token}").status_code, 404)

    def test_unknown_token_404(self) -> None:
        pub = create_app().test_client()
        self.assertEqual(pub.get("/api/share/no-such-token").status_code, 404)


if __name__ == "__main__":
    unittest.main()
