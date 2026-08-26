from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from dotenv import load_dotenv
from json_repair import loads as repair_json_loads
from openai import OpenAI


load_dotenv()


@dataclass(frozen=True)
class LLMCallRecord:
    model: str
    fallback_reason: str
    started_at: str
    completed_at: str


CallObserver = Callable[[dict[str, str]], None]


def call_llm_json(
    system_prompt: str,
    payload: dict[str, Any],
    temperature: float = 0.1,
    enable_thinking: bool = False,
    deep: bool = False,
    model_override: str | None = None,
    on_call: CallObserver | None = None,
    conversation: bool = False,
) -> dict[str, Any]:
    """调用 JSON 模型；对话调用显式传 conversation=True，其他调用统一走 5.2。"""
    primary_model = model_override or (
        _conversation_model() if conversation else (_deep_model() if deep else _non_conversation_model())
    )
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "300" if deep else "120"))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response = _request_completion(
        primary_model,
        {
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "timeout": timeout_seconds,
        },
        on_call=on_call,
    )

    content = response.choices[0].message.content or ""
    try:
        return _loads_json(content)
    except ValueError as first_error:
        retry_response = _request_completion(
            primary_model,
            {
                "messages": [
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
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "timeout": timeout_seconds,
            },
            on_call=on_call,
        )
        retry_content = retry_response.choices[0].message.content or ""
        try:
            return _loads_json(retry_content)
        except ValueError as retry_error:
            raise ValueError(
                f"LLM JSON 本地修复与二次生成均失败；"
                f"首次错误: {first_error}；二次错误: {retry_error}"
            ) from retry_error


def call_llm_stream(
    system_prompt: str,
    payload: dict[str, Any],
    temperature: float = 0.1,
    model_override: str | None = None,
    on_call: CallObserver | None = None,
):
    """流式调用 LLM，逐 token 返回文本内容。

    用于导入等需要边接收边解析 JSON Lines 的场景。若请求在产生首个内容前
    遇到限流/网络错误，最多重试 3 次；已经输出内容后不重试，避免前端收到重复片段。
    """
    primary_model = model_override or _non_conversation_model()
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    max_retries = 3
    for attempt in range(max_retries):
        emitted = False
        model, fallback_reason, is_probe = _CIRCUIT.select(primary_model)
        started_at = _utc_now()
        try:
            with _LLM_CONCURRENCY:
                response = _client().chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                    timeout=timeout_seconds,
                    **_thinking_kwargs_for(model),
                )
                for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        emitted = True
                        yield delta.content
            _CIRCUIT.succeeded(primary_model, model, is_probe)
            _observe_call(on_call, model, fallback_reason, started_at)
            return
        except Exception as exc:
            if _is_rate_limit_error(exc) and model == primary_model:
                _CIRCUIT.rate_limited(primary_model, is_probe)
                if not emitted and attempt + 1 < max_retries:
                    if _fallback_model(primary_model) == primary_model:
                        time.sleep(min(8.0, 2.0**attempt))
                    continue
            elif is_probe:
                _CIRCUIT.probe_finished()
            if emitted or attempt + 1 >= max_retries:
                raise
            time.sleep(min(8.0, 2.0**attempt))


