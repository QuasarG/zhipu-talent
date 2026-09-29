"""奖学金评分参数单一真相源（与书院评估的 scoring_config 完全独立）。

调参只改这里；config_version 随内容变化，用于标注历史分数可比性。
v3 维度重构（2026-09 评审章程版）：五维百分制权重（40/30/20/5/5），
去掉 0-5 级锚点改为考察要点软引导，评分 agent 在权重区间内自由打分
以拉开分差；亮点/异常点/特别栏目不设条数上限；Integrity 维度 agent
仅有提出疑点的权力，判定与取消资格由人工完成；不再输出推荐档位，
列表按总分排序。论文核验数据由 agent 工作过程中产生并随评分统一返回。
"""
from __future__ import annotations

import hashlib
import json

# 章程硬门槛
ELIGIBILITY = {
    "degree_types": {"master", "phd"},       # 硕士 / 博士在读
    "min_graduation": "2027-06",             # 预计毕业时间不早于 2027-06
}

# 重点支持方向（章程）
FOCUS_DIRECTIONS = [
    "Foundation Models",
    "Multimodal Intelligence",
    "Agent Systems",
    "Reinforcement Learning",
    "AI Infrastructure",
    "AI for Science",
    "Embodied Intelligence",
]

# 材料完整性：resume / achievement 各至少 1 份，letter 1-2 封
REQUIRED_KINDS = ("resume", "achievement")
MIN_LETTERS = 1
MAX_LETTERS = 2

# v3 五维权重制：无等级锚点，focus 为考察要点软引导（来自 2026-09 评审章程），
# bonus_hints 为叙述性加分参考——不写死分值，全权由评分 agent 判断。
DIMENSIONS = [
    {
        "key": "academic_impact", "label": "学术成果与影响力", "label_en": "Academic Achievement & Impact",
        "max_points": 40,
        "focus": "重点考察申请人的代表性学术成果，包括论文质量、学术贡献及国际影响力。综合考虑论文发表情况（CCF A、顶会、顶刊）、第一作者或共同第一作者贡献、论文引用情况等。",
        "bonus_hints": "Best Paper / Best Paper Nomination、Nature / Science 等顶级期刊、顶会 Oral、Findings、高引用代表性论文等。",
    },
    {
        "key": "originality", "label": "原创能力与生态贡献", "label_en": "Originality & Ecosystem Contribution",
        "max_points": 30,
        "focus": "重点考察申请人的原创能力、技术创新性及对 AI 开源生态的贡献。关注是否提出新的研究方法、技术框架或研究方向，以及开源项目、Benchmark、数据集、工具链等对社区的实际影响。",
        "bonus_hints": "高质量开源项目、GitHub Stars、Downloads、Benchmark 被广泛采用、社区影响力、生态贡献等。",
    },
    {
        "key": "independence", "label": "独立研究与技术工程能力", "label_en": "Independence & Execution",
        "max_points": 20,
        "focus": "重点考察申请人独立开展研究和技术实现的能力，是否能够将研究想法转化为系统、平台或工程成果，并完成完整验证。",
        "bonus_hints": "独立完成系统性创新、实际应用落地、产业应用、完整系统开发等。",
    },
    {
        "key": "letter_endorsement", "label": "导师评价", "label_en": "Recommendation",
        "max_points": 5,
        "focus": "综合参考导师推荐意见，重点关注申请人的研究能力、成长潜力、科研态度及综合表现。",
        "bonus_hints": "推荐意见具体、长期指导关系明确、有充分事实支撑。",
    },
    {
        "key": "integrity_risk", "label": "材料真实性与学术诚信", "label_en": "Integrity",
        "max_points": 5,
        "focus": "对申请材料真实性、成果归属、学术诚信及信息一致性进行核验。注意：本维度分数仅反映材料一致性程度；发现的任何疑点必须写入 anomalies 列表供人工复核，评分 agent 无权判定取消评审资格。",
        "bonus_hints": "（本维度无加分项）如发现学术不端、虚假陈述或材料造假的迹象，在 anomalies 中详细描述，由人工决定后续处理。",
    },
]

# 评分公平性约束（注入评分 agent prompt）：材料丰富度 ≠ 能力
FAIRNESS_RULES = """
评分公平性约束（必须遵守）：
- 评估的是能力与贡献，不是材料的详细程度。附件多、论文全上传不构成任何加分依据；
  附件少、只有代表作的候选人，若单篇质量与影响力更高，应得更高的分。
- 材料缺失只降低对应 claim 的证据置信度（evidence_level 降级），不直接扣能力分。
- 自述与已核验的事实必须区分：核验过的成果按实际水平计分，仅自述的按 claimed
  证据处理并在 anomalies 里提示，而不是直接按自述内容给高分。
- 对不同年级的申请人使用同一能力标尺，不因低年级而放水，也不因高年级而苛求。
""".strip()

# 证据分级（submit_scores 里每条关键 claim 必须标注）
EVIDENCE_LEVELS = {
    "verified": "公开库查证存在（venue/年份可核对）",
    "supported": "未公开收录但佐证材料完整可信（论文原文等）",
    "claimed": "仅自述/截图/无独立佐证",
}


def config_version() -> str:
    """配置内容哈希：任何调参都会改变版本号。"""
    payload = {
        "eligibility": {k: sorted(v) if isinstance(v, set) else v for k, v in ELIGIBILITY.items()},
        "dimensions": DIMENSIONS,
        "fairness": FAIRNESS_RULES,
        "directions": FOCUS_DIRECTIONS,
        "evidence_levels": EVIDENCE_LEVELS,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"scholarship-v3-{digest[:8]}"
