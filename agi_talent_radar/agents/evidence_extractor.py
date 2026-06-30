from __future__ import annotations

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import rubric_as_markdown


EVIDENCE_PROMPT = """
你是 AI 人才潜力初评系统里的【深度证据挖掘 Agent】。
只输出 JSON 对象，顶层字段必须是 evidence。

任务：
1. 从脱敏简历中抽取能支撑人才潜力判断的证据。
2. 每条 evidence.quote 必须逐字来自 raw_text 或项目/成果/技能字段，禁止改写、扩写、脑补。
3. 不要因为学校、GPA、排名给证据加分；这些背景已被脱敏。
4. 优先抽取具体动作、技术栈、量化结果、ownership、验证闭环。

dimension 只能取：
learning_growth, research_exploration, engineering_practice, ai_agent_leverage,
problem_definition, ownership, cultivation_value

每条证据格式：
{
  "id": "e001",
  "dimension": "...",
  "source": "项目：xxx / 代表成果 / 技能关键词 / 研究方向",
  "quote": "原文片段",
  "signals": ["技术栈:Triton", "动作:负责", "量化结果"],
  "strength": 1-5,
  "has_metric": true/false,
  "has_specific_tool": true/false,
  "has_ownership": true/false
}

证据数量控制在 10-18 条，覆盖多个维度。不要输出 Markdown。
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
