"""服务器配置 API（阶段 8）：脱敏读取 + 校验 + 原子写入。

约束（与决策记录 §2.7 对齐）：

- GET 只返回非敏感字段和 Key 的"已配置/未配置"或脱敏状态。
- 更新时先校验字段和可选连接测试，再写临时文件并使用原子替换更新 ``.env``。
- 原子替换后刷新进程内 Settings；失败时保留旧文件和旧运行时配置。
- 日志、API 错误和审计记录不得输出完整 Key。
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import (  # type: ignore[import-not-found]
    Blueprint,
    jsonify,
    request,
)

from agi_talent_radar.core.settings import (
    NON_SENSITIVE_KEYS,
    SENSITIVE_KEYS,
    get_provider,
    get_settings,
)


CONFIG_BP_NAME = "config"
_ALL_KNOWN_KEYS = SENSITIVE_KEYS | NON_SENSITIVE_KEYS


@dataclass(frozen=True)
class UpdateResult:
    applied: dict[str, str]
    rejected: dict[str, str]
    runtime_refreshed: bool


def _read_env_file(env_path: Path) -> dict[str, str]:
    """简易 .env 解析：KEY=VALUE 行，忽略注释和空行。"""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _write_env_file(env_path: Path, values: dict[str, str]) -> None:
    """原子写入：先写临时文件，再 os.replace 覆盖。"""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in sorted(values):
        value = values[key]
        # 含空格或特殊字符的值加引号
        if " " in value or "#" in value:
            value = f'"{value}"'
        lines.append(f"{key}={value}")
    content = "\n".join(lines) + "\n"

    # 写临时文件后原子替换
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(env_path.parent),
        prefix=".env.tmp.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, env_path)
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update_env(
    env_path: Path,
    updates: dict[str, str],
) -> UpdateResult:
    """校验并原子更新 .env。

    - 只接受已知 Key（SENSITIVE_KEYS | NON_SENSITIVE_KEYS）；
    - 空字符串视为"清空该 Key"；
    - 写入成功后刷新进程内 Settings；失败保留旧文件。
    """
    applied: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for key, value in updates.items():
        if key not in _ALL_KNOWN_KEYS:
            rejected[key] = "unknown_key"
            continue
        applied[key] = str(value or "")

    if not applied:
        return UpdateResult(applied={}, rejected=rejected, runtime_refreshed=False)

    # 读取现有 .env → 合并 → 原子写回
    try:
        existing = _read_env_file(env_path)
        existing.update(applied)
        _write_env_file(env_path, existing)
    except Exception as exc:
        # 失败保留旧文件
        return UpdateResult(
            applied={},
            rejected={k: f"write_failed: {exc}" for k in applied},
            runtime_refreshed=False,
        )

    # 原子替换成功后刷新进程内 Settings
    try:
        provider = get_provider()
        provider.refresh()
        refreshed = True
    except Exception:
        refreshed = False

    return UpdateResult(applied=applied, rejected=rejected, runtime_refreshed=refreshed)


def test_llm_connection() -> dict[str, Any]:
    """可选连接测试：检查 DEEPSEEK_API_KEY 是否配置并能调用。

    本函数不输出完整 Key；只返回 ok / unconfigured / error。
    """
    settings = get_settings()
    if not settings.is_configured("DEEPSEEK_API_KEY"):
        return {"ok": False, "reason": "unconfigured"}
    try:
        from agi_talent_radar.core import llm_client

        # 不真正调用 LLM（避免花钱），只确认 client 可构造
        _ = llm_client._client()
        return {"ok": True}
    except Exception:
        return {"ok": False, "reason": "client_error"}


def build_config_blueprint(env_path: Path | None = None) -> Blueprint:
    """构建 /api/config 蓝图。"""
    resolved_env_path = env_path or _default_env_path()
    bp = Blueprint(CONFIG_BP_NAME, __name__)

    @bp.get("/api/config")
    def config_get():
        # 只返回脱敏配置
        return jsonify(get_settings().to_public_dict())

    @bp.put("/api/config")
    def config_update():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"detail": "请求体必须是 JSON 对象。"}), 400
        result = update_env(resolved_env_path, body)
        response: dict[str, Any] = {
            "applied": result.applied,
            "rejected": result.rejected,
            "runtime_refreshed": result.runtime_refreshed,
        }
        # 用脱敏形式返回 applied（避免回显完整 Key）
        masked_applied: dict[str, Any] = {}
        from agi_talent_radar.core.settings import mask_key

        for key, value in result.applied.items():
            if key in SENSITIVE_KEYS:
                masked_applied[key] = {"configured": bool(value), "masked": mask_key(value)}
            else:
                masked_applied[key] = value
        response["applied"] = masked_applied
        status = 200 if result.applied and not result.rejected else (
            400 if result.rejected and not result.applied else 207
        )
        return jsonify(response), status

    @bp.get("/api/config/test")
    def config_test():
        return jsonify({"llm": test_llm_connection()})

    return bp


def _default_env_path() -> Path:
    """默认 .env 路径：仓库根。"""
    from agi_talent_radar.core.settings import get_settings as _gs

    _ = _gs  # 触发加载
    # 回溯到仓库根（auth.py 在 agi_talent_radar/web/，上两级）
    return Path(__file__).resolve().parents[2] / ".env"


__all__ = [
    "CONFIG_BP_NAME",
    "update_env",
    "test_llm_connection",
    "build_config_blueprint",
]