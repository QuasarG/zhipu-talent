# AGI 人才雷达 · 评估维度与权重全量说明

> 本文档基于 `agi_talent_radar/agents/` 下的真实配置生成，覆盖所有 Track 的维度、分值、证据规则、校准逻辑与总分聚合方式。
> 配置权威源以代码常量为准：通用潜力在 `common_potential/rubric.py`，各 Track 在 `tracks/<name>/spec.py`，聚合在 `aggregation/nodes.py`。

---

## 0. 总览：100 分怎么来

整体评分由两大块**绝对分值上限**叠加得到 0-100 的 `overall_score`（不是百分比系数，是"每块最多能拿多少分"）：

| 分项 | 满分 | 评估对象 | 代码位置 |
|---|---|---|---|
| 通用潜力（Common Potential） | **40** | 跨 Track 通用的元能力 | `common_potential/rubric.py` |
| Track 专业能力（按权重聚合） | **60** | 候选人路由到的 1-3 个 Track | `tracks/<name>/spec.py` |

> 原"简历视觉表达质量" 3 分已随多模态视觉管线一并移除（PDF 改为文本层提取 + 本地 OCR 兜底），其分值并入通用潜力。

核心公式（`aggregation/nodes.py:30`）：

```python
total = clip(common_score + track_total, 0, 100)
overall = int(round(total))
```

**多 Track 聚合公式**（`aggregation/nodes.py:13-28`）：

```python
track_total = Σ ( assignment.weight × track_result.calibrated_score )
```

- `assignment.weight ∈ [0, 1]`，所有命中 Track 的权重和 ≤ 1（例如 base 0.7 + agent 0.3）。
- `calibrated_score ∈ [0, 60]`，每条 Track 自己的满分上限。
- 极端情形：base 0.7 + agent 0.3 且两条都拿满分 60，`0.7×60 + 0.3×60 = 60`，所以 Track 分项整体不超过 60。

**最终档位阈值**（`aggregation/nodes.py:77-82`，`formatter.py:170-175` 双副本）：

| overall_score | level | tier | 库 |
|---|---|---|---|
| `>= 90` | S | 强烈建议沟通 | 优选库 |
| `>= 80` | A | 强烈建议沟通 | 优选库 |
| `>= 60` | B | 建议沟通 | 备选库 |
| `< 60` | C | 暂缓 / 需补充信息 | 不建议后续沟通 |

---

## 1. 通用潜力维度（Common Potential · 40 分）

> 评价"跨 Track 都成立的元能力"，**不评价具体方向熟练度**。
> 来源：`agi_talent_radar/agents/common_potential/rubric.py:5-12` 的 `COMMON_RUBRIC` 元组。

| 序号 | key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|---|
| 1 | `problem_definition` | 问题定义与独立判断 | 8 | 看科研、项目或实习/工作中的真实问题、约束、边界、失败模式与取舍。 |
| 2 | `research_rigor` | 探索严谨性与验证能力 | 9 | 看 baseline、对照、消融、失败分析和可证伪验证；已发表的高水平同行评议成果是外部验证，但不自动等于满分。 |
| 3 | `learning_transfer` | 学习迁移与认知成长 | 3 | 看跨任务迁移、失败修正和认知变化。 |
| 4 | `ownership` | Ownership 与贡献边界 | 8 | 看项目或实习/工作中本人提出、设计、实现、维护和推进范围；岗位名与机构档位不代表 ownership。 |
| 5 | `evidence_credibility` | 证据可信度与可复现性 | 9 | 看条件、数据、指标、产物和可核验性。正式同行评议成果、高含金量验收、可运行产物或可核验生产指标应加分；机构名气和拟投状态不构成强证据。 |
| 6 | `growth_trajectory` | 长期研究品味与成长轨迹 | 3 | 看问题选择是否持续深入并形成清晰主线。 |
| | | **合计** | **40** | |

**校准规则**（`common_potential/nodes.py`）：

