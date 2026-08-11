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

判断标准（自行判断什么是"稀缺且可核验的外部成就"）：
- 该成就能被第三方核验（有公开编号/排名/记录/奖项），不是自述
- 该成就在其同龄人/同阶段中属于极少数人能达到的（稀缺性）
- 该成就未被 common（通用潜力）和 track（专业能力）和 publication（论文）评价过

明确不加分的：
- 学校名气、机构档位、导师头衔（违反评分哲学）
- 项目能力、论文数量（已被其它维度覆盖）
- GPA、课程成绩（已脱敏折叠）
- 普通竞赛获奖、校级荣誉、奖学金（不够稀缺）

判断原则：
1. 只对可核验的外部成就加分，证据必须能在 resume_raw 里定位到原文。
2. 宁缺毋滥——大多数人不应获得加分。
3. bonus 取值：极稀缺 1.5-2.0，显著 0.5-1.0，不显著不给分。

只输出 JSON 对象：
{
  "bonuses": [
    {
      "description": "成就描述（一句话）",
      "bonus": 1.5,
      "evidence_quote": "简历原文片段",
      "rationale": "为什么这是分项评分未覆盖但值得加分的稀缺成就"
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
            temperature=0.0,
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
