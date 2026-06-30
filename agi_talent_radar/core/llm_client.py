from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def call_llm_json(system_prompt: str, payload: dict[str, Any], temperature: float = 0.1) -> dict[str, Any]:
    client = _client()
    model = _required_env("OPENAI_MODEL")
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
        timeout=timeout_seconds,
    )
    content = response.choices[0].message.content or ""
    return _loads_json(content)


def _client() -> OpenAI:
    api_key = _required_env("DEEPSEEK_API_KEY")
    base_url = _required_env("OPENAI_BASE_URL")
    return OpenAI(api_key=api_key, base_url=base_url)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，当前项目只保留 DeepSeek AI 模式。")
    return value


def _loads_json(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError(f"模型没有返回 JSON 对象: {content[:300]}")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 顶层必须是对象。")
    return data
