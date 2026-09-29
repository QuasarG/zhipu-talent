"""鉴权 middleware + /api/auth 测试（多账号版）。

覆盖：
1. 未登录访问 /api/* 返回 401。
2. 未登录访问页面跳转 /login。
3. 登录成功后可访问受保护资源。
4. 错误密码 / 不存在用户 / 停用账号登录失败（fail-closed）。
5. logout 后会话失效。
6. 白名单路径（/login /api/auth/login /health）无需鉴权。
7. reviewer 角色：奖学金/通知/会话/只读配置 API 放行，其余 /api/* 返回 403；
   页面不区分（SPA 外壳统一）；admin 不受影响。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash

from agi_talent_radar.core.db.orm import Base, UserORM
from agi_talent_radar.web.auth import (
    build_auth_blueprint,
    configure_app_session,
    install_auth_middleware,
)


def _make_session_factory():
    """StaticPool 内存库：跨 session 共享同一份数据。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _make_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../agi_talent_radar/web/templates",
        static_folder="../agi_talent_radar/web/static",
    )
    app.config["TESTING"] = True
    configure_app_session(app)
    install_auth_middleware(app)
    app.register_blueprint(build_auth_blueprint())

    @app.get("/api/protected")
    def protected():
        from flask import jsonify

        return jsonify({"ok": True})

    @app.get("/dashboard")
    def dashboard():
        return "<h1>dashboard</h1>"

    @app.get("/scholarship/graph")
    def scholarship_graph():
        return "<h1>graph</h1>"

    # reviewer 角色边界测试用的替身路由（只验证中间件放行/拦截，不实现业务）
    from flask import jsonify as _jsonify

    def _stub():
        return _jsonify({"ok": True})

    for _path in ("/api/candidates", "/api/scholarship/applications", "/api/scholarship/advisor-graph", "/api/notifications", "/api/config", "/api/config/audit"):
        app.add_url_rule(_path, f"stub_get{_path.replace('/', '_')}", _stub, methods=["GET"])
    app.add_url_rule("/api/config", "stub_config_put", _stub, methods=["PUT"])

    return app


class AuthTestBase(unittest.TestCase):
    """内存库 + 种子用户 admin；patch get_session 指向内存库。"""

    def setUp(self) -> None:
        self.Session = _make_session_factory()
        with self.Session() as session:
            session.add(
                UserORM(
                    username="admin",
                    password_hash=generate_password_hash("correct-password"),
                    display_name="管理员",
                )
            )
            session.commit()
        self.patch_db = patch(
            "agi_talent_radar.core.database.get_session",
            side_effect=lambda: self.Session(),
        )
        self.patch_db.start()
        self.app = _make_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.patch_db.stop()

    def login(self, username: str = "admin", password: str = "correct-password"):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )


class TestAuthMiddleware(AuthTestBase):
    def test_unauthenticated_api_returns_401(self) -> None:
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 401)

    def test_unauthenticated_page_redirects_to_login(self) -> None:
        rv = self.client.get("/dashboard")
        self.assertEqual(rv.status_code, 302)
        self.assertIn("/login", rv.headers.get("Location", ""))

    def test_public_paths_accessible_without_auth(self) -> None:
        rv = self.client.get("/login")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/health")
        self.assertEqual(rv.status_code, 200)

    def test_login_success_grants_access(self) -> None:
        rv = self.login()
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json()["user"]["username"], "admin")
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 200)

    def test_wrong_password_rejected(self) -> None:
        rv = self.login(password="wrong")
        self.assertEqual(rv.status_code, 401)
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 401)

    def test_logout_invalidates_session(self) -> None:
        self.login()
        rv = self.client.post("/api/auth/logout")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 401)

    def test_status_reflects_auth_state(self) -> None:
        rv = self.client.get("/api/auth/status")
        self.assertEqual(rv.status_code, 200)
        self.assertFalse(rv.get_json()["authenticated"])
        self.login()
        rv = self.client.get("/api/auth/status")
        self.assertTrue(rv.get_json()["authenticated"])
        self.assertEqual(rv.get_json()["user"]["username"], "admin")


class TestFailClosed(AuthTestBase):
    def test_unknown_user_rejected(self) -> None:
        rv = self.login(username="nobody")
        self.assertEqual(rv.status_code, 401)

    def test_inactive_user_rejected(self) -> None:
        with self.Session() as session:
            session.add(
                UserORM(
                    username="disabled",
                    password_hash=generate_password_hash("correct-password"),
                    is_active=False,
                )
            )
            session.commit()
        rv = self.login(username="disabled")
        self.assertEqual(rv.status_code, 401)


class TestReviewerRole(AuthTestBase):
    """评审账户（role=reviewer）：API 白名单收窄，页面不区分。"""

    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session:
            session.add(
                UserORM(
                    username="reviewer",
                    password_hash=generate_password_hash("correct-password"),
                    display_name="评审员",
                    role="reviewer",
                )
            )
            session.commit()

    def test_login_and_status_return_role(self) -> None:
        rv = self.login(username="reviewer")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json()["user"]["role"], "reviewer")
        rv = self.client.get("/api/auth/status")
        self.assertEqual(rv.get_json()["user"]["role"], "reviewer")

    def test_admin_defaults_to_admin_role(self) -> None:
        self.login()
        rv = self.client.get("/api/auth/status")
        self.assertEqual(rv.get_json()["user"]["role"], "admin")

    def test_reviewer_allowed_apis_pass(self) -> None:
        self.login(username="reviewer")
        for path in (
            "/api/scholarship/applications",
            "/api/scholarship/advisor-graph",
            "/api/notifications",
            "/api/config",
            "/api/config/audit",
        ):
            rv = self.client.get(path)
            self.assertEqual(rv.status_code, 200, path)

    def test_reviewer_other_apis_return_403(self) -> None:
        self.login(username="reviewer")
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 403)
        rv = self.client.get("/api/candidates")
        self.assertEqual(rv.status_code, 403)

    def test_reviewer_cannot_write_config(self) -> None:
        self.login(username="reviewer")
        rv = self.client.put("/api/config", json={"LLM_API_KEY": "x"})
        self.assertEqual(rv.status_code, 403)

    def test_reviewer_pages_not_restricted(self) -> None:
        # 页面统一返回 SPA 外壳；可见范围由前端按角色裁剪
        self.login(username="reviewer")
        rv = self.client.get("/dashboard")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/scholarship/graph")
        self.assertEqual(rv.status_code, 200)

    def test_admin_unaffected_by_role_rules(self) -> None:
        self.login()
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/api/candidates")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.put("/api/config", json={"LLM_API_KEY": "x"})
        self.assertEqual(rv.status_code, 200)


if __name__ == "__main__":
    unittest.main()
