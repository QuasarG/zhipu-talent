from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


SPEC = TrackSpec(
    key="ai4science",
    label="AI4Science",
    evidence_focus="科学问题、领域规律、科学数据、方法创新、计算或实验验证闭环与科学影响证据。",
    high_score_rule="必须证明科学问题成立、领域约束正确且预测经过科学验证，换领域数据刷榜不能高分。",
    dimensions=(
        D("scientific_problem", "科学问题定义", 11, "看问题是否真实、有价值且可验证。"),
        D("domain_validity", "领域规律与约束正确性", 10, "看是否符合生物、化学、物理等领域规律。"),
        D("scientific_data", "科学数据与 Benchmark 可信度", 8, "看数据来源、标签、泄漏、偏差和划分。"),
        D("scientific_method", "模型与方法创新", 8, "看创新来自科学建模、算法机制还是工程组合。"),
        D("experiment_loop", "计算与实验验证闭环", 10, "看模拟、湿实验、专家和外部数据验证。"),
        D("interdisciplinary_depth", "跨学科理解与协作深度", 7, "看 AI 与领域知识是否真正融合。"),
        D("scientific_impact", "科学影响与可复现性", 6, "看新发现、实验成本、研究效率和复现。"),
    ),
)
