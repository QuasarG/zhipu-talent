from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


class CriticOutput(BaseModel):
    critic_flags: list[str] = Field(default_factory=list)
    needs_rescore: bool = False

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict):
            obj = dict(obj)
            obj["critic_flags"] = _stringify_flags(obj.get("critic_flags", []))
            obj["needs_rescore"] = bool(obj.get("needs_rescore", False))
        return super().model_validate(obj, **kwargs)


CRITIC_PROMPT = """
你是 AI 人才潜力初评系统里的【逻辑判官与防幻觉节点】。
只输出 JSON 对象，字段必须是 critic_flags, needs_rescore。

检查规则：
1. 防幻觉：评分理由（rationale）中引用的 evidence id 必须在 evidence 列表中存在；不得引用不存在的事实或编造简历原文没有的信息。
2. 防主观高分：潜力维度（learning_growth, research_exploration, engineering_practice, ai_agent_leverage, problem_definition, ownership, cultivation_value）如果 score >= 4.5，必须有至少一条 evidence 同时具备「具体技术栈 / 具体动作动词 / 量化结果 / ownership 信号」中的两项以上；否则给 critic_flags。
3. 防履历偏见：如果评分理由主要依赖学校、GPA、排名、名企光环，而不是项目证据，给 critic_flags。
4. 防安全分：如果所有维度 score 都集中在同一个分数（例如所有维度都是 3.5 或 4.0），给 critic_flags 并要求 Scorer 根据 evidence 强弱拉开区分度。
5. 防漏风险：如果某维度 evidence 数量 <= 1 但 score >= 4.0，给 critic_flags。

回炉规则：
- 如果上述问题会影响 overall_score 或分层判断，needs_rescore=true。
- 如果只是小的表述问题，不影响分数，needs_rescore=false。
""".strip()


def run_critic(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    scores = [DimensionScore.model_validate(item) for item in state.get("scores", [])]
    response = llm_client.call_llm_json(
        CRITIC_PROMPT,
        {
            "resume_brief": normalized.model_dump(exclude={"raw_text"}),
            "evidence": [item.model_dump() for item in evidence],
            "dimension_scores": [item.model_dump() for item in scores],
            "hard_integrity_flags": _quote_integrity_flags(evidence, normalized.raw_text),
        },
        temperature=0,
    )
    critic = CriticOutput.model_validate(response)
    loop_count = int(state.get("loop_count", 0))
    needs_rescore = critic.needs_rescore and loop_count < 1
    return {
        **state,
        "critic_flags": list(dict.fromkeys(state.get("critic_flags", []) + critic.critic_flags)),
        "critic_needs_rescore": needs_rescore,
        "loop_count": loop_count + 1 if needs_rescore else loop_count,
    }


def route_after_critic(state: dict) -> str:
    return "scorer" if state.get("critic_needs_rescore") else "formatter"


def _stringify_flags(value) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return [str(value)] if value else []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                result.append(item)
        elif isinstance(item, dict):
            text = item.get("flag") or item.get("issue") or item.get("reason") or item.get("note") or " ".join(str(v) for v in item.values() if isinstance(v, str))
            if text.strip():
                result.append(text.strip())
        else:
            text = str(item).strip()
            if text:
                result.append(text)
    return result


def _quote_integrity_flags(evidence: list[EvidenceItem], raw_text: str) -> list[str]:
    return [f"{item.id} 的 quote 未出现在原简历" for item in evidence if item.quote not in raw_text]
