"""健康检查（阶段 11）：分开报告每个外部服务可用性。

约束（与决策记录 §阶段 11 对齐）：

- MySQL 是业务真源，失败 = 应用宕机；
- Qdrant / LLM / Embedding / AMiner / OpenAlex / Web Search 是可选外部服务，
  失败不伪装成应用宕机，只标记 ``degraded``；
- 不输出完整 Key；
- 探测超时短（默认 5 秒），避免拖慢健康检查。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ServiceHealth:
    """单个服务的健康状态。"""

    name: str
    status: str          # ok / degraded / down
    required: bool       # True = 失败算应用宕机
    detail: str = ""
    latency_ms: float = 0.0


@dataclass(frozen=True)
class HealthReport:
    """整体健康报告。"""

    overall: str         # ok / degraded / down
    services: list[ServiceHealth] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "checked_at": self.checked_at,
            "services": [
                {
                    "name": s.name,
                    "status": s.status,
                    "required": s.required,
                    "detail": s.detail,
                    "latency_ms": round(s.latency_ms, 1),
                }
                for s in self.services
            ],
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _probe(name: str, required: bool, fn: Callable[[], str], timeout: float) -> ServiceHealth:
    """执行单个探测，捕获异常并计时。"""
    import time

    start = time.monotonic()
    try:
        detail = fn()
        latency = (time.monotonic() - start) * 1000
        return ServiceHealth(
            name=name,
            status="ok",
            required=required,
            detail=detail or "",
            latency_ms=latency,
        )
    except Exception as exc:  # noqa: BLE001
        latency = (time.monotonic() - start) * 1000
        status = "down" if required else "degraded"
        return ServiceHealth(
            name=name,
            status=status,
            required=required,
            detail=str(exc)[:200],
            latency_ms=latency,
        )


def check_mysql() -> str:
    """MySQL 是业务真源，失败 = 应用宕机。"""
    from sqlalchemy import text

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        session.execute(text("SELECT 1"))
    return "connected"


def check_qdrant() -> str:
    """Qdrant 可选；未配置时返回 'not_configured'（status=ok，不强制）。"""
    url = os.getenv("QDRANT_URL", "").strip()
    if not url:
        return "not_configured"
    from agi_talent_radar.core.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    count = store.count()
    return f"connected ({count} points)"


def check_llm() -> str:
    """LLM 探测：检查 API Key 是否配置（不真正调用，避免花钱）。"""
    from agi_talent_radar.core.settings import get_settings

    settings = get_settings()
    if not (settings.is_configured("LLM_API_KEY") or settings.is_configured("DEEPSEEK_API_KEY")):
        return "unconfigured"
    return "configured"


def check_embedding() -> str:
    """Embedding 探测：检查 LLM_API_KEY 是否配置。"""
    from agi_talent_radar.core.settings import get_settings

    settings = get_settings()
    if not (settings.is_configured("LLM_API_KEY") or settings.is_configured("Z_AI_API_KEY")):
        return "unconfigured"
    return "configured"


def check_aminer() -> str:
    """AMiner REST 连接测试：用 person_search 查一个知名学者。"""
    try:
        from agi_talent_radar.core.connectors.aminer_rest import check_aminer_connection

        result = check_aminer_connection()
        if result == "ok":
            return "connected"
        return result
    except Exception as exc:
        return f"error: {exc}"


def check_openalex() -> str:
    """OpenAlex 探测：无需 key，检查网络可达。"""
    import httpx

    rv = httpx.get("https://api.openalex.org/works?per-page=1", timeout=DEFAULT_TIMEOUT_SECONDS)
    rv.raise_for_status()
    return "reachable"


def check_crossref() -> str:
    """CrossRef 探测：无需 key，检查网络可达。"""
    import httpx

    rv = httpx.get("https://api.crossref.org/works?rows=1", timeout=DEFAULT_TIMEOUT_SECONDS)
    rv.raise_for_status()
    return "reachable"


def check_arxiv() -> str:
    """arXiv 探测：无需 key，检查网络可达。"""
    import httpx

    rv = httpx.get(
        "https://export.arxiv.org/api/query",
        params={"search_query": "all:test", "max_results": 1},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    rv.raise_for_status()
    return "reachable"


def check_web_search() -> str:
    """智谱 Web Search 探测：检查 LLM_API_KEY 是否配置。"""
    from agi_talent_radar.core.settings import get_settings

    settings = get_settings()
    if not (settings.is_configured("LLM_API_KEY") or settings.is_configured("Z_AI_API_KEY")):
        return "unconfigured"
    return "configured"


def run_health_check(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HealthReport:
    """执行全部探测，返回 HealthReport。

    overall 规则：
    - 任一 required 服务 down → overall=down
    - 任一可选服务 degraded 但无 required down → overall=degraded
    - 全部 ok 或 not_configured → overall=ok
    """
    probes: list[tuple[str, bool, Callable[[], str]]] = [
        ("mysql", True, check_mysql),
        ("qdrant", False, check_qdrant),
        ("llm", False, check_llm),
        ("embedding", False, check_embedding),
        ("aminer", False, check_aminer),
        ("crossref", False, check_crossref),
        ("arxiv", False, check_arxiv),
        ("openalex", False, check_openalex),
        ("web_search", False, check_web_search),
    ]

    services = [_probe(name, required, fn, timeout) for name, required, fn in probes]

    any_required_down = any(s.status == "down" for s in services if s.required)
    any_degraded = any(s.status == "degraded" for s in services)
    if any_required_down:
        overall = "down"
    elif any_degraded:
        overall = "degraded"
    else:
        overall = "ok"

    return HealthReport(overall=overall, services=services, checked_at=_now_iso())


__all__ = [
    "ServiceHealth",
    "HealthReport",
    "check_mysql",
    "check_qdrant",
    "check_llm",
    "check_embedding",
    "check_aminer",
    "check_openalex",
    "check_web_search",
    "run_health_check",
]