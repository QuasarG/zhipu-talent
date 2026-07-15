"""Legacy v1 critic retained for regression coverage; inactive in the multi-track graph."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agi_talent_radar.agents.evidence_integrity import INTEGRITY_FLAG_PREFIX, quote_integrity_flags
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


MAX_EVIDENCE_REWRITE_LOOPS = 2
MAX_SCORE_RESCORE_LOOPS = 1


class CriticOutput(BaseModel):
    critic_flags: list[str] = Field(default_factory=list)
    needs_rescore: bool = False
    needs_evidence_rewrite: bool = False

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict):
            obj = dict(obj)
            obj["critic_flags"] = _stringify_flags(obj.get("critic_flags", []))
            obj["needs_rescore"] = bool(obj.get("needs_rescore", False))
            obj["needs_evidence_rewrite"] = bool(obj.get("needs_evidence_rewrite", False))
        return super().model_validate(obj, **kwargs)


CRITIC_PROMPT = """
你是 AI 人才潜力初评系统里的【逻辑判官与防幻觉节点】。
只输出 JSON 对象，字段必须是 critic_flags, needs_rescore, needs_evidence_rewrite。

检查规则：
1. 防幻觉：评分理由（rationale）中引用的 evidence id 必须在 evidence 列表中存在；不得引用不存在的事实或编造简历原文没有的信息。注意：quote 可以是原文短句的裁剪、顺序重组或语义压缩，只要关键术语、数字、技术栈和动作都能从原简历追溯，就不要判为幻觉。
2. 防主观高分：潜力维度（learning_growth, research_exploration, engineering_practice, ai_agent_leverage, problem_definition, ownership, cultivation_value）如果 score >= 4.5，必须有至少一条 evidence 同时具备「具体技术栈 / 具体动作动词 / 量化结果 / ownership 信号」中的两项以上；否则给 critic_flags。
3. 防履历偏见：如果评分理由主要依赖学校、GPA、排名、名企光环，而不是项目证据，给 critic_flags；教育背景只能使用 background_signal_tiers 的分级信号。
4. 防安全分：如果所有维度 score 都集中在同一个分数（例如所有维度都是 3.5 或 4.0），给 critic_flags 并要求 Scorer 根据 evidence 强弱拉开区分度。
5. 防漏风险：如果某维度 evidence 数量 <= 1 但 score >= 4.0，给 critic_flags。
6. 防自相矛盾：如果 risk_notes 或 rationale 里写了“证据偏弱 / 缺少量化结果 / 需确认本人贡献 / 只有论文题目 / 拟投待验证”，但该维度 score 仍 >= 4.0，给 critic_flags。
7. 防光鲜履历冲顶：如果高分主要来自 education_signal、academic_output、project_richness、impact_visibility、direction_fit，而 AI/Agent 杠杆、问题定义、ownership、工程闭环不足，必须给 critic_flags。
8. 防错把跨域当潜力：跨 AI4Science、医学、生物、视觉等方向本身不是加分项；只有能证明问题定义、工具杠杆和验证闭环时才可支撑高分。

回炉规则：
- 如果 evidence quote 或 evidence fact 真的不可追溯，优先 needs_evidence_rewrite=true，让证据挖掘节点重抽，不要直接把幻觉风险保留给前端。
- 如果评分逻辑会影响 overall_score 或分层判断，needs_rescore=true。
- 如果 hard_integrity_flags 为空，不要因为 quote 不是逐字连续子串就判幻觉。
- 如果只是小的表述问题，不影响分数，needs_rescore=false。
""".strip()


def run_critic(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    scores = [DimensionScore.model_validate(item) for item in state.get("scores", [])]
    integrity_flags = state.get("evidence_integrity_flags") or quote_integrity_flags(evidence, normalized.raw_text)
    response = llm_client.call_llm_json(
        CRITIC_PROMPT,
        {
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw", "experiences_raw"}),
            "evidence": [item.model_dump() for item in evidence],
            "dimension_scores": [item.model_dump() for item in scores],
            "hard_integrity_flags": integrity_flags,
        },
        temperature=0,
    )
    critic = CriticOutput.model_validate(response)
    critic_flags = _filter_quote_integrity_false_positives(critic.critic_flags, integrity_flags)
    evidence_loop_count = int(state.get("evidence_loop_count", 0))
    score_loop_count = int(state.get("score_loop_count", state.get("loop_count", 0)))
    wants_evidence_rewrite = bool(integrity_flags or _has_quote_integrity_flag(critic_flags) or critic.needs_evidence_rewrite)
    needs_evidence_rewrite = wants_evidence_rewrite and evidence_loop_count < MAX_EVIDENCE_REWRITE_LOOPS
    needs_rescore = critic.needs_rescore and not needs_evidence_rewrite and score_loop_count < MAX_SCORE_RESCORE_LOOPS
    final_flags = list(state.get("critic_flags", []))
    if needs_evidence_rewrite:
        repair_feedback = list(dict.fromkeys(integrity_flags + critic_flags))
    else:
        repair_feedback = state.get("evidence_repair_feedback", [])
        final_flags.extend(critic_flags)
        if wants_evidence_rewrite and integrity_flags:
            final_flags.extend(integrity_flags)
    return {
        **state,
        "critic_flags": list(dict.fromkeys(final_flags)),
        "critic_needs_rescore": needs_rescore,
        "critic_needs_evidence_rewrite": needs_evidence_rewrite,
        "evidence_repair_feedback": repair_feedback,
        "evidence_loop_count": evidence_loop_count + 1 if needs_evidence_rewrite else evidence_loop_count,
        "score_loop_count": score_loop_count + 1 if needs_rescore else score_loop_count,
        "loop_count": score_loop_count + 1 if needs_rescore else score_loop_count,
    }


def route_after_critic(state: dict) -> str:
    if state.get("critic_needs_evidence_rewrite"):
        return "evidence_extractor"
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


def _filter_quote_integrity_false_positives(flags: list[str], integrity_flags: list[str]) -> list[str]:
    flagged_ids = _evidence_ids("\n".join(integrity_flags))
    result: list[str] = []
    for flag in flags:
        if _is_quote_integrity_flag(flag):
            flag_ids = _evidence_ids(flag)
            if not integrity_flags or (flag_ids and flag_ids.isdisjoint(flagged_ids)):
                continue
        result.append(flag)
    return result


def _has_quote_integrity_flag(flags: list[str]) -> bool:
    return any(_is_quote_integrity_flag(flag) for flag in flags)


def _is_quote_integrity_flag(flag: str) -> bool:
    text = str(flag).lower()
    return (
        INTEGRITY_FLAG_PREFIX in str(flag)
        or "quote" in text
        or "引文" in text
        or ("原文" in text and ("未出现" in text or "不存在" in text or "不可追溯" in text))
        or ("原简历" in text and ("未出现" in text or "不存在" in text or "不可追溯" in text))
    )


def _evidence_ids(text: str) -> set[str]:
    return set(re.findall(r"e\d{3,}", str(text)))
