from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.agents.tracks.agent.weights import WEIGHTS


W = WEIGHTS


SPEC = TrackSpec(
    key="agent",
    label="Agent",
    evidence_focus="Agent 任务与环境、方法/架构创新、工具与行动闭环、自主决策、验证可靠性和可运行系统证据。",
    high_score_rule="允许 Coding Agent、Agentic Fuzzing、安全 Agent、多 Agent 协同和通用助手等不同研究范式。不要因简历未显式写出 Planner/Memory/Checkpoint 名词就判定没有 Agent 方法；应结合任务、行动空间、多步决策、工具使用和验证机制评价。仅调用模型或拼装 Workflow 仍不能高分。",
    dimensions=(
        D("task_environment", "Agent 任务与环境定义", W["task_environment"], "看任务边界、可观测状态、行动/工具空间和成功标准。Harness 生成、软件修复、风险识别等专用任务均可正常计分。"),
        D("agent_method", "Agent 方法与架构创新", W["agent_method"], "3 分：有具体 Agent 方法或协同机制；4 分：提出原创架构/决策机制并有成果验证；5 分：形成可迁移的 Agent 方法论。不限定必须出现某些组件名。"),
        D("tool_action_loop", "工具使用与行动闭环", W["tool_action_loop"], "看 Agent 如何生成、调用、观测并修正行动；真实工具链、多步环境交互和自动验证可高分。"),
        D("verification_reliability", "评估、验证与可靠性", W["verification_reliability"], "看成功标准、自动验证、对照、失败归因和测试环境。简历未披露完整指标只在本维度保守，不在其他维度重复扣分。"),
        D("agent_system", "Agent 系统实现", W["agent_system"], "看是否形成可运行系统、实验平台或生产原型，以及稳定性、成本和工程质量。"),
        D("agent_research_impact", "Agent 研究成果与方向持续性", W["agent_research_impact"], "3 分：有可核验的 Agent 项目、系统或投稿；4 分：多项相关成果形成连续主线，且至少一项经过正式同行评议；4.5-5 分：有多项高水平成果、清晰主要贡献并形成方法影响。拟投与已接收必须区分。"),
    ),
)