1. **无证据封顶 1 分**：维度引用的 `evidence_ids` 全部不可追溯时，分数压到 1。
2. **验证锚点封顶 2.5 分**：`research_rigor` / `evidence_credibility` 引用证据缺少量化指标、具体工具、可运行产物、验收/上线/可复现记录或正式发表成果时封顶 2.5。评分 prompt 中有同样的硬性锚点。
3. **高分支撑校验**：`score >= 4` 但缺"量化指标 + 工具 + ownership"组合证据时，封顶 3.5。
4. **研究成果组合保底**（`_apply_research_portfolio_floors`）：当 strong_sources ≥ 6、owned ≥ 3、published ≥ 2 同时满足，给六维设下限：

   ```python
   floors = {
       "problem_definition": 4.0, "research_rigor": 4.0,
       "learning_transfer": 3.5, "ownership": 4.5,
       "evidence_credibility": 4.5, "growth_trajectory": 4.0,
   }
   ```

> 注：曾实验过基于 owned/metric/tool 证据计数的"工程闭环保底"，因证据提取器的标记存在轮次间波动（同一份简历不同轮次 flag 数量差异很大），保底会放大噪声，已移除。

---

## 2. Track 专业维度（60 分 / 每条 Track）

> 每条 Track 都是独立的一组维度，**自身满分都恰好 60**。
> 通用数据结构见 `tracks/shared/spec.py:8-44`（`TrackDimensionSpec` / `TrackSpec`）。

### 2.1 `base` · Base 基模（60 分）

来源：`tracks/base/spec.py:5-18`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `model_architecture` | 模型机制与架构深度 | 14 | 看机制理解、架构创新及与已有方法的差异。 |
| `training_method` | 预训练与后训练方法 | 12 | 看预训练、SFT、RL、对齐与训练稳定性。 |
| `data_objective` | 数据与目标函数设计 | 9 | 看数据配比、质量、训练目标、Reward 与 Loss。 |
| `scaling_rigor` | Scaling 与实验严谨性 | 10 | 看模型规模、算力、基线、消融和 Scaling 趋势。 |
| `frontier_originality` | 前沿原创性 | 9 | 看新假设、新机制和研究问题。 |
| `generalization` | 模型评估与泛化 | 6 | 看跨任务泛化、鲁棒性和评测完整性。 |
| | **合计** | **60** | |

- **证据重点**：模型机制、架构、预训练、后训练、数据目标、Scaling、消融和泛化证据。
- **高分规则**：必须说明改了什么机制、为什么有效、如何训练和验证，只有模型调用经验不能高分。

---

### 2.2 `agent` · Agent（60 分）

来源：`tracks/agent/spec.py:5-18`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `task_environment` | Agent 任务与环境定义 | 8 | 看任务边界、可观测状态、行动/工具空间和成功标准。Harness 生成、软件修复、风险识别等专用任务均可正常计分。 |
| `agent_method` | Agent 方法与架构创新 | 14 | 3 分：有具体 Agent 方法或协同机制；4 分：提出原创架构/决策机制并有成果验证；5 分：形成可迁移的 Agent 方法论。不限定必须出现某些组件名。 |
| `tool_action_loop` | 工具使用与行动闭环 | 10 | 看 Agent 如何生成、调用、观测并修正行动；真实工具链、多步环境交互和自动验证可高分。 |
| `verification_reliability` | 评估、验证与可靠性 | 10 | 看成功标准、自动验证、对照、失败归因和测试环境。简历未披露完整指标只在本维度保守，不在其他维度重复扣分。 |
| `agent_system` | Agent 系统实现 | 8 | 看是否形成可运行系统、实验平台或生产原型，以及稳定性、成本和工程质量。 |
| `agent_research_impact` | Agent 研究成果与方向持续性 | 10 | 3 分：有可核验的 Agent 项目、系统或投稿；4 分：多项相关成果形成连续主线，且至少一项经过正式同行评议；4.5-5 分：有多项高水平成果、清晰主要贡献并形成方法影响。拟投与已接收必须区分。 |
| | **合计** | **60** | |

