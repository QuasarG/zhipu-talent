"""智谱 Embedding 适配器测试。

覆盖（与计划 §阶段 7 验收对齐）：

1. batch 切分严格遵守 64 条限制。
2. 单条输入按 MAX_CHARS_PER_INPUT 截断。
3. embed_texts 自动分批 + 维度校验。
4. 维度异常时抛 ValueError（提示重建索引）。
5. FakeEmbeddingClient 确定性可复现。
"""
from __future__ import annotations

import unittest

from agi_talent_radar.core.embedding import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MAX_CHARS_PER_INPUT,
    MAX_INPUTS_PER_BATCH,
    FakeEmbeddingClient,
    ZhipuEmbeddingClient,
    chunk_inputs,
    embed_texts,
    truncate_input,
)


class TestBatching(unittest.TestCase):
    def test_chunk_respects_64_limit(self) -> None:
        inputs = [f"text-{i}" for i in range(200)]
        batches = chunk_inputs(inputs)
        for batch in batches[:-1]:
            self.assertLessEqual(len(batch), MAX_INPUTS_PER_BATCH)
        # 200 / 64 = 4 batches（最后一个 200 - 64*3 = 8 条）
        self.assertEqual(len(batches), 4)
        self.assertEqual(len(batches[-1]), 8)
        # 总数一致
        flat = [text for batch in batches for text in batch]
        self.assertEqual(flat, inputs)

    def test_empty_inputs_returns_empty(self) -> None:
        self.assertEqual(chunk_inputs([]), [])


class TestTruncate(unittest.TestCase):
    def test_truncates_long_input(self) -> None:
        long_text = "a" * (MAX_CHARS_PER_INPUT + 1000)
        truncated = truncate_input(long_text)
        self.assertEqual(len(truncated), MAX_CHARS_PER_INPUT)

    def test_keeps_short_input(self) -> None:
        self.assertEqual(truncate_input("short"), "short")
        self.assertEqual(truncate_input(""), "")


class TestEmbedTexts(unittest.TestCase):
    def test_auto_batches_and_returns_in_order(self) -> None:
        client = FakeEmbeddingClient()
        inputs = [f"text-{i}" for i in range(70)]  # 跨 2 个 batch
        vectors = embed_texts(inputs, client=client)
        self.assertEqual(len(vectors), 70)
        # 每个 batch 调一次
        self.assertEqual(len(client.calls), 2)
        # 维度正确
        for vector in vectors:
            self.assertEqual(len(vector), EMBEDDING_DIM)
        # 顺序保持
        self.assertEqual(vectors[0], client.calls[0][0][0:1] and vectors[0])

    def test_dimension_mismatch_raises(self) -> None:
        class WrongDimClient:
            def embed(self, inputs, model=EMBEDDING_MODEL):
                return [[0.1, 0.2] for _ in inputs]

        with self.assertRaises(ValueError) as ctx:
            embed_texts(["x"], client=WrongDimClient())  # type: ignore[arg-type]
        self.assertIn("维度异常", str(ctx.exception))

    def test_empty_inputs_returns_empty(self) -> None:
        self.assertEqual(embed_texts([], client=FakeEmbeddingClient()), [])


class TestFakeEmbeddingDeterminism(unittest.TestCase):
    def test_same_text_same_vector(self) -> None:
        client = FakeEmbeddingClient()
        v1 = client.embed(["hello"])[0]
        v2 = client.embed(["hello"])[0]
        self.assertEqual(v1, v2)

    def test_different_text_different_vector(self) -> None:
        client = FakeEmbeddingClient()
        v1 = client.embed(["hello"])[0]
        v2 = client.embed(["world"])[0]
        self.assertNotEqual(v1, v2)


class TestZhipuClientConfig(unittest.TestCase):
    def test_missing_api_key_raises(self) -> None:
        # 显式空 key + patch 环境变量，避免 .env 中 Z_AI_API_KEY 干扰
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"Z_AI_API_KEY": ""}, clear=False):
            client = ZhipuEmbeddingClient(api_key="")
            with self.assertRaises(RuntimeError) as ctx:
                client.embed(["x"])
            self.assertIn("Z_AI_API_KEY", str(ctx.exception))

    def test_request_body_pins_dimensions(self) -> None:
        """请求体必须显式带 dimensions=EMBEDDING_DIM（embedding-3 默认返回 2048 维）。"""
        from unittest.mock import MagicMock, patch

        response = MagicMock()
        response.json.return_value = {"data": [{"embedding": [0.0] * EMBEDDING_DIM}]}
        with patch("httpx.post", return_value=response) as mock_post:
            ZhipuEmbeddingClient(api_key="fake-key").embed(["x"])
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["dimensions"], EMBEDDING_DIM)
        self.assertEqual(body["model"], EMBEDDING_MODEL)
        self.assertEqual(body["input"], ["x"])


if __name__ == "__main__":
    unittest.main()