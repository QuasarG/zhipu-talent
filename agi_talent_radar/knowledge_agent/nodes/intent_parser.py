"""意图识别节点。

区分四类意图：库内查询 / 已知人物调查 / 不在本期的人才发现 / 不支持。
"按研究关键词发现一批未知人物" 明确不做，返回 UNSUPPORTED。
"""
from __future__ import annotations

import re
from typing import Any

from agi_talent_radar.core import llm_client
from agi_talent_radar.knowledge_agent.models import KnowledgeState, UserIntent


INTENT_PROMPT = """
你是人才知识 Agent 的意图识别节点。只输出 JSON 对象，顶层字段必须是 intent 与 scope。

意图类型（intent 字段，只能选一个）：
- pool_query     库内查询、比较、统计人才库已有信息
- known_person   围绕一个可识别的具体已知人物做调查（论文 / 舆情 / 画像）
- talent_discovery 按研究关键词发现一批未知人物（本期明确不做）
- unsupported    其他不支持

scope 字段（数组）从下面选：papers / reputation / profile / all；用户明确
说"只看论文"→ ["papers"]，"只查舆情"→ ["reputation"]，未限定时默认 ["all"]。

输入：用户自由文本。
""".strip()


_DISCOVERY_MARKERS = (
    "发现", "找一批", "找一些", "推荐一批", "按方向", "按关键词找",
    "list candidates", "discover",
)


def parse_intent(prompt: str, llm_response: dict[str, Any] | None = None) -> dict[str, Any]:
    """纯函数版意图识别，便于单测。

    优先使用 LLM 响应；其次走保守关键字兜底。
    """
    if llm_response and llm_response.get("intent"):
        return _normalize(llm_response, prompt)
    return _fallback(prompt)


def _normalize(response: dict[str, Any], prompt: str) -> dict[str, Any]:
    raw_intent = str(response.get("intent", "")).strip().lower()
    intent = _coerce_intent(raw_intent, prompt)
    scope = response.get("scope") or []
    if isinstance(scope, str):
        scope = [scope]
    scope = [str(item).lower() for item in scope if item]
    if not scope or "all" in scope:
        scope = ["all"]
    allowed_scopes = {"papers", "reputation", "profile", "all"}
    scope = [s for s in scope if s in allowed_scopes] or ["all"]
    return {
        "intent": intent,
        "scope": scope,
        "needs_clarification": False,
        "clarification_message": "",
    }


def _coerce_intent(raw: str, prompt: str) -> str:
    if raw in {item.value for item in UserIntent}:
        return raw
    # LLM 误判时按关键字兜底
    return _fallback(prompt)["intent"]


def _fallback(prompt: str) -> dict[str, Any]:
    text = prompt or ""
    lowered = text.lower()
    # 1. 人才发现：本期明确不做
    if any(marker in text for marker in _DISCOVERY_MARKERS):
        if "找" in text or "发现" in text or "推荐" in text or "一批" in text:
            if not _looks_like_known_person(text):
                return {
                    "intent": UserIntent.TALENT_DISCOVERY.value,
                    "scope": ["all"],
                    "needs_clarification": False,
                    "clarification_message": "",
                }
    # 2. 已知人物：包含姓名（中文 2-4 字 / 英文大写首字母）+ 至少一个机构/方向信号
    if _looks_like_known_person(text):
        scope = _extract_scope(text)
        return {
            "intent": UserIntent.KNOWN_PERSON.value,
            "scope": scope,
            "needs_clarification": False,
            "clarification_message": "",
        }
    # 3. 默认库内查询
    return {
        "intent": UserIntent.POOL_QUERY.value,
        "scope": ["all"],
        "needs_clarification": False,
        "clarification_message": "",
    }


_CN_NAME_RE = re.compile(r"[\u4e00-\u9fa5]{2,4}")
_ORG_HINTS = ("大学", "学院", "实验室", "研究院", "公司", "机构", "组", "team", "lab", "university", "inc")


def _looks_like_known_person(text: str) -> bool:
    if not text:
        return False
    has_name = bool(_CN_NAME_RE.search(text)) or bool(re.search(r"[A-Z][a-z]+ [A-Z]", text))
    has_org = any(hint in text.lower() for hint in _ORG_HINTS)
    # 也支持纯姓名输入
    return has_name and (has_org or len(text) <= 8)


_SCOPE_KEYWORDS = {
    "papers": ("论文", "paper", "publication", "引用", "引用量"),
    "reputation": ("舆情", "争议", " reputation", "撤稿", "学术不端"),
    "profile": ("画像", "方向", "研究范围", "profile"),
}


def _extract_scope(text: str) -> list[str]:
    lowered = text.lower()
    matched: list[str] = []
    for scope, markers in _SCOPE_KEYWORDS.items():
        if any(marker in lowered for marker in markers):
            matched.append(scope)
    return matched or ["all"]


def intent_parser(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：识别意图。"""
    prompt = state.get("prompt", "")
    try:
        response = llm_client.call_llm_json(
            INTENT_PROMPT,
            {"prompt": prompt},
            temperature=0.0,
        )
    except Exception:
        response = None
    parsed = parse_intent(prompt, response)
    return parsed