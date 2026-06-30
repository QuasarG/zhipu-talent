from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


class CriticOutput(BaseModel):
    critic_flags: list[str] = Field(default_factory=list)
    needs_rescore: bool = False


CRITIC_PROMPT = """
你是 AI 人才潜力初评系统里的【逻辑判官与防幻觉节点】。
只输出 JSON 对象，字段必须是 critic_flags, needs_rescore。

检查规则：
1. 防幻觉：评分理由和证据引用必须能在 evidence 中找到，不得引用不存在的事实。
2. 防主观：如果某维度给到 4.5+，但 evidence 中缺少具体技术栈、量化结果、本人动作或验证闭环，必须给 critic_flags。
3. 防背景偏见：如果理由依赖学校、GPA、排名、名企而不是项目证据，必须给 critic_flags。
4. 如果问题会影响综合评分，needs_rescore=true；如果只是小的表述问题，needs_rescore=false。
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
        "critic_flags": critic.critic_flags,
        "critic_needs_rescore": needs_rescore,
        "loop_count": loop_count + 1 if needs_rescore else loop_count,
    }


def route_after_critic(state: dict) -> str:
    return "scorer" if state.get("critic_needs_rescore") else "formatter"


def _quote_integrity_flags(evidence: list[EvidenceItem], raw_text: str) -> list[str]:
    return [f"{item.id} 的 quote 未出现在原简历" for item in evidence if item.quote not in raw_text]
