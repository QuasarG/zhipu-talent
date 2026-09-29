"""鉴权 middleware 与会话管理（阶段 8）。

约束（与决策记录 §2.6 对齐）：

- 平台是内部工具，使用账号密码完成访问鉴权。
- 鉴权成功后获得平台全部信息与功能权限，不做字段级过滤。
- 角色只有两档：admin（默认，全功能）与 reviewer（奖学金评审账户，
  只能用奖学金、通知与设置（只读配置）相关的 API；其余 /api/* 返回 403）。
  页面本身不做服务端区分（SPA 同一外壳），可见范围由前端按角色裁剪，
  API 层的 403 才是真正的安全边界。
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

ROLE_ADMIN = "admin"
ROLE_REVIEWER = "reviewer"


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


def user_role(user) -> str:
    """读取用户角色；老数据/未知值一律按 admin 处理（fail-open 只面向既有账号）。"""
    role = getattr(user, "role", None)
    return role if role in (ROLE_ADMIN, ROLE_REVIEWER) else ROLE_ADMIN


# 不需要鉴权的路径前缀（白名单）。
PUBLIC_PATHS = frozenset({"/login", "/api/auth/login", "/api/auth/status", "/health"})
# 前缀白名单：只读分享页与其公开数据 API（凭随机 token 自证，不走会话）
# materials-file：视觉 API 拉取视频/图片做转译（webhook token 自证 + 扩展名白名单）
PUBLIC_PREFIXES = (
    "/share/",
    "/api/share/",
    "/api/scholarship/feishu-webhook/",
    "/api/scholarship/materials-file/",
)

# reviewer 可用的 API 前缀：奖学金全流程 + 通知中心 + 会话自身。
# 设置页只读配置走 /api/config*（GET），写配置（PUT）不放行。
REVIEWER_ALLOWED_API_PREFIXES = (
    "/api/auth",
    "/api/scholarship",
    "/api/notifications",
)


def _reviewer_api_allowed(path: str) -> bool:
    if path.startswith(REVIEWER_ALLOWED_API_PREFIXES):
        return True
    # 设置页展示脱敏配置与审计记录：只读放行，写操作由 config_update 再拦一道
    if path.startswith("/api/config") and request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    return False


def install_auth_middleware(app) -> None:
    """在 Flask app 上注册统一鉴权 before_request。

    - 白名单路径放行；
    - API 路径（/api/...）未鉴权返回 401 JSON；
    - 其他页面未鉴权跳转 /login；
    - SSE 流（/api/.../evaluate 等）同样要求鉴权；
    - reviewer 角色只放行奖学金/通知/会话与只读配置 API，其余 /api/* 返回 403。
    """

    @app.before_request
    def _check_auth():
        path = request.path
        # 白名单
        if path in PUBLIC_PATHS or path.startswith(("/static/",) + PUBLIC_PREFIXES):
            return None
        user = current_user() if is_authenticated() else None
        if user is None:
            # 未鉴权
            accept = request.headers.get("Accept", "")
            if path.startswith("/api/"):
                return jsonify({"detail": "未鉴权，请先登录。"}), 401
            if "text/html" in accept or request.method == "GET":
                return redirect("/login")
            return jsonify({"detail": "未鉴权。"}), 401
        # 已鉴权：reviewer 的 API 访问范围收窄（页面不区分，SPA 外壳统一）
        if user_role(user) == ROLE_REVIEWER and path.startswith("/api/") and not _reviewer_api_allowed(path):
            return jsonify({"detail": "评审账户无权访问该功能。"}), 403
        return None


def _user_payload(user) -> dict | None:
    """login/status 共用的用户信息（含角色，前端据此裁剪导航与路由）。"""
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user_role(user),
    }


def build_auth_blueprint() -> Blueprint:
    """构建 /api/auth 蓝图：login / logout / status。"""
    bp = Blueprint(AUTH_BP_NAME, __name__)

    @bp.post("/api/auth/login")
    def auth_login():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        if login(username, password):
            return jsonify({"authenticated": True, "user": _user_payload(current_user())})
        return jsonify({"detail": "用户名或密码错误。"}), 401

    @bp.post("/api/auth/logout")
    def auth_logout():
        logout()
        return jsonify({"authenticated": False})

    @bp.get("/api/auth/status")
    def auth_status():
        authed = is_authenticated()
        user = current_user() if authed else None
        return jsonify({"authenticated": authed, "user": _user_payload(user)})

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
        if not vite_dev:
            from agi_talent_radar.web.spa_assets import list_dist_assets

            dist_assets = list_dist_assets(dist_dir)
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
    """配置 Flask session secret 与 Cookie 安全属性。

    未配置 FLASK_SESSION_SECRET 时打印警告（不崩溃，便于本地开发）。
    生产环境必须配置。

    Cookie 安全属性：
    - HttpOnly + SameSite=Lax 默认开启；
    - Secure 由 FLASK_SESSION_COOKIE_SECURE=1 显式开启（HTTPS 部署时设置；
      裸 HTTP 下开 Secure 会导致 Cookie 无法下发，因此不默认开）。
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
    import os as _os

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_os.getenv("FLASK_SESSION_COOKIE_SECURE", "0") == "1",
    )


__all__ = [
    "AUTH_BP_NAME",
    "PUBLIC_PATHS",
    "ROLE_ADMIN",
    "ROLE_REVIEWER",
    "user_role",
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
