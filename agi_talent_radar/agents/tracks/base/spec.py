from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.agents.tracks.base.weights import WEIGHTS


SPEC = TrackSpec(
    key="base",
    label="Base 基模",
    evidence_focus="模型机制、架构、预训练、后训练、数据目标、Scaling、消融和泛化证据。",
    high_score_rule="必须说明改了什么机制、为什么有效、如何训练和验证，只有模型调用经验不能高分。",
    dimensions=(
        D("model_architecture", "模型机制与架构深度", WEIGHTS["model_architecture"], "看机制理解、架构创新及与已有方法的差异。"),
        D("training_method", "预训练与后训练方法", WEIGHTS["training_method"], "看预训练、SFT、RL、对齐与训练稳定性。"),
        D("data_objective", "数据与目标函数设计", WEIGHTS["data_objective"], "看数据配比、质量、训练目标、Reward 与 Loss。"),
        D("scaling_rigor", "Scaling 与实验严谨性", WEIGHTS["scaling_rigor"], "看模型规模、算力、基线、消融和 Scaling 趋势。"),
        D("frontier_originality", "前沿原创性", WEIGHTS["frontier_originality"], "看新假设、新机制和研究问题。"),
        D("generalization", "模型评估与泛化", WEIGHTS["generalization"], "看跨任务泛化、鲁棒性和评测完整性。"),
    ),
)
