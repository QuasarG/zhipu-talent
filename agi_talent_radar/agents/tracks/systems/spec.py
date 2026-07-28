from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.agents.tracks.systems.weights import WEIGHTS


SPEC = TrackSpec(
    key="systems",
    label="Systems 大模型系统",
    evidence_focus="训练推理性能、系统架构、基线条件、软硬件协同、可靠性、可观测性和生产交付证据。",
    high_score_rule="必须说明瓶颈、测试条件、公平基线和稳定收益，不同硬件或模型上的指标不能直接比较。",
    dimensions=(
        D("performance", "训练与推理性能优化", WEIGHTS["performance"], "看吞吐、延迟、显存、成本、利用率和扩展效率。"),
        D("system_architecture", "系统架构深度", WEIGHTS["system_architecture"], "看并行、调度、缓存、通信、Serving 和容错。"),
        D("performance_baseline", "性能指标与公平基线", WEIGHTS["performance_baseline"], "看硬件、模型、Batch、数据和测试条件可比性。"),
        D("hardware_software", "软硬件协同设计", WEIGHTS["hardware_software"], "看 GPU、算子、内存、通信和模型结构协同。"),
        D("system_reliability", "可靠性与可观测性", WEIGHTS["system_reliability"], "看稳定性、监控、调试、降级和故障恢复。"),
        D("production_delivery", "可复现性与生产交付", WEIGHTS["production_delivery"], "看代码、配置、环境、部署和真实采用。"),
        D("systems_transfer", "可迁移的系统洞见", WEIGHTS["systems_transfer"], "看方法能否迁移到其他模型、硬件和负载。"),
    ),
)