- **证据重点**：Agent 任务与环境、方法/架构创新、工具与行动闭环、自主决策、验证可靠性和可运行系统证据。
- **高分规则**：允许 Coding Agent、Agentic Fuzzing、安全 Agent、多 Agent 协同和通用助手等不同研究范式。不要因简历未显式写出 Planner/Memory/Checkpoint 名词就判定没有 Agent 方法；应结合任务、行动空间、多步决策、工具使用和验证机制评价。仅调用模型或拼装 Workflow 仍不能高分。

---

### 2.3 `safety` · AI 与大模型安全（60 分）

来源：`tracks/safety/spec.py:5-18`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `security_insight` | 安全问题洞察与威胁建模 | 10 | 3 分：能定义具体攻击面和目标；4 分：多个真实问题中都有独立建模与边界判断；5 分：形成可迁移的威胁建模方法并产生广泛影响。 |
| `method_innovation` | 方法创新与技术深度 | 14 | 3 分：改造具体安全方法或工具；4 分：提出原创机制并有多条项目/论文证据；5 分：方法成为可复用的技术路线。程序分析、Fuzzing、攻击或防御任一专长都可高分。 |
| `validation_rigor` | 实验验证与研究严谨性 | 12 | 3 分：有基本测试或项目验收；4 分：有完整对照、量化指标或多项同行评议成果交叉验证；5 分：有强复现、失败归因和外部采用。简历未展开实验表时不得低估已正式发表成果的基本验证价值。 |
| `research_impact` | 研究成果与外部验证 | 10 | 3 分：有可核验项目、专利或投稿；4 分：有两项及以上已发表高水平同行评议成果或高含金量验收；5 分：形成学术/产业广泛影响。拟投与已接收必须区分。 |
| `security_engineering` | 安全工程与系统实现 | 8 | 3 分：实现可运行原型或自动化工具；4 分：多个系统产物与研究方法闭环；5 分：系统可复用、可扩展并被外部使用。 |
| `ai_safety_transfer` | AI / Agent 安全迁移潜力 | 6 | 3 分：有明确 AI/Agent 安全课题或成果；4 分：已将安全方法迁移到 Agent/模型并形成方法；5 分：迁移经过强验证且可泛化。该项评价迁移潜力，不用来否定经典安全专长。 |
| | **合计** | **60** | |

- **证据重点**：安全问题洞察、威胁与漏洞建模、程序分析/Fuzzing/攻防方法创新、实验验证、可运行安全系统、高质量成果与 AI/Agent 安全迁移证据。
- **高分规则**：按安全研究者的核心能力评价，不要要求同一人同时覆盖攻击、防御、治理和所有 AI 安全子方向。多项独立负责的安全项目、有方法创新的可运行工具、已正式发表的高水平同行评议成果，可支撑 4-5 分。简历未写全检测率、误报率或消融细节时，只在「实验验证」维度保守并记为面试待核验点，不得在方法、工程和成果维度重复扣分。

---

### 2.4 `multimodal` · Multimodal 多模态（60 分）

来源：`tracks/multimodal/spec.py:5-19`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `cross_modal_alignment` | 跨模态表征与对齐 | 10 | 看编码器、投影、Token 对齐、融合和训练目标。 |
| `perception_reasoning` | 感知、推理与生成深度 | 11 | 看视觉理解、跨模态推理、生成和任务复杂度。 |
| `multimodal_data` | 多模态数据构建与合成 | 8 | 看采集、标注、合成、负样本与质量控制。 |
| `multimodal_robustness` | 评测、鲁棒性与 OOD | 10 | 看扰动、长尾、幻觉、跨域和模态缺失。 |
| `spatiotemporal_grounding` | 空间、时序与 3D Grounding | 8 | 看视频时序、空间关系、3D 几何和具身 Grounding。 |
| `multimodal_system` | 模型与系统集成 | 7 | 看训练、推理、部署、数据流水线和效率。 |
| `multimodal_originality` | 跨模态原创性 | 6 | 看新的对齐、推理、数据或任务范式。 |
| | **合计** | **60** | |

