"""鉴权 middleware 与会话管理（阶段 8）。

约束（与决策记录 §2.6 对齐）：

- 平台是内部工具，使用一个密码完成访问鉴权。
- 鉴权成功后获得平台全部信息与功能权限，不做字段级过滤。
- 除登录接口和健康检查外，所有页面、后端 API 和 SSE 流都必须鉴权。
- 访问密码从环境变量读取，不得写入前端或提交到仓库。
- 登录成功后使用服务端签名的会话 Cookie，支持会话过期和主动退出。
- 未鉴权的 API 返回 ``401``；未鉴权的页面请求跳转登录页。
"""
from __future__ import annotations

import os
import time
from functools import wraps
from typing import Any, Callable

from flask import (  # type: ignore[import-not-found]
    Blueprint,
    current_app,
    jsonify,
    redirect,
    request,
    session,
)


AUTH_BP_NAME = "auth"
SESSION_KEY_AUTHED = "authed_at"
SESSION_KEY_EXPIRES = "auth_expires_at"
SESSION_KEY_USER_ID = "user_id"
DEFAULT_SESSION_TTL_SECONDS = 8 * 3600  # 8 小时


def _read_session_secret() -> str:
    return os.getenv("FLASK_SESSION_SECRET", "").strip()


def _read_session_ttl() -> int:
    raw = os.getenv("APP_SESSION_TTL_SECONDS", "").strip()
    try:
        return int(raw) if raw else DEFAULT_SESSION_TTL_SECONDS
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS


def is_authenticated() -> bool:
    """检查当前会话是否已鉴权且未过期。"""
    authed_at = session.get(SESSION_KEY_AUTHED)
    expires_at = session.get(SESSION_KEY_EXPIRES)
    if not authed_at or not expires_at:
        return False
    if time.time() > float(expires_at):
        return False
    return True


def current_user():
    """返回当前登录用户 ORM，未登录返回 None。

    从 session 取 user_id 后查 DB；结果缓存到 flask.g.current_user。
    """
    from flask import g

    cached = getattr(g, "current_user", None)
    if cached is not None:
        return cached

    user_id = session.get(SESSION_KEY_USER_ID)
    if not user_id:
        return None

    from agi_talent_radar.core.database import get_session
    from agi_talent_radar.core.db.orm import UserORM

    with get_session() as db_session:
        user = db_session.get(UserORM, user_id)
        if user and user.is_active:
            g.current_user = user
            return user
    return None


def login(username: str, password: str) -> bool:
    """用户名+密码登录。成功写入会话；失败返回 False。"""
    if not username or not password:
        return False

    from werkzeug.security import check_password_hash

    from agi_talent_radar.core.database import get_session
    from agi_talent_radar.core.db.orm import UserORM

    with get_session() as db_session:
        user = db_session.query(UserORM).filter_by(username=username.strip()).first()
        if not user or not user.is_active:
            return False
        if not check_password_hash(user.password_hash, password):
            return False

    ttl = _read_session_ttl()
    now = time.time()
    session[SESSION_KEY_AUTHED] = now
    session[SESSION_KEY_EXPIRES] = now + ttl
    session[SESSION_KEY_USER_ID] = user.id
    session.permanent = True
    return True


def logout() -> None:
    """主动退出：清除会话。"""
    session.pop(SESSION_KEY_AUTHED, None)
    session.pop(SESSION_KEY_EXPIRES, None)
    session.pop(SESSION_KEY_USER_ID, None)
    session.clear()


def require_auth(view: Callable) -> Callable:
    """API 装饰器：未鉴权返回 401 JSON。"""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if is_authenticated():
            return view(*args, **kwargs)
        return jsonify({"detail": "未鉴权，请先登录。"}), 401

    return wrapper


def require_auth_page(view: Callable) -> Callable:
    """页面装饰器：未鉴权跳转登录页。"""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if is_authenticated():
            return view(*args, **kwargs)
        return redirect("/login")

    return wrapper


