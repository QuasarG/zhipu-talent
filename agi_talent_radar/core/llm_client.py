from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from json_repair import loads as repair_json_loads
from openai import OpenAI


load_dotenv()


def call_llm_json(
    system_prompt: str,
    payload: dict[str, Any],
    temperature: float = 0.1,
    enable_thinking: bool = False,
) -> dict[str, Any]:
    client = _client()
    model = _required_env("OPENAI_MODEL")
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    thinking_kwargs = _thinking_kwargs(enable_thinking)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        timeout=timeout_seconds,
        **thinking_kwargs,
    )
    content = response.choices[0].message.content or ""
    try:
        return _loads_json(content)
    except ValueError as first_error:
        retry_response = client.chat.completions.create(
            model=model,
            messages=[
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "上一次输出不是完整有效的 JSON 对象。"
                        f"解析错误：{first_error}。"
                        "请基于原始请求重新生成完整 JSON，只输出 JSON 对象，"
                        "不要省略字段，不要输出 Markdown 或解释。"
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=timeout_seconds,
            **_thinking_kwargs(False),
        )
        retry_content = retry_response.choices[0].message.content or ""
        try:
            return _loads_json(retry_content)
        except ValueError as retry_error:
            raise ValueError(
                f"LLM JSON 本地修复与二次生成均失败；"
                f"首次错误: {first_error}；二次错误: {retry_error}"
            ) from retry_error


def call_llm_stream(system_prompt: str, payload: dict[str, Any], temperature: float = 0.1):
    """流式调用 LLM，逐 token 返回文本内容。

    用于导入等需要边接收边解析 JSON Lines 的场景。
    """
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
        stream=True,
        timeout=timeout_seconds,
        extra_body={"thinking": {"type": "disabled"}},
    )
    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


def _client() -> OpenAI:
    api_key = _required_env("DEEPSEEK_API_KEY")
    base_url = _required_env("OPENAI_BASE_URL")
    return OpenAI(api_key=api_key, base_url=base_url)


def _thinking_kwargs(enable_thinking: bool) -> dict[str, Any]:
    """按是否启用思考返回对应请求参数。

    开启：低强度思考（提升事实对齐准确度，核验阶段专用）。
    关闭：纯生成模式（评估等 17 处调用保持原行为）。
    """
    if enable_thinking:
        return {"reasoning_effort": "low", "extra_body": {"thinking": {"type": "enabled"}}}
    return {"extra_body": {"thinking": {"type": "disabled"}}}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，当前项目只保留 DeepSeek AI 模式。")
    return value


def _loads_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.S)
    if match and match.group(0) != text:
        candidates.append(match.group(0))

    errors: list[str] = []
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"line {exc.lineno} column {exc.colno}: {exc.msg}")
            continue
        if isinstance(data, dict):
            return data
        errors.append("顶层不是对象")

    for candidate in candidates:
        try:
            repaired = repair_json_loads(candidate)
        except Exception as exc:
            errors.append(f"本地修复失败: {exc}")
            continue
        if isinstance(repaired, dict):
            return repaired
        errors.append("本地修复后顶层仍不是对象")

    preview = text[:240].replace("\n", " ")
    details = "；".join(dict.fromkeys(errors))
    raise ValueError(f"模型没有返回有效 JSON 对象: {details}；内容摘要: {preview}")
