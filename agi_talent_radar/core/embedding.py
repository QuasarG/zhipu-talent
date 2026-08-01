"""智谱 Embedding 适配器（阶段 7）。

固定约束（与决策记录 §2.4 对齐）：

- 模型固定 ``embedding-3``；不部署本地 Embedding，不为本地模型预留 Provider 抽象。
- 维度固定 1024。
- 单条输入最多 3072 tokens；超出按字符粗略截断（不报错）。
- 一次请求最多 64 条；切片和批处理必须遵守该限制。
- 调用智谱开放平台 ``/api/paas/v4/embeddings``；
  若 ``Z_AI_API_KEY`` 是开放平台 Key 则与 Web Search 共用。

本模块只在调用真实 API 时才 import openai；测试可注入 fake client。
"""
from __future__ import annotations

import os
from typing import Any, Protocol


EMBEDDING_MODEL = "embedding-3"
EMBEDDING_DIM = 1024
MAX_TOKENS_PER_INPUT = 3072
MAX_INPUTS_PER_BATCH = 64
# 粗略字符上限（按中文 1 字 ≈ 2 token 估算，留余量）。
MAX_CHARS_PER_INPUT = 1400
ZHIPU_EMBEDDINGS_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"


class EmbeddingClient(Protocol):
    """Embedding 调用协议，便于测试注入。"""

    def embed(self, inputs: list[str], model: str) -> list[list[float]]: ...


class ZhipuEmbeddingClient:
    """真实智谱 Embedding 客户端。

    通过 OpenAI 兼容接口调用智谱开放平台。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("Z_AI_API_KEY", "").strip()
        self.base_url = base_url or ZHIPU_EMBEDDINGS_URL
        self.timeout = timeout

    def embed(self, inputs: list[str], model: str = EMBEDDING_MODEL) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("Z_AI_API_KEY 未配置，无法调用智谱 Embedding。")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("缺少 httpx 依赖。") from exc

        truncated = [truncate_input(text) for text in inputs]
        response = httpx.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            # embedding-3 默认返回 2048 维，必须显式指定 dimensions=1024
            json={"model": model, "input": truncated, "dimensions": EMBEDDING_DIM},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data.get("data", [])]


def truncate_input(text: str) -> str:
    """按字符粗略截断到 MAX_CHARS_PER_INPUT，避免超 3072 token。"""
    if not text:
        return ""
    return text[:MAX_CHARS_PER_INPUT]


def chunk_inputs(inputs: list[str]) -> list[list[str]]:
    """按 MAX_INPUTS_PER_BATCH=64 切批。"""
    if not inputs:
        return []
    batches: list[list[str]] = []
    for start in range(0, len(inputs), MAX_INPUTS_PER_BATCH):
        batches.append(inputs[start : start + MAX_INPUTS_PER_BATCH])
    return batches


def embed_texts(
    inputs: list[str],
    client: EmbeddingClient | None = None,
    model: str = EMBEDDING_MODEL,
) -> list[list[float]]:
    """高层入口：自动分批 + 截断 + 调用 client。

    返回顺序与 ``inputs`` 一致的向量列表。
    """
    if not inputs:
        return []
    if client is None:
        client = ZhipuEmbeddingClient()

    vectors: list[list[float]] = []
    for batch in chunk_inputs(inputs):
        batch_vectors = client.embed(batch, model=model)
        for vector in batch_vectors:
            if len(vector) != EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding 维度异常：期望 {EMBEDDING_DIM}，实际 {len(vector)}。"
                    "模型或维度变化时必须重建全部向量索引。"
                )
            vectors.append(vector)
    return vectors


class FakeEmbeddingClient:
    """确定性 fake，用于测试。返回固定 1024 维向量（按文本哈希派生）。"""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim
        self.calls: list[tuple[list[str], str]] = []

    def embed(self, inputs: list[str], model: str = EMBEDDING_MODEL) -> list[list[float]]:
        self.calls.append((list(inputs), model))
        vectors: list[list[float]] = []
        for text in inputs:
            seed = sum((ord(ch) + 1) * (i + 1) for i, ch in enumerate(text or " "))
            vector = [((seed >> (i % 16)) & 0xF) / 15.0 for i in range(self.dim)]
            vectors.append(vector)
        return vectors


__all__ = [
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "MAX_TOKENS_PER_INPUT",
    "MAX_INPUTS_PER_BATCH",
    "MAX_CHARS_PER_INPUT",
    "EmbeddingClient",
    "ZhipuEmbeddingClient",
    "FakeEmbeddingClient",
    "truncate_input",
    "chunk_inputs",
    "embed_texts",
]