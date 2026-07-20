from __future__ import annotations

import base64
import binascii
import importlib
import os
from dataclasses import dataclass
from typing import Any, Protocol

from dotenv import load_dotenv


load_dotenv()


DEFAULT_VISION_MODEL = "glm-5v-turbo"


class VisionModelUnavailableError(RuntimeError):
    pass


class VisionModelResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionPage:
    page_number: int
    mime_type: str
    data_base64: str


class VisionModelClient(Protocol):
    def analyze_resume(self, pages: list[VisionPage], prompt: str) -> dict:
        """调用多模态模型，并返回结构化简历 JSON。"""


class ZaiVisionClient:
    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self.model = os.getenv("Z_AI_VISION_MODEL", DEFAULT_VISION_MODEL).strip() or DEFAULT_VISION_MODEL
        self.timeout_seconds = timeout_seconds or float(os.getenv("Z_AI_VISION_TIMEOUT_SECONDS", "180"))
        self.max_tokens = int(os.getenv("Z_AI_VISION_MAX_TOKENS", "16384"))
        self.thinking = _thinking_config()
        if sdk_client is not None:
            self.client = sdk_client
            return

        api_key = os.getenv("Z_AI_API_KEY", "").strip()
        if not api_key:
            raise VisionModelUnavailableError("缺少 Z_AI_API_KEY，无法调用智谱多模态模型。")
        try:
            from zai import ZhipuAiClient
        except ImportError as exc:
            raise VisionModelUnavailableError("缺少 zai-sdk，请先安装 requirements.txt。") from exc

        self.client = ZhipuAiClient(
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=int(os.getenv("Z_AI_VISION_MAX_RETRIES", "2")),
        )

    def analyze_resume(self, pages: list[VisionPage], prompt: str) -> dict:
        if not pages:
            raise ValueError("多模态模型没有收到简历页面。")

        content: list[dict[str, Any]] = [_image_content(page) for page in pages]
        page_numbers = "、".join(str(page.page_number) for page in pages)
        content.append(
            {
                "type": "text",
                "text": (
                    f"以上图像按顺序对应简历第 {page_numbers} 页。\n\n"
                    f"{prompt}\n\n"
                    "请直接输出完整 JSON 对象，不要输出 Markdown 代码块或解释。"
                ),
            }
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                thinking=self.thinking,
                response_format={"type": "json_object"},
                max_tokens=self.max_tokens,
                temperature=0.1,
                timeout=self.timeout_seconds,
            )
            raw_content = _response_content(response)
        except VisionModelResponseError:
            raise
        except Exception as exc:
            raise VisionModelResponseError(f"智谱多模态模型调用失败: {exc}") from exc

        from agi_talent_radar.core.llm_client import _loads_json

        try:
            return _loads_json(raw_content)
        except ValueError as exc:
            raise VisionModelResponseError(f"多模态模型未返回有效简历 JSON: {exc}") from exc


_registered_client: VisionModelClient | None = None


def register_vision_client(client: VisionModelClient | None) -> None:
    global _registered_client
    _registered_client = client


def get_vision_client() -> VisionModelClient:
    if _registered_client is not None:
        return _registered_client
    adapter_path = os.getenv("VISION_MODEL_ADAPTER", "").strip()
    if adapter_path:
        return _load_adapter(adapter_path)
    return ZaiVisionClient()


def _image_content(page: VisionPage) -> dict[str, Any]:
    if page.mime_type not in {"image/png", "image/jpeg"}:
        raise ValueError(f"第 {page.page_number} 页图像格式不支持: {page.mime_type}")
    try:
        base64.b64decode(page.data_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"第 {page.page_number} 页图像不是有效 Base64。") from exc
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{page.mime_type};base64,{page.data_base64}"},
    }


def _response_content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise VisionModelResponseError("多模态模型响应缺少 choices[0].message.content。") from exc
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        text = "\n".join(part for part in parts if part).strip()
        if text:
            return text
    raise VisionModelResponseError("多模态模型返回了空内容。")


def _thinking_config() -> dict[str, str]:
    value = os.getenv("Z_AI_VISION_THINKING", "enabled").strip().lower()
    if value not in {"enabled", "disabled"}:
        raise VisionModelUnavailableError("Z_AI_VISION_THINKING 只能是 enabled 或 disabled。")
    return {"type": value}


def _load_adapter(path: str) -> VisionModelClient:
    if ":" not in path:
        raise VisionModelUnavailableError("VISION_MODEL_ADAPTER 必须使用 module:attribute 格式。")
    module_name, attribute_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    adapter = getattr(module, attribute_name)
    client = adapter() if isinstance(adapter, type) else adapter
    if not hasattr(client, "analyze_resume"):
        raise VisionModelUnavailableError("多模态适配器必须实现 analyze_resume(pages, prompt)。")
    return client
