"""奖学金评分参数单一真相源（与书院评估的 scoring_config 完全独立）。

调参只改这里；config_version 随内容变化，用于标注历史分数可比性。
v2 维度重构（评分 agent 版）：拆掉笼统的"研究能力"，正交化为
学术贡献/原创性/独立性三轴；方向契合降为 0（资格 gate 已管），
仅作为同分 tie-breaker 描述注入 prompt，不占分数。
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

# 脱敏评分维度：每项 0-5，加权到 100（v2 正交化 + 年级校准锚点）
DIMENSIONS = [
    {
        "key": "academic_impact", "label": "学术贡献与影响力", "max_points": 25,
        "anchors": "0-1 无可验证学术产出；2 有 workshop/普通刊物或合作署名；3 该年级扎实水平（博士中期=主流会议一作）；4 顶会顶刊一作或高被引/开源广泛复用；5 按在读年限看显著超出预期（如低年级顶会一作多篇）",
    },
    {
        "key": "originality", "label": "原创性与问题品味", "max_points": 20,
        "anchors": "0-1 跟随性工作或无明确问题；2 在已有框架内做增量改进；3 提出有新意的角度或非常规路径，有一定佐证；4 提出新问题/新范式且有初步验证；5 开创性问题定义，社区可见的独立思想（不依赖是否已发表）",
    },
    {
        "key": "independence", "label": "独立性与成长斜率", "max_points": 20,
        "anchors": "0-1 全部工作为课程/导师指令产物；2 参与明确分工的项目；3 有自主发起的子课题并完成闭环；4 主导 0→1 项目（自己定义方案并驱动完成），近两年产出斜率陡；5 多次从零发起并产出有影响力成果，导师角色是支持者而非驱动者",
    },
    {
        "key": "engineering", "label": "工程与落地能力", "max_points": 15,
        "anchors": "0-1 无工程痕迹或仅调用 API；2 完成课程级/复现级系统；3 独立实现可运行的完整系统（代码/工件佐证）；4 系统有真实用户/开源影响力/复现细节严谨；5 大规模基础设施级贡献或开源社区核心维护者",
    },
    {
        "key": "letter_endorsement", "label": "推荐信背书强度", "max_points": 10,
        "anchors": "0-1 模板化泛泛之词；2 具体描述了工作内容；3 有具体事例+横向比较（如近年学生前 X%）；4 强比较陈述（如十年最强三人）+具体证据支撑；5 极强背书且证据链完整可信",
    },
    {
        "key": "integrity_risk", "label": "诚信与一致性", "max_points": 10,
        "anchors": "0-1 经历明显矛盾或成果存疑且无解释；2-3 存在未解释的疑点；4-5 有轻微矛盾但可解释（本维度反向：分高=一致可信）；6-7 基本一致，个别处信息不足；8-10 材料内部一致、时间线合理、佐证互洽。理由中必须写明发现的任何疑点供人工复核",
    },
]

# 推荐档位（LLM 输出，辅助组合选择，不替代总分排序）
RECOMMEND_TIERS = ["strong", "recommend", "borderline", "not_recommend"]

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
        "directions": FOCUS_DIRECTIONS,
        "tiers": RECOMMEND_TIERS,
        "evidence_levels": EVIDENCE_LEVELS,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"scholarship-v2-{digest[:8]}"
