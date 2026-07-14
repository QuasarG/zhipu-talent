from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


SPEC = TrackSpec(
    key="safety",
    label="大模型安全",
    evidence_focus="威胁模型、真实攻击面、攻击方法、防御、指标、生命周期治理与责任披露证据。",
    high_score_rule="必须交代攻击者权限、现实危害、防御效果和自适应绕过，安全关键词不能直接加分。",
    dimensions=(
        D("threat_model", "威胁模型与真实攻击面", 11, "看攻击者、目标、权限、约束和危害。"),
        D("attack_realism", "攻击方法的新颖性与现实性", 9, "看攻击是否创新、可复现且现实可行。"),
        D("defense", "防御与风险缓解效果", 10, "看覆盖、绕过成本、性能损失与适应性攻击。"),
        D("safety_evaluation", "安全评测与指标体系", 10, "看攻击成功率、检测率、误报率与覆盖面。"),
        D("governance", "生命周期治理与可解释性", 8, "看训练、部署、审计、治理与解释机制。"),
        D("safety_transfer", "跨模型与跨模态迁移", 7, "看方法能否迁移到其他模型、模态和场景。"),
        D("responsible_impact", "责任披露与实际影响", 5, "看漏洞确认、修复采用和责任披露。"),
    ),
)