# 不需要鉴权的路径前缀（白名单）。
PUBLIC_PATHS = frozenset({"/login", "/api/auth/login", "/api/auth/status", "/health"})
# 前缀白名单：只读分享页与其公开数据 API（凭随机 token 自证，不走会话）
PUBLIC_PREFIXES = ("/share/", "/api/share/")


def install_auth_middleware(app) -> None:
    """在 Flask app 上注册统一鉴权 before_request。

    - 白名单路径放行；
    - API 路径（/api/...）未鉴权返回 401 JSON；
    - 其他页面未鉴权跳转 /login；
    - SSE 流（/api/.../evaluate 等）同样要求鉴权。
    """

    @app.before_request
    def _check_auth():
        path = request.path
        # 白名单
        if path in PUBLIC_PATHS or path.startswith(("/static/",) + PUBLIC_PREFIXES):
            return None
        if is_authenticated():
            return None
        # 未鉴权
        accept = request.headers.get("Accept", "")
        if path.startswith("/api/"):
            return jsonify({"detail": "未鉴权，请先登录。"}), 401
        if "text/html" in accept or request.method == "GET":
            return redirect("/login")
        return jsonify({"detail": "未鉴权。"}), 401


def build_auth_blueprint() -> Blueprint:
    """构建 /api/auth 蓝图：login / logout / status。"""
    bp = Blueprint(AUTH_BP_NAME, __name__)

    @bp.post("/api/auth/login")
    def auth_login():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        if login(username, password):
            user = current_user()
            return jsonify({
                "authenticated": True,
                "user": {"id": user.id, "username": user.username, "display_name": user.display_name}
                if user
                else None,
            })
        return jsonify({"detail": "用户名或密码错误。"}), 401

    @bp.post("/api/auth/logout")
    def auth_logout():
        logout()
        return jsonify({"authenticated": False})

    @bp.get("/api/auth/status")
    def auth_status():
        authed = is_authenticated()
        user = current_user() if authed else None
        return jsonify({
            "authenticated": authed,
            "user": {"id": user.id, "username": user.username, "display_name": user.display_name}
            if user
            else None,
        })

    @bp.get("/login")
    def login_page():
        # SPA 模式：React Router 接管登录页。
        # 未鉴权时 redirect /login，React App.tsx 显示 Login 组件。
        from pathlib import Path
        import os
        from flask import current_app, render_template

        dist_dir = Path(current_app.static_folder) / "dist"
        vite_dev = os.getenv("VITE_DEV", "").strip() == "1"
        dist_assets: list[str] = []
        if not vite_dev and dist_dir.exists():
            assets_dir = dist_dir / "assets"
            if assets_dir.exists():
                dist_assets = [f"assets/{f.name}" for f in assets_dir.iterdir() if f.suffix in (".js", ".css")]
        return render_template("index.html", vite_dev=vite_dev, dist_assets=dist_assets)

    @bp.get("/health")
    def health():
        # 阶段 11：分开报告每个外部服务可用性。
        # MySQL 失败 = 应用宕机；可选服务失败 = degraded。
        from agi_talent_radar.core.health import get_cached_health

        report = get_cached_health()
        status_code = 200 if report.overall != "down" else 503
        return jsonify(report.to_dict()), status_code

    return bp


def configure_app_session(app) -> None:
    """配置 Flask session secret。

    未配置 FLASK_SESSION_SECRET 时打印警告（不崩溃，便于本地开发）。
    生产环境必须配置。
    """
    secret = _read_session_secret()
    if not secret:
        import warnings

        warnings.warn(
            "FLASK_SESSION_SECRET 未配置；生产环境必须设置后才能安全启用会话。",
            stacklevel=2,
        )
        # 本地兜底：用进程内随机值（重启后失效）
        import secrets as _secrets

        secret = _secrets.token_hex(32)
    app.secret_key = secret


__all__ = [
    "AUTH_BP_NAME",
    "PUBLIC_PATHS",
    "is_authenticated",
    "current_user",
    "login",
    "logout",
    "require_auth",
    "require_auth_page",
    "install_auth_middleware",
    "build_auth_blueprint",
    "configure_app_session",
]