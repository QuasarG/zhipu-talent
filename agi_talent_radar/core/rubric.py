"""Legacy v1 rubric retained for regression coverage; inactive in multi-track scoring."""

from __future__ import annotations

from agi_talent_radar.core.models import RubricDimension


CORE_POTENTIAL_KEYS = {
    "learning_growth",
    "research_exploration",
    "engineering_practice",
    "ai_agent_leverage",
    "problem_definition",
    "ownership",
    "cultivation_value",
}

BREAKTHROUGH_AXIS_KEYS = {
    "research_exploration",
    "engineering_practice",
    "ai_agent_leverage",
    "problem_definition",
    "ownership",
}

AUXILIARY_PROFILE_KEYS = {
    "education_signal",
    "academic_output",
    "project_richness",
    "impact_visibility",
    "direction_fit",
}

CALIBRATION_REFERENCE = """
本批 10 个虚构候选人的评估校准锚点（只用于定义判断标准，不要机械按候选人 ID 打分）：
- 优先看好的高潜画像：candidate_02、candidate_07、candidate_08、candidate_01、candidate_03。
  共同点不是学校或论文最亮，而是有可验证闭环、AI/Agent 杠杆、工程交付、问题拆解和本人动作。
  candidate_02 的标志是“构图-出题-求解-验证-反思”闭环、符号/数值/一致性认证、错误拦截与修复；
  candidate_07 的标志是 Coding Agent、失败测试复现、patch 验证、环境配置和可复现性自动化；
  candidate_08 的标志是 Agent 平台、sandbox/事件总线/工作流、具身代码解释器和开源/队长信号；
  candidate_01 的标志是长上下文机制、Triton kernel、显存/吞吐指标和评测流水线；
  candidate_03 的标志是模型路由、成本-效果优化、分步 GUI Agent 和 test-time scaling。
- 谨慎看待的“光鲜但未必高潜”画像：candidate_04、candidate_05、candidate_06、candidate_09、candidate_10。
  它们可能有论文、方向和技术栈，但如果缺少 AI 杠杆、真实闭环、本人贡献边界或可验证指标，不应和上面的高潜样本挤在同一分段。
  candidate_06 是强系统候选，可以高于普通候选，但不能只因论文/量化方向冲顶；
  candidate_10 跨域很漂亮，但若“显著降低幻觉率/提升稳定性”等缺 baseline 和量化定义，应明显低于闭环证据更硬的 Agent/工程候选；
  candidate_04/05/09 属于专业能力不错的方向型候选，除非补足闭环与 ownership，否则更适合备选而非优选。
- 最终目标：找能在 AGI 时代快速把问题定义、工具杠杆、工程闭环和验证机制串起来的人，而不是传统履历排序第一的人。
""".strip()

RUBRIC: list[RubricDimension] = [
    # === 潜力维度（核心，总权重 88%）===
    RubricDimension(
        key="learning_growth",
        label="学习与成长潜力",
        weight=0.08,
        why_it_matters="AGI 时代技术栈更新极快，能否跨工具、跨任务持续迁移，比当前头衔更关键。",
        evidence_rule="优先看复现-失败-修正-再验证链路；只有泛泛写学习能力或多方向经历时不得高分。",
    ),
    RubricDimension(
        key="research_exploration",
        label="研究探索能力",
        weight=0.10,
        why_it_matters="高潜人才需要提出可检验的新假设，而不是只跟随已有 benchmark 刷点或论文包装。",
        evidence_rule="必须看到假设、机制、约束建模、消融、错误归因或一作主线；仅有论文题目不等于强研究。",
    ),
    RubricDimension(
        key="engineering_practice",
        label="工程实践能力",
        weight=0.16,
        why_it_matters="优秀 AI 研究正在工程化，能不能把想法跑成系统会直接影响成长上限。",
        evidence_rule="强证据必须包含可运行产物、具体技术栈、性能/稳定性指标或线上/评测闭环。",
    ),
    RubricDimension(
        key="ai_agent_leverage",
        label="AI 工具 / Agent 使用能力",
        weight=0.14,
        why_it_matters="会用 Agent 组织任务、验证结果和降低成本的人，会更早形成复利。",
        evidence_rule="重点看多智能体、工具调用、自动验证、RAG、代码执行、路由、反思闭环等真实 AI 杠杆。",
    ),
    RubricDimension(
        key="problem_definition",
        label="问题定义与独立思考",
        weight=0.16,
        why_it_matters="黑马通常不是简历背景最亮的人，而是能把真实问题拆成可验证假设的人。",
        evidence_rule="必须看到痛点、约束、失败模式、baseline、评价指标、任务边界或取舍逻辑。",
    ),
    RubricDimension(
        key="ownership",
        label="项目 Ownership",
        weight=0.14,
        why_it_matters="培养价值来自可托付程度，能否独立负责闭环比参与项目更重要。",
        evidence_rule="优先看负责、设计、提出、维护、构建、开发、负责人、一作；只写参与/协助要明显降分。",
    ),
    RubricDimension(
        key="cultivation_value",
        label="长期培养价值",
        weight=0.10,
        why_it_matters="最终筛选目标是长期成长为研究者、工程师或技术 leader 的可能性，而不是当前履历好看。",
        evidence_rule="综合技术深度、工程闭环、方向稀缺性、可迁移性和风险；不能作为泛化兜底高分项。",
    ),
    # === 履历维度（辅助，总权重 12%）===
    RubricDimension(
        key="education_signal",
        label="教育背景信号",
        weight=0.02,
        why_it_matters="教育背景只能作为基础训练信号，不能替代项目证据。",
        evidence_rule="仅使用标准化分级信号；学校、GPA、排名不得直接推高总体结论。",
    ),
    RubricDimension(
        key="academic_output",
        label="学术产出信号",
        weight=0.035,
        why_it_matters="论文是研究能力的可验证痕迹，但需区分一作/挂名、已发表/拟投。",
        evidence_rule="区分已接收/在投、一作/共同参与；论文题目本身不能替代方法和贡献证据。",
    ),
    RubricDimension(
        key="project_richness",
        label="项目 / 实习丰富度",
        weight=0.025,
        why_it_matters="项目数量和领域覆盖度能反映候选人的实践广度和工程接触面。",
        evidence_rule="只做辅助参考；项目多但缺少具体动作、指标和 ownership 时不能高分。",
    ),
    RubricDimension(
        key="impact_visibility",
        label="成果影响力 / 可见度",
        weight=0.02,
        why_it_matters="开源贡献、竞赛、专利等外部可见成果能降低信息不对称。",
        evidence_rule="只认可可验证外部影响，如开源 star/fork、奖项、专利、被采用；空泛影响力不加分。",
    ),
    RubricDimension(
        key="direction_fit",
        label="方向匹配度",
        weight=0.02,
        why_it_matters="候选人的研究方向、技术栈与目标岗位的契合度影响培养周期。",
        evidence_rule="只作为培养路径匹配参考；方向对口但证据薄弱不能进入高分层。",
    ),
]