- **证据重点**：跨模态表征、对齐、感知推理、数据构建、鲁棒性、时空与 3D Grounding 证据。
- **高分规则**：必须解释模态如何表示和融合、数据如何构建以及跨域后是否有效，调用视觉 API 不能高分。

---

### 2.5 `systems` · Systems 大模型系统（60 分）

来源：`tracks/systems/spec.py:5-19`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `performance` | 训练与推理性能优化 | 12 | 看吞吐、延迟、显存、成本、利用率和扩展效率。 |
| `system_architecture` | 系统架构深度 | 10 | 看并行、调度、缓存、通信、Serving 和容错。 |
| `performance_baseline` | 性能指标与公平基线 | 10 | 看硬件、模型、Batch、数据和测试条件可比性。 |
| `hardware_software` | 软硬件协同设计 | 8 | 看 GPU、算子、内存、通信和模型结构协同。 |
| `system_reliability` | 可靠性与可观测性 | 8 | 看稳定性、监控、调试、降级和故障恢复。 |
| `production_delivery` | 可复现性与生产交付 | 7 | 看代码、配置、环境、部署和真实采用。 |
| `systems_transfer` | 可迁移的系统洞见 | 5 | 看方法能否迁移到其他模型、硬件和负载。 |
| | **合计** | **60** | |

- **证据重点**：训练推理性能、系统架构、基线条件、软硬件协同、可靠性、可观测性和生产交付证据。
- **高分规则**：必须说明瓶颈、测试条件、公平基线和稳定收益，不同硬件或模型上的指标不能直接比较。

---

### 2.6 `ai4science` · AI4Science（60 分）

来源：`tracks/ai4science/spec.py:5-19`

| key | 中文 label | 满分 | 证据规则 |
|---|---|---|---|
| `scientific_problem` | 科学问题定义 | 11 | 看问题是否真实、有价值且可验证。 |
| `domain_validity` | 领域规律与约束正确性 | 10 | 看是否符合生物、化学、物理等领域规律。 |
| `scientific_data` | 科学数据与 Benchmark 可信度 | 8 | 看数据来源、标签、泄漏、偏差和划分。 |
| `scientific_method` | 模型与方法创新 | 8 | 看创新来自科学建模、算法机制还是工程组合。 |
| `experiment_loop` | 计算与实验验证闭环 | 10 | 看模拟、湿实验、专家和外部数据验证。 |
| `interdisciplinary_depth` | 跨学科理解与协作深度 | 7 | 看 AI 与领域知识是否真正融合。 |
| `scientific_impact` | 科学影响与可复现性 | 6 | 看新发现、实验成本、研究效率和复现。 |
| | **合计** | **60** | |

- **证据重点**：科学问题、领域规律、科学数据、方法创新、计算或实验验证闭环与科学影响证据。
- **高分规则**：必须证明科学问题成立、领域约束正确且预测经过科学验证，换领域数据刷榜不能高分。

---

## 3. 简历视觉表达质量（已移除）

> 该分项随多模态视觉管线一并删除：`document_quality` 节点已从评估图中移除，3 分上限并入通用潜力（37 → 40）。
> PDF 导入改为 `core/resume_ingestion.py` 的文本层提取，扫描页用本地 RapidOCR 兜底，不再产生任何版面/外观评分。
> `DocumentQualityAssessment` 模型仅为数据库与前端字段兼容保留，`document_score` 恒为 0。

---

## 4. 0-5 分语义尺子（所有维度通用）

来源：`tracks/shared/engine.py:12-37` 的 `TRACK_SCORER_PROMPT` 与 `common_potential/nodes.py:11-25` 的 `COMMON_SCORER_PROMPT`（语义一致）。

| 分值 | 含义 |
|---|---|
| 0 | 没有证据。 |
| 1 | 只有关键词、方向或论文标题。 |
| 2 | 参与过相关工作，但贡献、方法或验证仅有部分信息。 |
| 3 | 有具体方法或本人动作，并有项目、系统或研究成果支撑。 |
| 4 | 有原创方法/问题定义和较完整的研究或工程闭环，多条独立强证据可交叉支撑。 |
| 4.5 | 多项独立高质量成果与项目 ownership 交叉验证，已明显超过单项工作的完整闭环。 |
| 5 | 形成可迁移方法论，并有强验证、清晰 ownership 和学术或产业影响。 |

