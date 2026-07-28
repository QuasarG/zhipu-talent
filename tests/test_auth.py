"""鉴权 middleware + /api/auth 测试。

覆盖（与决策记录 §2.6 对齐）：

1. 未登录访问 /api/* 返回 401。
2. 未登录访问页面跳转 /login。
3. 登录成功后可访问受保护资源。
4. 错误密码登录失败。
5. logout 后会话失效。
6. 白名单路径（/login /api/auth/login /health）无需鉴权。
7. 未配置 APP_AUTH_PASSWORD 时禁止任何登录（fail-closed）。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from agi_talent_radar.web.auth import (
    build_auth_blueprint,
    configure_app_session,
    install_auth_middleware,
)


def _make_app() -> Flask:
    app = Flask(__name__)
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

    return app


class TestAuthMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        self.patch_pw = patch(
            "agi_talent_radar.web.auth._read_auth_password",
            return_value="correct-password",
        )
        self.patch_pw.start()
        self.app = _make_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.patch_pw.stop()

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
        rv = self.client.post(
            "/api/auth/login",
            json={"password": "correct-password"},
        )
        self.assertEqual(rv.status_code, 200)
        # 同一会话访问受保护资源
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 200)

    def test_wrong_password_rejected(self) -> None:
        rv = self.client.post(
            "/api/auth/login",
            json={"password": "wrong"},
        )
        self.assertEqual(rv.status_code, 401)
        # 仍未登录
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 401)

    def test_logout_invalidates_session(self) -> None:
        self.client.post("/api/auth/login", json={"password": "correct-password"})
        rv = self.client.post("/api/auth/logout")
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/api/protected")
        self.assertEqual(rv.status_code, 401)

    def test_status_reflects_auth_state(self) -> None:
        rv = self.client.get("/api/auth/status")
        self.assertEqual(rv.status_code, 200)
        self.assertFalse(rv.get_json()["authenticated"])
        self.client.post("/api/auth/login", json={"password": "correct-password"})
        rv = self.client.get("/api/auth/status")
        self.assertTrue(rv.get_json()["authenticated"])


class TestFailClosed(unittest.TestCase):
    def test_unconfigured_password_blocks_login(self) -> None:
        with patch(
            "agi_talent_radar.web.auth._read_auth_password",
            return_value="",
        ):
            app = _make_app()
            client = app.test_client()
            rv = client.post("/api/auth/login", json={"password": "anything"})
            self.assertEqual(rv.status_code, 401)


if __name__ == "__main__":
    unittest.main()