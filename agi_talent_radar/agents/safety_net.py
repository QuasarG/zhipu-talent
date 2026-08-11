"""兜底加分节点(safety_net)。

扫描原始简历(未脱敏)+ 全部评分结果,识别分项评分体系未覆盖、
但确实显著的外部成就(高考状元/竞赛最高奖/开源高star等),
给予少量加分(0-5),加分必须可追溯。

不改任何维度分,只额外加分。加分上限5分,单条上限2分。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.core import llm_client


SAFETY_NET_PROMPT = """
你是人才评估的【兜底加分节点】。只识别"分项评分体系未覆盖、但确实显著的外部成就"。
不重复评价项目能力、论文发表——这些已被 common/track 评分和 publication_score 覆盖。

可加分锚点示例（脱敏，不带姓名，按显著性从高到低）：
- 高考省/市级状元、全省前列（如高考705/全省前10）
- 国际数学建模竞赛最高奖（美赛O奖/特等奖提名/美国数学学会特别奖）
- 国际竞赛冠军、全球排名前列（如挑战赛1/78支队伍击败308次提交）
- 开源项目高star或被世界级开源基座收录（如55k★项目核心贡献、代码合并进OpenCV官方）
- 成果被顶级研究者引用采用（如被图灵奖得主引用）
- 安全漏洞产出（如CVE编号、企业认证漏洞）

不可加分项（已被其它维度覆盖或违反评分哲学）：
- 学校名气、机构档位、导师头衔（评分明确禁止机构加分）
- 项目能力、论文数量（已被 common/track/publication 评价）
- GPA、课程成绩（已脱敏折叠，不直接加分）

判断原则：
1. 只对可核验的外部成就加分，证据必须能在 resume_raw 里定位到原文。
2. 宁缺毋滥——只有真正稀缺的成就才加分，普通竞赛获奖/校级荣誉不给分。
3. bonus 取值：稀缺成就 1.5-2.0，中等显著 0.5-1.0，不显著不给分。

只输出 JSON 对象：
{
  "bonuses": [
    {
      "description": "成就描述（一句话，如'高考705分，云南省理科状元'）",
      "bonus": 1.5,
      "evidence_quote": "简历原文片段",
      "rationale": "为什么这是分项评分未覆盖但值得加分的成就"
    }
  ]
}
没有符合条件的成就时输出 {"bonuses": []}。
""".strip()

MAX_BONUS_PER_ITEM = 2.0
MAX_TOTAL_BONUS = 5.0


def run_safety_net(state: dict[str, Any]) -> dict[str, Any]:
    resume_raw = (state.get("resume") or {}).get("raw_text") or ""
    if not resume_raw.strip():
        return {"safety_net_bonuses": [], "safety_net_score": 0.0}

    # 给 LLM 看已有分数,避免重复评价
    existing = {
        "common_score": state.get("common_score", 0),
        "publication_score": state.get("publication_score", 0),
        "track_scores": [
            {"track": r.get("track"), "score": r.get("calibrated_score")}
            for r in state.get("track_results") or []
        ],
    }

    try:
        response = llm_client.call_llm_json(
            SAFETY_NET_PROMPT,
            {"resume_raw": resume_raw, "existing_scores": existing},
            temperature=0.1,
        )
    except Exception:
        return {"safety_net_bonuses": [], "safety_net_score": 0.0}

    bonuses = []
    total = 0.0
    for item in response.get("bonuses") or []:
        bonus = float(item.get("bonus") or 0)
        # 单条 clamp
        bonus = max(0.0, min(MAX_BONUS_PER_ITEM, bonus))
        if bonus <= 0 or total + bonus > MAX_TOTAL_BONUS:
            break
        bonuses.append({
            "description": str(item.get("description") or "").strip(),
            "bonus": round(bonus, 2),
            "evidence_quote": str(item.get("evidence_quote") or "").strip()[:120],
            "rationale": str(item.get("rationale") or "").strip()[:200],
        })
        total += bonus

    return {"safety_net_bonuses": bonuses, "safety_net_score": round(total, 2)}