**加权公式**（`engine.py:124`）：

```python
weighted_score = round(score / 5 * max_points, 2)
```

例如某维度 `max_points=14`、`score=3.5` → `3.5/5×14 = 9.8`。

---

## 5. 评分原则（LLM Prompt 明确约束）

来源：`tracks/shared/engine.py:26-31`，所有 Track 共用。

1. 评价候选人**已被证据支撑的能力**，不是评价简历是否写成完整论文。
2. 正式发表的高水平同行评议成果是有效外部验证；不得与仅有论文标题的拟投成果等同。
3. 项目负责人 + 具体技术方法 + 可核验成果可构成高分组合证据，不强求它们出现在同一条 evidence 中。
4. 同一个"缺少量化指标/贡献细节"**不得在多个维度重复扣分**；放在最相关维度的 `risk_notes` 中。
5. 实习/工作经历中的具体方法、系统、指标和产物与项目证据同等有效；但**机构档位、机构类型、岗位名或时长本身不得加分**。

**硬性锚点**（prompt 与代码兜底双保险）：

- 引用证据中没有任何量化指标、可运行产物、验收结果或正式发表成果时，该维度得分不得超过 2.5。
- 4 分以上需要指标、具体工具或 ownership 中至少两项的组合证据；只有方向或参与描述时封顶 3。

---

## 6. Track 共用校准规则

来源：`tracks/shared/engine.py:133-176` 的 `_calibrate_scores` / `_supports_high_score`。

1. **无证据封顶 1 分**：维度引用的 evidence 全部不可追溯 → 压到 1。
2. **验证锚点封顶 2.5 分**：引用证据缺少量化指标、具体工具、验收/上线或正式发表成果（`_has_verification` 为假）→ 封顶 2.5。
3. **高分支撑校验**：`score >= 4` 且 `_supports_high_score(refs)` 为假 → 封顶 3.5。
4. **`_supports_high_score` 判定**满足任一即视为有高分支撑：
   - 强证据（`strength >= 4`）中存在一条，其 `[has_metric, has_specific_tool, has_ownership]` 三选二为真；
   - 或强证据覆盖 ≥ 2 个不同 `source`（如既有论文又有项目）。
5. **Portfolio 保底钩子**：`run_track_chain` 接受可选的 `portfolio_calibrator`，允许各 Track 注入自己的组合证据下限规则。

---

## 7. 数据流（评估如何贯穿系统）

```
简历输入（PDF 走文本层提取，扫描页本地 RapidOCR 兜底）
  │
  ▼
normalizer            背景细节折叠为低权重档位（学校/学业）
evidence_extractor    抽证据并归类到通用维度 / track_specific / background_signal
  │
  ▼
track_router + route_auditor    分配 1-3 个 Track 及权重（第二、三 Track 需 ≥2 条独立证据）
  │
  ├──────────────┬──────────────┬──────────────┐
  ▼              ▼              ▼              ▼
common_scorer  base_track    agent_track   ... 其余 Track
common_critic  (60 分)       (60 分)        (60 分)
  │              │              │              │
  └──────────────┴──────┬───────┴──────────────┘
                        ▼  fan-in (graph.py)
            portfolio_aggregator
              track_total = Σ weight × calibrated_score   # ≤ 60
              common_score ≤ 40
              overall = clip(common + track, 0, 100)
                        ▼
                    global_critic     全局复核（路由/证据/范围）
                        ▼
                    formatter         组装 CandidateEvaluation、tier / level
```

---

## 8. 数据结构参考

### 8.1 维度评分 `DimensionScore`

