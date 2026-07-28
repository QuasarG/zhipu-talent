"""身份解析节点：从自由文本提取姓名 / 机构 / 方向 / 附加检索词。

身份不足时返回 needs_clarification，由上层要求用户补充，
不直接调用外部检索（与计划 §2.2 对齐）。
"""
from __future__ import annotations

import re
from typing import Any

from agi_talent_radar.core import llm_client
from agi_talent_radar.knowledge_agent.models import KnowledgeState


IDENTITY_PROMPT = """
你是人才知识 Agent 的身份解析节点。只输出 JSON 对象，顶层字段必须是 identity。

字段说明：
- name: 姓名（必须，没有则空串）
- org: 机构
- direction: 研究方向
- additional_keywords: 附加检索词数组
- confidence: 0-1
- needs_clarification: 身份不足（无姓名或置信度过低）时为 true

注意：只识别"一个"具体已知人物；若输入是"按方向找一批"则不在此节点处理。
""".strip()


_CN_NAME_RE = re.compile(r"[\u4e00-\u9fa5]{2,4}")
_EN_NAME_RE = re.compile(r"[A-Z][a-z]+(?:[\s-][A-Z][a-z]+)+")


def parse_identity(prompt: str, llm_response: dict[str, Any] | None = None) -> dict[str, Any]:
    """纯函数版身份解析。优先用 LLM；其次走正则兜底。"""
    if llm_response and isinstance(llm_response.get("identity"), dict):
        identity = dict(llm_response["identity"])
        return _normalize(identity, prompt)
    return _fallback(prompt)


def _normalize(identity: dict[str, Any], prompt: str) -> dict[str, Any]:
    name = str(identity.get("name", "")).strip()
    confidence = float(identity.get("confidence", 0.0) or 0.0)
    needs_clarification = bool(identity.get("needs_clarification", False))
    if not name:
        needs_clarification = True
    elif confidence < 0.4:
        needs_clarification = True
    return {
        "identity": {
            "name": name,
            "org": str(identity.get("org", "")).strip(),
            "direction": str(identity.get("direction", "")).strip(),
            "additional_keywords": [
                str(k) for k in (identity.get("additional_keywords") or []) if k
            ],
        },
        "identity_confidence": confidence,
        "needs_clarification": needs_clarification,
        "clarification_message": (
            "请提供可识别的具体人物姓名（以及机构或研究方向）。"
            if needs_clarification
            else ""
        ),
    }


def _fallback(prompt: str) -> dict[str, Any]:
    text = prompt or ""
    name = ""
    cn = _CN_NAME_RE.search(text)
    en = _EN_NAME_RE.search(text)
    if cn:
        name = cn.group(0)
    elif en:
        name = en.group(0)
    confidence = 0.6 if name else 0.0
    return _normalize(
        {
            "name": name,
            "org": "",
            "direction": "",
            "additional_keywords": [],
            "confidence": confidence,
            "needs_clarification": not bool(name),
        },
        prompt,
    )


def identity_resolver(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：解析身份。"""
    prompt = state.get("prompt", "")
    try:
        response = llm_client.call_llm_json(
            IDENTITY_PROMPT,
            {"prompt": prompt},
            temperature=0.0,
        )
    except Exception:
        response = None
    return parse_identity(prompt, response)