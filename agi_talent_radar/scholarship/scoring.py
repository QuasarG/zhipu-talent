"""奖学金评分参数单一真相源（与书院评估的 scoring_config 完全独立）。

调参只改这里；config_version 随内容变化，用于标注历史分数可比性。
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

# 材料完整性：resume / supplementary / achievement 各至少 1 份，letter 1-2 封
REQUIRED_KINDS = ("resume", "supplementary", "achievement")
MIN_LETTERS = 1
MAX_LETTERS = 2

# 脱敏评分维度：每项 0-5，加权到 100
DIMENSIONS = [
    {"key": "research_capability", "label": "研究能力", "max_points": 25},
    {"key": "originality", "label": "原创性", "max_points": 20},
    {"key": "achievement_quality", "label": "代表性成果质量", "max_points": 20},
    {"key": "engineering", "label": "工程与系统能力", "max_points": 15},
    {"key": "letter_endorsement", "label": "推荐信背书强度", "max_points": 10},
    {"key": "direction_fit", "label": "方向契合度", "max_points": 10},
]

# 舆情加减分：每条确认 ±5，总封顶 ±10
REPUTATION_ITEM_POINTS = 5.0
REPUTATION_CAP = 10.0


def config_version() -> str:
    """配置内容哈希：任何调参都会改变版本号。"""
    payload = {
        "eligibility": {k: sorted(v) if isinstance(v, set) else v for k, v in ELIGIBILITY.items()},
        "dimensions": DIMENSIONS,
        "reputation": [REPUTATION_ITEM_POINTS, REPUTATION_CAP],
        "directions": FOCUS_DIRECTIONS,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"scholarship-v1-{digest[:8]}"
