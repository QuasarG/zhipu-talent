"""Qdrant 向量数据库适配器（阶段 7）。

约束（与决策记录 §2.4 对齐）：

- Qdrant 只保存可重建的文本块向量、检索 payload 和对应 MySQL 记录 ID；
- payload 至少包含：person_id / candidate_id / record_type / record_id /
  fact_status / source / fetched_at / index_version；
- collection 名称带 index_version 后缀，模型 / 维度变化时新建 collection；
- ``qdrant-client`` 为可选依赖：未安装时 import 不报错，调用时抛 RuntimeError。
- 测试用 InMemoryVectorStore 替代真实 Qdrant。
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Protocol


CURRENT_INDEX_VERSION = "v1"
DEFAULT_COLLECTION = "talent_knowledge"
PAYLOAD_REQUIRED_KEYS = (
    "person_id",
    "candidate_id",
    "record_type",
    "record_id",
    "fact_status",
    "source",
    "fetched_at",
    "index_version",
)


class VectorStore(Protocol):
    """向量存储协议，便于测试注入。"""

    def ensure_collection(self, dim: int) -> None: ...

    def upsert(self, points: list["VectorPoint"]) -> int: ...

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list["SearchHit"]: ...

    def delete_by_record(self, record_type: str, record_id: str) -> int: ...

    def delete_by_filter(self, filters: dict[str, Any]) -> int: ...

    def count(self) -> int: ...


class VectorPoint:
    """一条向量记录：id + vector + payload。"""

    def __init__(
        self,
        vector: list[float],
        payload: dict[str, Any],
        point_id: str | None = None,
    ) -> None:
        self.vector = vector
        self.payload = payload
        self.point_id = point_id or uuid.uuid4().hex

    def validate_payload(self) -> None:
        missing = [key for key in PAYLOAD_REQUIRED_KEYS if key not in self.payload]
        if missing:
            raise ValueError(f"payload 缺少必需字段：{missing}")


class SearchHit:
    def __init__(self, point_id: str, score: float, payload: dict[str, Any]) -> None:
        self.point_id = point_id
        self.score = score
        self.payload = payload


class QdrantVectorStore:
    """真实 Qdrant 客户端封装。

    通过 ``QDRANT_URL`` / ``QDRANT_API_KEY`` / ``QDRANT_COLLECTION`` 连接。
    未安装 qdrant-client 或未配置 URL 时，调用抛 RuntimeError。
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        collection: str | None = None,
    ) -> None:
        self.url = url or os.getenv("QDRANT_URL", "").strip()
        self.api_key = api_key or os.getenv("QDRANT_API_KEY", "").strip()
        base_collection = collection or os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION)
        self.collection = f"{base_collection}_{CURRENT_INDEX_VERSION}"
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.url:
            raise RuntimeError(
                "QDRANT_URL 未配置；Qdrant 不可用时请从 MySQL 重建。"
            )
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "缺少 qdrant-client 依赖；pip install qdrant-client 后重试。"
            ) from exc
        self._client = QdrantClient(url=self.url, api_key=self.api_key or None)
        return self._client

    def ensure_collection(self, dim: int) -> None:
        from qdrant_client.http.exceptions import UnexpectedResponse

        client = self._get_client()
        try:
            client.get_collection(self.collection)
        except (UnexpectedResponse, Exception):
            client.recreate_collection(
                collection_name=self.collection,
                vectors_config={"size": dim, "distance": "Cosine"},
            )

    def upsert(self, points: list[VectorPoint]) -> int:
        if not points:
            return 0
        for point in points:
            point.validate_payload()
        client = self._get_client()
        client.upsert(
            collection_name=self.collection,
            points=[
                {
                    "id": point.point_id,
                    "vector": point.vector,
                    "payload": point.payload,
                }
                for point in points
            ],
        )
        return len(points)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        client = self._get_client()
        result = client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=_to_qdrant_filter(filters) if filters else None,
        )
        return [
            SearchHit(
                point_id=str(hit.id),
                score=float(hit.score),
                payload=dict(hit.payload or {}),
            )
            for hit in result
        ]

    def delete_by_record(self, record_type: str, record_id: str) -> int:
        return self.delete_by_filter({"record_type": record_type, "record_id": record_id})

    def delete_by_filter(self, filters: dict[str, Any]) -> int:
        client = self._get_client()
        client.delete(
            collection_name=self.collection,
            points_selector=_to_qdrant_filter(filters),
        )
        return 0

    def count(self) -> int:
        client = self._get_client()
        result = client.count(collection_name=self.collection, exact=True)
        return int(result.count)


def _to_qdrant_filter(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "must": [
            {"key": key, "match": {"value": value}}
            for key, value in filters.items()
        ]
    }


class InMemoryVectorStore:
    """进程内 fake 向量存储，用于测试。

    简单余弦相似度检索；不做 ANN 优化。
    """

    def __init__(self) -> None:
        self._points: dict[str, VectorPoint] = {}
        self._collection_dim: int | None = None

    def ensure_collection(self, dim: int) -> None:
        self._collection_dim = dim

    def upsert(self, points: list[VectorPoint]) -> int:
        for point in points:
            point.validate_payload()
            self._points[point.point_id] = point
        return len(points)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        scored: list[tuple[float, VectorPoint]] = []
        for point in self._points.values():
            if filters and not _match_filters(point.payload, filters):
                continue
            score = _cosine(query_vector, point.vector)
            scored.append((score, point))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            SearchHit(point_id=point.point_id, score=score, payload=dict(point.payload))
            for score, point in scored[:top_k]
        ]

    def delete_by_record(self, record_type: str, record_id: str) -> int:
        return self.delete_by_filter({"record_type": record_type, "record_id": record_id})

    def delete_by_filter(self, filters: dict[str, Any]) -> int:
        to_remove = [
            pid
            for pid, point in self._points.items()
            if all(str(point.payload.get(key)) == str(value) for key, value in filters.items())
        ]
        for pid in to_remove:
            del self._points[pid]
        return len(to_remove)

    def count(self) -> int:
        return len(self._points)


def _match_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(payload.get(key) == value for key, value in filters.items())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = [
    "CURRENT_INDEX_VERSION",
    "DEFAULT_COLLECTION",
    "PAYLOAD_REQUIRED_KEYS",
    "VectorStore",
    "VectorPoint",
    "SearchHit",
    "QdrantVectorStore",
    "InMemoryVectorStore",
]
