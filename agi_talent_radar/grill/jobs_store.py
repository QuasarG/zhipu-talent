"""grill 岗位检索：复用项目 embedding + QdrantVectorStore，独立 collection grill_jobs。

向量数据进同一个 docker Qdrant 实例；完整 JD 从岗位 JSON 内存 dict 回补。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agi_talent_radar.core.embedding import embed_texts
from agi_talent_radar.core.vector_store import CURRENT_INDEX_VERSION, QdrantVectorStore, VectorPoint

# 岗位 payload 契约（与人才知识库 PAYLOAD_REQUIRED_KEYS 不同，故 VectorPoint 显式传此契约）
GRILL_JOB_PAYLOAD_KEYS = (
    "job_id",
    "title",
    "job_category",
    "city_info",
    "recruit_type",
    "requirement_excerpt",
    "index_version",
)

GRILL_COLLECTION = "grill_jobs"

_STORE: QdrantVectorStore | None = None
_FULL_JOBS: dict[str, dict] | None = None
# 完整 JD 源数据（入库同一来源，只读回补 description/requirement）
_DEFAULT_FULL = Path(__file__).resolve().parents[2] / "data" / "grill" / "jobs" / "zhipu_jobs_all.json"
_FULL_PATH = Path(os.getenv("GRILL_JOBS_FULL_JSON", "") or _DEFAULT_FULL)


def _full_jobs() -> dict[str, dict]:
    global _FULL_JOBS
    if _FULL_JOBS is None:
        if not _FULL_PATH.exists():
            raise RuntimeError(
                f"完整岗位数据不存在：{_FULL_PATH}（先跑 scripts/ingest_grill_jobs.py）"
            )
        raw = json.load(open(_FULL_PATH, encoding="utf-8"))
        records = raw["jobs"] if isinstance(raw, dict) else raw
        _FULL_JOBS = {str(r["id"]): r for r in records}
    return _FULL_JOBS


def get_store() -> QdrantVectorStore:
    global _STORE
    if _STORE is None:
        _STORE = QdrantVectorStore(collection=GRILL_COLLECTION)
    return _STORE


def search_jobs(
    query: str,
    top_k: int = 5,
    job_category: str | None = None,
    score_threshold: float = 0.3,
) -> list[dict[str, Any]]:
    """向量检索真实校招岗位；失败时返回空列表（检索只影响话术不伤主链路）。"""
    vector = embed_texts([query])[0]
    filters = {"job_category": job_category} if job_category else None
    hits = get_store().search(vector, top_k=top_k, filters=filters)
    jobs = []
    for hit in hits:
        if hit.score < score_threshold:
            continue
        p = hit.payload
        full = _full_jobs().get(str(p.get("job_id"))) or {}
        jobs.append({
            "job_id": p.get("job_id"),
            "title": p.get("title"),
            "job_category": p.get("job_category"),
            "city_info": p.get("city_info"),
            "recruit_type": p.get("recruit_type"),
            "requirement_excerpt": p.get("requirement_excerpt"),
            "description": full.get("description") or "",
            "requirement": full.get("requirement") or "",
            "score": round(hit.score, 4),
        })
    return jobs


def indexed_count() -> int:
    return get_store().count()


def full_job(job_id: str) -> dict | None:
    return _full_jobs().get(str(job_id))


def find_by_title(title: str) -> dict | None:
    for r in _full_jobs().values():
        if (r.get("title") or "") == title:
            return r
    return None


def build_point(rec: dict, vector: list[float]) -> VectorPoint:
    """入库辅助：构造带岗位 payload 契约的 VectorPoint。"""
    city_names = _join_city(rec)
    # Qdrant point ID 只接受 unsigned int 或 UUID；job_id 是数字串，转 int 以确定性覆盖
    try:
        pid: int | str = int(rec["id"])
        if pid < 0:
            raise ValueError
    except (TypeError, ValueError):
        import uuid

        pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(rec["id"])))
    return VectorPoint(
        vector=vector,
        payload={
            "job_id": str(rec["id"]),
            "title": rec.get("title") or "",
            "job_category": _category_name(rec),
            "city_info": city_names,
            "recruit_type": _recruit_name(rec),
            "requirement_excerpt": (rec.get("requirement") or "")[:300],
            "index_version": CURRENT_INDEX_VERSION,
        },
        point_id=pid,
        required_keys=GRILL_JOB_PAYLOAD_KEYS,
    )


def _category_name(rec: dict) -> str:
    cat = rec.get("job_category")
    return str(cat.get("name") or "") if isinstance(cat, dict) else str(cat or "")


def _recruit_name(rec: dict) -> str:
    rt = rec.get("recruit_type")
    return str(rt.get("name") or "") if isinstance(rt, dict) else str(rt or "")


def _join_city(rec: dict) -> str:
    info = rec.get("city_info")
    if isinstance(info, dict):
        info = [info]
    if isinstance(info, list):
        names = [str(c.get("name") or "") for c in info if isinstance(c, dict)]
        return "/".join(n for n in names if n)
    return str(info or "")


__all__ = [
    "GRILL_COLLECTION",
    "GRILL_JOB_PAYLOAD_KEYS",
    "get_store",
    "search_jobs",
    "indexed_count",
    "full_job",
    "find_by_title",
    "build_point",
]
