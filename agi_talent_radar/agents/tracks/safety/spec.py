from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


SPEC = TrackSpec(
    key="safety",
    label="AI 与大模型安全",
    evidence_focus="威胁与漏洞建模、真实攻击面、自动化漏洞发现、Fuzzing/程序分析、防御工程、安全评测、AI/Agent 迁移与责任披露证据。",
    high_score_rule="经典软件安全方法可作为 AI 安全的可迁移基础正常计分；4 分以上必须有具体方法、本人贡献与验证，但不强求简历已写出所有面试级指标。",
    dimensions=(
        D("security_problem", "威胁、漏洞与攻击面建模", 10, "看目标、边界、攻击面、约束和现实危害。"),
        D("vulnerability_discovery", "漏洞发现与攻击测试", 10, "看 Fuzzing、程序分析、攻击复现、覆盖和失败归因。"),
        D("defense", "防御与风险缓解", 9, "看防御设计、检测能力、绕过分析与性能代价。"),
        D("safety_evaluation", "安全评测与验证闭环", 9, "看指标、对照、覆盖面、复现和结果验证；简历缺指标作为待验证点而非直接归零。"),
        D("security_engineering", "安全工程与自动化", 9, "看可运行工具、Harness、分析框架、扩展性和工程闭环。"),
        D("ai_safety_transfer", "AI / Agent 安全迁移", 8, "看经典安全方法如何迁移到模型、Agent、多模态或 AI 开发链。"),
        D("responsible_impact", "真实影响与责任披露", 5, "看项目验收、漏洞确认、修复采用、论文与开源产物。"),
    ),
)
