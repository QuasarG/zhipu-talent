from __future__ import annotations

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import CALIBRATION_REFERENCE, rubric_as_markdown
from agi_talent_radar.agents.evidence_integrity import quote_integrity_flags


EVIDENCE_PROMPT = """
你是 AI 人才潜力初评系统里的【深度证据挖掘 Agent】。
只输出 JSON 对象，顶层字段必须是 evidence。

任务：
从简历中抽取能支撑人才潜力与履历判断的证据。

抽取原则：
1. 像尽调律师一样，优先提取「具体技术栈 / 具体动作动词 / 量化结果 / ownership 信号 / 验证闭环」。
2. 每条 evidence.quote 必须尽量使用简历原文短句；允许裁剪或压缩，但必须可从原文追溯，禁止扩写、脑补、编造数据。
3. 潜力维度（学习与成长、研究探索、工程实践、AI Agent、问题定义、ownership、长期培养）只看项目/成果中的实际动作，不看学校/GPA/论文名气。
4. 履历维度（教育背景、学术产出、项目丰富度、影响力、方向匹配）只允许使用 education_blind 与 background_signal_tiers 中的分级信号，不要恢复或猜测具体学校/GPA/排名。
5. 如果某维度没有直接证据，不要硬凑，直接跳过。
6. 优先捕捉能区分“真正高潜”与“简历光鲜”的证据：问题约束、baseline/评测、错误归因、自动验证、Agent/工具链、可运行系统、本人负责范围。
7. 对只有论文题目、拟投状态、方向关键词、宽泛“提升/降低”但缺少 baseline 或验证定义的内容，可以抽取为风险证据，但 strength 不应给高。

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
    repair_feedback = state.get("evidence_repair_feedback", [])
    response = llm_client.call_llm_json(
        EVIDENCE_PROMPT,
        {
            "rubric": rubric_as_markdown(),
            "calibration_reference": CALIBRATION_REFERENCE,
            "resume": normalized.model_dump(exclude={"education_raw"}),
            "repair_feedback": repair_feedback,
            "repair_instruction": (
                "如果 repair_feedback 非空，请重抽对应 evidence：quote 改为可在原文中直接定位的短句，"
                "不要保留不可追溯的重组句。"
            ),
        },
        temperature=0.1,
    )
    evidence = [EvidenceItem.model_validate(item) for item in response.get("evidence", [])]
    return {
        **state,
        "evidence": [item.model_dump() for item in evidence],
        "evidence_integrity_flags": quote_integrity_flags(evidence, normalized.raw_text),
        "critic_needs_rescore": False,
        "critic_needs_evidence_rewrite": False,
    }
