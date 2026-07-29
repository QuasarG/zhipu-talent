"""服务器级全局配置 Provider（阶段 8）。

约束（与决策记录 §2.7 对齐）：

- 配置是服务器级全局配置，所有通过内部密码鉴权的使用者共享同一套。
- Key 不得硬编码进代码或前端资源。
- GET 只返回非敏感字段和 Key 的"已配置/未配置"或脱敏状态。
- 浏览器前端不得直接读取或下载 ``.env``。
- ``.env`` 更新走原子替换（阶段 8.3 实装）。

业务代码不再分散直接 ``os.getenv``，统一通过 ``Settings``。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any


# 敏感字段：GET 时只返回脱敏状态，不返回原文。
SENSITIVE_KEYS = frozenset({
    "DEEPSEEK_API_KEY",
    "Z_AI_API_KEY",
    "AMINER_API_TOKEN",
    "QDRANT_API_KEY",
    "DB_PASSWORD",
    "APP_AUTH_PASSWORD",
    "FLASK_SESSION_SECRET",
})

# 设置页可见的非敏感配置：只有 API Key 和模型参数，不含内部基础设施配置。
NON_SENSITIVE_KEYS = frozenset({
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_TIMEOUT_SECONDS",
    "Z_AI_MODE",
    "OPENALEX_MAILTO",
    "EMBEDDING_MODEL",
})


def mask_key(value: str) -> str:
    """脱敏：保留首尾 2 字符，中间用 * 代替。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


@dataclass
class Settings:
    """全局配置快照。"""

    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def is_configured(self, key: str) -> bool:
        return bool((self.values.get(key) or "").strip())

    def to_public_dict(self) -> dict[str, Any]:
        """返回可对外暴露的脱敏配置。

        - 敏感 Key：返回 ``{configured: bool, masked: str}``；
        - 非敏感 Key：返回原值。
        """
        public: dict[str, Any] = {}
        for key in SENSITIVE_KEYS:
            value = self.values.get(key, "")
            public[key] = {
                "configured": bool(value.strip()),
                "masked": mask_key(value) if value else "",
            }
        for key in NON_SENSITIVE_KEYS:
            if key in self.values:
                public[key] = self.values[key]
        return public


class SettingsProvider:
    """进程内 Settings 单例，支持原子刷新。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settings = Settings(values={})

    def load_from_env(self, env: dict[str, str] | None = None) -> Settings:
        """从环境变量（或注入的 env dict）加载。"""
        source = env if env is not None else dict(os.environ)
        relevant_keys = SENSITIVE_KEYS | NON_SENSITIVE_KEYS
        values = {
            key: str(source.get(key, "") or "")
            for key in relevant_keys
            if source.get(key) is not None
        }
        with self._lock:
            self._settings = Settings(values=values)
            return self._settings

    def snapshot(self) -> Settings:
        """返回当前 Settings 的浅拷贝，避免外部修改。"""
        with self._lock:
            return Settings(values=dict(self._settings.values))

    def refresh(self, env: dict[str, str] | None = None) -> Settings:
        """原子刷新；等价于 load_from_env。"""
        return self.load_from_env(env)


# 全局单例
_PROVIDER = SettingsProvider()


def get_settings() -> Settings:
    """获取当前 Settings 快照。首次调用自动从 os.environ 加载。"""
    snapshot = _PROVIDER.snapshot()
    if not snapshot.values:
        _PROVIDER.load_from_env()
    return _PROVIDER.snapshot()


def get_provider() -> SettingsProvider:
    return _PROVIDER


__all__ = [
    "SENSITIVE_KEYS",
    "NON_SENSITIVE_KEYS",
    "mask_key",
    "Settings",
    "SettingsProvider",
    "get_settings",
    "get_provider",
]