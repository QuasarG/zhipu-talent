from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable

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

    # 限流/超时重试(指数退避),避免并发时降级响应压低评分
    import time as _time
    max_http_retries = 3
    response = None
    for http_attempt in range(max_http_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
                timeout=timeout_seconds,
                **thinking_kwargs,
            )
            break
        except Exception as http_err:
            if http_attempt + 1 < max_http_retries:
                _time.sleep(min(8.0, 2.0 ** http_attempt))
                continue
            raise

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


def call_llm_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float = 0.2,
    on_delta: Callable[[str], None] | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """流式 tool calling：文本 delta 经 on_delta 实时回调，tool_calls 分片累积。

    返回 {"text": 完整文本, "tool_calls": [{id, name, arguments}], "finish_reason": str}。
    arguments 为原始 JSON 字符串，由调用方负责解析。

    重试取舍：首轮边流边回调 on_delta；若流中途异常，已发出的文本无法收回，
    故重试轮改为静默收集、不再回调（否则用户会看到重复文本），最终通过返回值的
    text 字段给出完整文本。只有整轮流完整结束才算成功，否则整轮作废、指数退避重试。
    """
    client = _client()
    model = _required_env("OPENAI_MODEL")
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))

    last_error: Exception | None = None
    for attempt in range(max(1, max_retries)):
        stream_delta = on_delta if attempt == 0 else None
        try:
            return _call_llm_tools_once(
                client, model, messages, tools, temperature, timeout_seconds, stream_delta
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < max(1, max_retries):
                time.sleep(min(8.0, 2.0**attempt))
    raise RuntimeError(f"call_llm_tools 重试 {max(1, max_retries)} 次后仍失败: {last_error}") from last_error


def _call_llm_tools_once(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float,
    timeout_seconds: float,
    on_delta: Callable[[str], None] | None,
) -> dict[str, Any]:
    """单轮流式调用；任何中途异常都向上抛，由外层整轮重试。"""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "timeout": timeout_seconds,
    }
    if tools:  # 空列表=无工具收尾调用，不传 tools 参数（部分 API 拒绝空数组）
        kwargs["tools"] = tools
    response = client.chat.completions.create(**kwargs)
    text_parts: list[str] = []
    tool_fragments: dict[int, dict[str, str]] = {}
    finish_reason = ""
    for chunk in response:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta is None:
            continue
        if delta.content:
            text_parts.append(delta.content)
            if on_delta is not None:
                on_delta(delta.content)
        for tool_call in delta.tool_calls or []:
            fragment = tool_fragments.setdefault(
                tool_call.index, {"id": "", "name": "", "arguments": ""}
            )
            if tool_call.id:
                fragment["id"] += tool_call.id
            function = tool_call.function
            if function is not None:
                if function.name:
                    fragment["name"] += function.name
                if function.arguments:
                    fragment["arguments"] += function.arguments

    return {
        "text": "".join(text_parts),
        "tool_calls": [tool_fragments[index] for index in sorted(tool_fragments)],
        "finish_reason": finish_reason,
    }


_CLIENT: "OpenAI | None" = None
_CLIENT_LOCK = threading.Lock()


def _client() -> OpenAI:
    """模块级单例：OpenAI 客户端线程安全，每次新建只会白做 TCP 握手。"""
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                api_key = _required_env("LLM_API_KEY", "DEEPSEEK_API_KEY")
                base_url = _required_env("OPENAI_BASE_URL")
                _CLIENT = OpenAI(api_key=api_key, base_url=base_url)
    return _CLIENT


def _thinking_kwargs(enable_thinking: bool = False) -> dict[str, Any]:
    """GLM-5.2 全链路禁用思考：参数保留但恒返回 disabled（提示词工程已足够）。"""
    return {"extra_body": {"thinking": {"type": "disabled"}}}


def _required_env(*names: str) -> str:
    """按顺序取第一个非空环境变量；全部缺失时报错。"""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    missing = "/".join(names)
    raise RuntimeError(f"缺少环境变量 {missing}，当前项目使用智谱 GLM（OpenAI 兼容端点）。")


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
