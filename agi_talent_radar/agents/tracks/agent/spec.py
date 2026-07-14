from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


SPEC = TrackSpec(
    key="agent",
    label="Agent",
    evidence_focus="任务环境、Harness、规划、工具、记忆、长程执行、自我进化、验证和可靠性证据。",
    high_score_rule="必须证明 Agent 的决策、验证、恢复与持续学习，简单 Workflow 或套框架不能高分。",
    dimensions=(
        D("task_environment", "任务、环境与 Harness 定义", 10, "看任务边界、环境、工具空间和成功标准。"),
        D("agent_architecture", "Agent 架构设计", 10, "看 Planner、Memory、Tool、Executor 与状态管理。"),
        D("long_horizon", "长程任务能力", 10, "看任务拆解、持续执行、Checkpoint 和恢复。"),
        D("verification_reliability", "评估、验证与可靠性", 12, "看成功率、自动验证、失败归因和测试环境。"),
        D("self_evolution", "持续学习与自我进化", 10, "看经验积累、技能沉淀、自训练和共同进化。"),
        D("agent_system", "系统实现与运行效率", 8, "看可运行系统、延迟、成本、稳定性和工程质量。"),
    ),
)
