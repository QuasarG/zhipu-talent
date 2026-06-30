from __future__ import annotations

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import rubric_as_markdown


EVIDENCE_PROMPT = """
你是 AI 人才潜力初评系统里的【深度证据挖掘 Agent】。
只输出 JSON 对象，顶层字段必须是 evidence。

任务：
从简历中抽取能支撑人才潜力与履历判断的证据。

抽取原则：
1. 像尽调律师一样，优先提取「具体技术栈 / 具体动作动词 / 量化结果 / ownership 信号 / 验证闭环」。
2. 每条 evidence.quote 必须尽量逐字来自简历原文，禁止扩写、脑补、编造数据。
3. 潜力维度（学习与成长、研究探索、工程实践、AI Agent、问题定义、ownership、长期培养）只看项目/成果中的实际动作，不看学校/GPA/论文名气。
4. 履历维度（教育背景、学术产出、项目丰富度、影响力、方向匹配）允许从学校、GPA、论文、项目数量、技能覆盖等背景信息中提取。
5. 如果某维度没有直接证据，不要硬凑，直接跳过。

可用维度（dimension 必须取以下值之一）：
learning_growth, research_exploration, engineering_practice, ai_agent_leverage,
problem_definition, ownership, cultivation_value,
education_signal, academic_output, project_richness, impact_visibility, direction_fit

每条证据格式：
{
  "id": "e001",
  "dimension": "engineering_practice",
  "source": "项目：xxx / 代表成果 / 教育背景 / 技能关键词 / 研究方向",
  "quote": "原文片段",
  "signals": ["技术栈:Triton", "动作:负责", "量化结果:显存降低35%"],
  "strength": 1-5,
  "has_metric": true/false,
  "has_specific_tool": true/false,
  "has_ownership": true/false
}

证据数量：每位候选人控制在 15-25 条，潜力维度与履历维度都要覆盖，不要全部堆在某一个维度上。
不要输出 Markdown。
""".strip()


def run_evidence_extractor(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    response = llm_client.call_llm_json(
        EVIDENCE_PROMPT,
        {
            "rubric": rubric_as_markdown(),
            "resume": normalized.model_dump(),
        },
        temperature=0.1,
    )
    evidence = [EvidenceItem.model_validate(item) for item in response.get("evidence", [])]
    integrity_flags = _quote_integrity_flags(evidence, normalized.raw_text)
    return {
        **state,
        "evidence": [item.model_dump() for item in evidence],
        "critic_flags": state.get("critic_flags", []) + integrity_flags,
    }


def _quote_integrity_flags(evidence: list[EvidenceItem], raw_text: str) -> list[str]:
    return [f"疑似幻觉证据：{item.id} 的引文未出现在原简历。" for item in evidence if item.quote not in raw_text]
