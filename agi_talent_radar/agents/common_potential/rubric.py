from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.core.models import RubricDimension


COMMON_RUBRIC = (
    D("problem_definition", "问题定义与独立判断", 8, "看真实问题、约束、边界、失败模式与取舍。"),
    D("research_rigor", "探索严谨性与验证能力", 8, "看 baseline、对照、消融、失败分析和可证伪验证。"),
    D("learning_transfer", "学习迁移与认知成长", 5, "看跨任务迁移、失败修正和认知变化。"),
    D("ownership", "Ownership 与贡献边界", 7, "看本人提出、设计、实现、维护和推进范围。"),
    D("evidence_credibility", "证据可信度与可复现性", 5, "看条件、数据、指标、产物和可核验性。"),
    D("growth_trajectory", "长期研究品味与成长轨迹", 4, "看问题选择是否持续深入并形成清晰主线。"),
)

COMMON_MAX_POINTS = sum(item.max_points for item in COMMON_RUBRIC)
COMMON_DIMENSION_LABELS = {item.key: item.label for item in COMMON_RUBRIC}
COMMON_RUBRIC_MODELS = [
    RubricDimension(
        key=item.key,
        label=item.label,
        weight=item.max_points / 100,
        why_it_matters="跨 Track 的通用潜力与长期培养价值。",
        evidence_rule=item.evidence_rule,
    )
    for item in COMMON_RUBRIC
]