来源：`core/models.py`。每条维度的最终输出形态：

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | str | 维度标识，如 `problem_definition` |
| `label` | str | 中文显示名 |
| `score` | float | 0-5 的原始/校准后分值 |
| `max_points` | float | 该维度满分（如通用 8、Track 14） |
| `weighted_score` | float | `score / 5 × max_points`，即贡献到总分的分值 |
| `rationale` | str | LLM 给出的理由，必须引用 evidence id |
| `evidence_ids` | list[str] | 引用的证据 id 列表 |
| `risk_notes` | list[str] | 校准/风险提示 |

### 8.2 Track 评估 `TrackEvaluation`

| 字段 | 类型 | 说明 |
|---|---|---|
| `track` | TrackKey | Track 标识 |
| `label` | str | 中文显示名 |
| `weight` | float | 该 Track 在聚合中的权重 `[0,1]` |
| `confidence` | float | 路由置信度 |
| `raw_score` | float | 校准前分项和 |
| `calibrated_score` | float | 校准后分项和（≤60），进入聚合 |
| `dimension_scores` | list[DimensionScore] | 各维度明细 |
| `evidence_ids` | list[str] | Track 用到的全部证据 id |
| `risk_notes` | list[str] | Track 级风险提示 |
| `critic_flags` | list[str] | 校准器产生的封顶/风险标记 |

### 8.3 Portfolio 聚合结果（dict，非数据类）

来源：`aggregation/nodes.py:32-43`，写入 `state["portfolio_assessment"]`。

| 键 | 类型 | 说明 |
|---|---|---|
| `overall_score` | int | 0-100 整数总分 |
| `raw_total` | float | 未取整的小数总分 |
| `common_score` | float | 通用潜力分（≤40） |
| `track_score` | float | 多 Track 加权后的专业分（≤60） |
| `document_score` | float | 已废弃，恒为 0（原简历表达质量分） |
| `track_contributions` | list[dict] | 每 Track 的 `track / weight / specialist_score / contribution / available` |
| `level` | str | S / A / B / C |
| `tier` | str | 强烈建议沟通 / 建议沟通 / 暂缓 / 需补充信息 |

---

## 9. 维度权重速查总表

| Track | 维度数 | 满分 | 单维度最大 | 单维度最小 |
|---|---|---|---|---|
| 通用潜力 | 6 | 40 | 9 (`research_rigor` / `evidence_credibility`) | 3 (`learning_transfer` / `growth_trajectory`) |
| base | 6 | 60 | 14 (`model_architecture`) | 6 (`generalization`) |
| agent | 6 | 60 | 14 (`agent_method`) | 8 (`task_environment` / `agent_system`) |
| safety | 6 | 60 | 14 (`method_innovation`) | 6 (`ai_safety_transfer`) |
| multimodal | 7 | 60 | 11 (`perception_reasoning`) | 6 (`multimodal_originality`) |
| systems | 7 | 60 | 12 (`performance`) | 5 (`systems_transfer`) |
| ai4science | 7 | 60 | 11 (`scientific_problem`) | 6 (`scientific_impact`) |

---

## 10. 修改注意事项（给未来改 Rubric 的人）

1. **40 / 60 的上限由两处独立约束共同保证**，任一处变动都要同步：
   - `aggregation/nodes.py` 的 `min(40.0, …)`；
   - `core/models.py` 中 `TrackEvaluation.calibrated_score` 的 `le=60`。
   否则总分不再等于 100。
2. **Tier / Level 阈值有两处副本**：`aggregation/nodes.py` 和 `formatter.py`，必须同步修改。
3. **维度定义本身不在数据库**，`DimensionScoreORM`（`core/db/orm.py`）只按 `scope` 字段（`"common"` 或 Track key）存打分结果。
4. **Legacy v1 Rubric 已停用**（`core/rubric.py`，含 7 项核心潜力 + 5 项履历辅助），仅在回归测试中保留，多 Track 图（`core/graph.py`）不 import `scorer.py`，**不要混淆**。
5. **多模态视觉管线已移除**：PDF 导入走 `core/resume_ingestion.py` 的文本层提取 + RapidOCR 兜底；`DocumentQualityAssessment` 仅为数据库兼容保留，`document_score` 恒为 0。
