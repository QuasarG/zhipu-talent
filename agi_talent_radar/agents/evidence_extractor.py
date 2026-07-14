from __future__ import annotations

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.agents.tracks.registry import TRACK_SPECS
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume
from agi_talent_radar.agents.evidence_integrity import quote_integrity_flags


EVIDENCE_PROMPT = """
你是 AI 人才潜力初评系统里的【深度证据挖掘 Agent】。
只输出 JSON 对象，顶层字段必须是 evidence。

任务：
从简历中抽取能支撑人才潜力与履历判断的证据。

抽取原则：
1. 像尽调律师一样，优先提取「具体技术栈 / 具体动作动词 / 量化结果 / ownership 信号 / 验证闭环」。
2. 每条 evidence.quote 必须尽量使用简历原文短句；允许裁剪或压缩，但必须可从原文追溯，禁止扩写、脑补、编造数据。
3. 通用潜力只看项目/成果中的实际动作，不看学校、GPA、论文名气或热门方向。
4. Track 专业证据必须标注 track_hints，可多选 base, agent, safety, multimodal, systems, ai4science。
5. 如果某维度没有直接证据，不要硬凑，直接跳过。
6. 优先捕捉能区分“真正高潜”与“简历光鲜”的证据：问题约束、baseline、评测、错误归因、验证方式、本人负责范围和可复现产物。
7. 对只有论文题目、拟投状态、方向关键词、宽泛“提升/降低”但缺少 baseline 或验证定义的内容，可以抽取为风险证据，但 strength 不应给高。

可用通用维度：
problem_definition, research_rigor, learning_transfer, ownership,
evidence_credibility, growth_trajectory, track_specific, background_signal

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
  "has_ownership": true/false,
  "track_hints": ["systems", "base"],
  "page": null,
  "bbox": [],
  "extraction_confidence": 1.0
}

证据数量：每位候选人控制在 15-25 条，通用潜力与候选人实际涉及的专业 Track 都要覆盖。
不要输出 Markdown。
""".strip()


def run_evidence_extractor(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    repair_feedback = state.get("evidence_repair_feedback", [])
    response = llm_client.call_llm_json(
        EVIDENCE_PROMPT,
        {
            "common_rubric": [
                {
                    "key": item.key,
                    "label": item.label,
                    "max_points": item.max_points,
                    "evidence_rule": item.evidence_rule,
                }
                for item in COMMON_RUBRIC
            ],
            "track_rubrics": {key: spec.as_prompt_dict() for key, spec in TRACK_SPECS.items()},
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