def call_llm_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float = 0.2,
    on_delta: Callable[[str], None] | None = None,
    max_retries: int = 3,
    on_reasoning: Callable[[str], None] | None = None,
    reasoning_effort: str | None = None,
    model_override: str | None = None,
    on_call: CallObserver | None = None,
) -> dict[str, Any]:
    """流式 tool calling：文本 delta 经 on_delta 实时回调，tool_calls 分片累积。

    返回 {"text": 完整文本, "tool_calls": [{id, name, arguments}], "finish_reason": str}。
    arguments 为原始 JSON 字符串，由调用方负责解析。

    重试取舍：首轮边流边回调 on_delta；若流中途异常，已发出的文本无法收回，
    故重试轮改为静默收集、不再回调（否则用户会看到重复文本），最终通过返回值的
    text 字段给出完整文本。只有整轮流完整结束才算成功，否则整轮作废、指数退避重试。
    """
    primary_model = model_override or _required_env("OPENAI_MODEL")
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))

    last_error: Exception | None = None
    for attempt in range(max(1, max_retries)):
        stream_delta = on_delta if attempt == 0 else None
        stream_reasoning = on_reasoning if attempt == 0 else None
        model, fallback_reason, is_probe = _CIRCUIT.select(primary_model)
        started_at = _utc_now()
        try:
            with _LLM_CONCURRENCY:
                result = _call_llm_tools_once(
                    _client(), model, messages, tools, temperature, timeout_seconds,
                    stream_delta, stream_reasoning, reasoning_effort,
                )
            _CIRCUIT.succeeded(primary_model, model, is_probe)
            _observe_call(on_call, model, fallback_reason, started_at)
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if _is_rate_limit_error(exc) and model == primary_model:
                _CIRCUIT.rate_limited(primary_model, is_probe)
                if _fallback_model(primary_model) == primary_model and attempt + 1 < max(1, max_retries):
                    time.sleep(min(8.0, 2.0**attempt))
                continue
            if is_probe:
                _CIRCUIT.probe_finished()
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
    on_reasoning: Callable[[str], None] | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """单轮流式调用；任何中途异常都向上抛，由外层整轮重试。

    reasoning delta（思考流）经 on_reasoning 回调；effort 不传走 env 默认（low）。
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "timeout": timeout_seconds,
        **_thinking_kwargs_for(model, reasoning_effort),
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
        reasoning = (delta.model_extra or {}).get("reasoning_content") if hasattr(delta, "model_extra") else None
        if reasoning and on_reasoning is not None:
            on_reasoning(str(reasoning))
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
_LLM_CONCURRENCY = threading.BoundedSemaphore(max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "5"))))


class _RateLimitCircuit:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open_until = 0.0
        self._probe_in_flight = False

    def select(self, primary_model: str) -> tuple[str, str, bool]:
        fallback = _fallback_model(primary_model)
        if fallback == primary_model:
            return primary_model, "", False
        with self._lock:
            now = time.monotonic()
            if now < self._open_until:
                return fallback, "rate_limit_circuit_open", False
            if self._open_until > 0:
                if self._probe_in_flight:
                    return fallback, "recovery_probe_in_progress", False
                self._probe_in_flight = True
                return primary_model, "recovery_probe", True
            return primary_model, "", False

    def rate_limited(self, primary_model: str, was_probe: bool) -> None:
        if _fallback_model(primary_model) == primary_model:
            return
        with self._lock:
            self._open_until = time.monotonic() + float(os.getenv("LLM_FALLBACK_COOLDOWN_SECONDS", "60"))
            if was_probe:
                self._probe_in_flight = False

    def succeeded(self, primary_model: str, actual_model: str, was_probe: bool) -> None:
        if actual_model != primary_model or not was_probe:
            return
        with self._lock:
            self._open_until = 0.0
            self._probe_in_flight = False

    def probe_finished(self) -> None:
        with self._lock:
            self._probe_in_flight = False

    def reset(self) -> None:
        with self._lock:
            self._open_until = 0.0
            self._probe_in_flight = False


_CIRCUIT = _RateLimitCircuit()


def _request_completion(
    primary_model: str,
    kwargs: dict[str, Any],
    on_call: CallObserver | None = None,
    max_retries: int = 3,
):
    last_error: Exception | None = None
    for attempt in range(max(1, max_retries)):
        model, fallback_reason, is_probe = _CIRCUIT.select(primary_model)
        started_at = _utc_now()
        try:
            with _LLM_CONCURRENCY:
                response = _client().chat.completions.create(
                    model=model,
                    **kwargs,
                    **_thinking_kwargs_for(model),
                )
            _CIRCUIT.succeeded(primary_model, model, is_probe)
            _observe_call(on_call, model, fallback_reason, started_at)
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if _is_rate_limit_error(exc) and model == primary_model:
                _CIRCUIT.rate_limited(primary_model, is_probe)
                if _fallback_model(primary_model) == primary_model and attempt + 1 < max(1, max_retries):
                    time.sleep(min(8.0, 2.0**attempt))
                continue
            if is_probe:
                _CIRCUIT.probe_finished()
            if attempt + 1 < max(1, max_retries):
                time.sleep(min(8.0, 2.0**attempt))
    assert last_error is not None
    raise last_error


def _fallback_model(primary_model: str) -> str:
    configured = os.getenv("OPENAI_MODEL_FALLBACK", "").strip()
    if configured:
        return configured
    if primary_model.startswith("glm-5.3"):
        return "glm-5.2"
    return primary_model


def _is_rate_limit_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        detail = body.get("error", body)
        if isinstance(detail, dict) and str(detail.get("code", "")) == "1302":
            return True
    text = str(error)
    return bool(re.search(r"(?:\b429\b|['\"]?code['\"]?\s*[:=]\s*['\"]?1302\b)", text))


def _observe_call(
    observer: CallObserver | None,
    model: str,
    fallback_reason: str,
    started_at: str,
) -> None:
    if observer is None:
        return
    observer(
        asdict(
            LLMCallRecord(
                model=model,
                fallback_reason=fallback_reason,
                started_at=started_at,
                completed_at=_utc_now(),
            )
        )
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _deep_model() -> str:
    """非对话深度节点也固定使用 5.2，避免与对话模型争用 5.3 配额。"""
    return _non_conversation_model()


def _non_conversation_model() -> str:
    """所有非对话 LLM 节点的模型；默认固定为 GLM-5.2。"""
    return os.getenv("OPENAI_MODEL_NON_CONVERSATION", "").strip() or "glm-5.2"


def _conversation_model() -> str:
    """对话 Agent 使用的主模型，沿用 OPENAI_MODEL（生产环境为 GLM-5.3）。"""
    return _required_env("OPENAI_MODEL")


def _thinking_kwargs_for(model: str, effort_override: str | None = None) -> dict[str, Any]:
    """按模型选思考参数：glm-5.3 不支持 disabled，强制 enabled+effort；其余禁思考。

    effort_override 显式指定（如问答 Agent 用 max 获取可流式展示的思考）；
    默认走 OPENAI_EFFORT_DEEP（low——实测 low 不产生思考内容，最快）。
    """
    if model.startswith("glm-5.3"):
        effort = (effort_override or os.getenv("OPENAI_EFFORT_DEEP", "low").strip() or "low")
        return {"reasoning_effort": effort, "extra_body": {"thinking": {"type": "enabled"}}}
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