DIMENSION_LABELS = {item.key: item.label for item in RUBRIC}


TECH_STACK_TERMS = {
    "PyTorch",
    "Triton",
    "CUDA",
    "TorchTitan",
    "Transformers",
    "vLLM",
    "LM-Eval",
    "SymPy",
    "Ray",
    "Docker",
    "Kubernetes",
    "CLIP",
    "LLaVA",
    "Qwen-VL",
    "OpenCV",
    "Gaussian Splatting",
    "Mamba",
    "MMDetection",
    "DeepSpeed",
    "Megatron",
    "TensorRT",
    "Playwright",
    "Git",
    "FastAPI",
    "React",
    "Rust",
    "Node.js",
    "Omniverse",
    "PaddleOCR",
    "LayoutLM",
    "Donut",
    "PDF parsing",
    "Hugging Face",
    "RAG",
    "RLHF",
    "RLVR",
    "scikit-learn",
}

ACTION_TERMS = {
    "提出",
    "设计",
    "构建",
    "负责",
    "实现",
    "复现",
    "维护",
    "开发",
    "优化",
    "改进",
    "自动",
    "验证",
    "评测",
    "分析",
    "降低",
    "提升",
    "修复",
    "探索",
    "引入",
    "解决",
}

METRIC_MARKERS = {"提升", "降低", "减少", "达到", "覆盖", "%", "倍", "star", "F1", "mAP", "128K", "4B", "300+"}

OWNERSHIP_MARKERS = {"负责", "提出", "设计", "构建", "实现", "维护", "开发", "一作", "负责人", "队长"}

DIMENSION_KEYWORDS: dict[str, set[str]] = {
    "learning_growth": {
        "复现",
        "跨模态",
        "跨领域",
        "错误归因",
        "持续学习",
        "多任务",
        "实验自动化",
        "评测",
        "benchmark",
        "ablation",
    },
    "research_exploration": {
        "提出",
        "机制",
        "范式",
        "建模",
        "消融",
        "拟投",
        "Under Review",
        "一作",
        "逻辑一致性",
        "约束",
        "奖励",
        "谱正则化",
    },
    "engineering_practice": {
        "Triton",
        "CUDA",
        "kernel",
        "流水线",
        "Docker",
        "Kubernetes",
        "FastAPI",
        "React",
        "Playwright",
        "TensorRT",
        "DeepSpeed",
        "Megatron",
        "sandbox",
        "事件总线",
        "训练脚本",
    },
    "ai_agent_leverage": {
        "Agent",
        "多智能体",
        "路由",
        "验证",
        "反思",
        "RAG",
        "代码解释器",
        "SWE",
        "工具",
        "自动完成",
        "任务订阅",
        "工作流",
    },
    "problem_definition": {
        "针对",
        "问题",
        "约束",
        "错误",
        "一致性",
        "baseline",
        "评测指标",
        "风险",
        "误报",
        "漏召",
        "低资源",
        "低成本",
        "长尾",
    },
    "ownership": OWNERSHIP_MARKERS,
    "cultivation_value": {
        "闭环",
        "平台",
        "系统",
        "高效",
        "长期",
        "稀缺",
        "leader",
        "架构",
        "自动化",
        "数据治理",
        "开源",
    },
    "education_signal": {"985", "211", "双一流", "GPA", "排名", "Top", "博士", "硕士", "本科"},
    "academic_output": {"一作", "CCF-A", "NeurIPS", "ICML", "ICLR", "ACL", "CVPR", "ICCV", "ECCV", "AAAI", "IJCAI", "拟投", "Under Review"},
    "project_richness": {"项目", "实习", "经历", "多个", "系列", "平台", "系统"},
    "impact_visibility": {"开源", "GitHub", "star", "竞赛", "获奖", "专利", "技术博客"},
    "direction_fit": {"方向", "岗位", "匹配", "相关", "对口"},
}


def rubric_as_markdown() -> str:
    rows = ["| 维度 | 权重 | 为什么重要 | 取证方式 |", "| --- | ---: | --- | --- |"]
    for item in RUBRIC:
        rows.append(f"| {item.label} | {item.weight:.0%} | {item.why_it_matters} | {item.evidence_rule} |")
    return "\n".join(rows)
