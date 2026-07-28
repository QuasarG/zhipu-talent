# 人才研究平台实施计划

> 计划状态：可执行
>
> 编写日期：2026-07-28
>
> 需求依据：`CONTEXT.md`、`docs/backend_use_case_decisions.md`

## 1. 目标与边界

本计划把现有“多 Track 简历初筛工具”演进为一个内部人才研究平台。最终只保留两条独立 Agent 工作流：

1. **简历评估 Agent**：评价能力结构、计算分数、推荐 Track、提取并核验论文信息；不做录取判断，不按分数自动分组。
2. **人才知识 Agent**：接收自由自然语言问题，优先查询人才库，必要时调用 AMiner、OpenAlex 和智谱 Web Search，输出带来源、时间和核验状态的回答。

人才知识库是两条 Agent 共用的数据与展示底座，不是第三条评估 Agent。本期明确不做“按关键词批量发现未知人才”。

## 2. 当前基线与主要缺口

### 2.1 已有能力

- 简历 LangGraph 已具备标准化、证据提取、通用潜力评分、多 Track 路由与汇总，入口见 `agi_talent_radar/core/graph.py:36`。
- Track 权重已开始拆分到各 Track 的 `weights.py`，现有评分测试集中在 `tests/test_multi_track.py:278` 之后。
- OpenAlex、智谱 Web Search、AMiner 学者搜索连接器已经存在。
- MySQL/SQLAlchemy 数据层已保存历次评估和评分明细，见 `agi_talent_radar/core/db/orm.py:81`、`agi_talent_radar/core/db/repository.py:109`。
- 人物主档、外部事实、舆情报告和异步任务已有初步表结构，见 `agi_talent_radar/core/db/orm.py:278`。
- Flask 已提供简历导入、评估 SSE、人才列表和人物详情 API，入口见 `agi_talent_radar/web/workbench.py:35`。

### 2.2 必须先修正的结构问题

- 当前 `CandidateORM` 同时承担“刚导入的简历”和“已入人才库的人才”两种含义，见 `agi_talent_radar/core/db/orm.py:54`。这与领域定义冲突。
- 导入阶段会立即保存 Candidate，见 `agi_talent_radar/core/import_agent.py:121`；目标规则是完整评估成功后才进入人才库。
- 评估完成后仍按总分自动写入 `shortlisted / alternative / rejected`，见 `agi_talent_radar/web/workbench.py:122` 和 `agi_talent_radar/web/workbench.py:666`。
- 人物归并目前主要依赖姓名、机构、方向哈希，见 `agi_talent_radar/core/persons.py:17`，不足以支持稳定标识和 AI 模糊对齐。
- 论文状态仍由固定关键词 validator 归一化，见 `agi_talent_radar/agents/academic/models.py:8`；且外部核验只对部分阶段运行，见 `agi_talent_radar/agents/academic/nodes.py:163`。
- 人物调查还是固定参数同步服务，见 `agi_talent_radar/core/guest_profile_service.py:17`，尚未形成自由提示词 LangGraph Agent。
- AMiner 论文接口仍是空实现，见 `agi_talent_radar/core/connectors/aminer.py:94`。
- 没有 Qdrant、Embedding、混合检索、统一鉴权和服务器配置界面。

## 3. 目标模块边界

### 3.1 简历评估模块

对外只暴露高层接口：

```python
evaluate_resume(submission_id) -> EvaluationResult
retry_publication_verification(evaluation_id, paper_claim_ids=None) -> TaskResult
```

内部负责身份解析、评分、Track 推荐、论文自述提取、结果持久化和外部核验任务派发。调用方不直接编排单个评分节点。

### 3.2 人才知识模块

对外只暴露：

```python
ask_talent_knowledge(conversation_id, prompt) -> stream[AgentEvent]
```

内部负责意图识别、人物消歧、库内混合检索、外部工具选择、证据归一、待核验事实落库和带引用回答。

### 3.3 外部服务端口

AMiner、OpenAlex、智谱 Web Search、智谱 Embedding 和 Qdrant 均通过可注入端口访问。生产环境使用真实适配器，测试使用确定性 Fake，避免业务测试依赖外网。

### 3.4 数据真源

- MySQL：唯一业务数据真源。
- Qdrant：可重建的派生语义索引，仅保存向量、检索 payload 和 MySQL ID。
- `.env`：服务器级外部服务配置，不向浏览器暴露原文 Key。

### 3.5 Track 推荐与研究组匹配边界

- `TrackRecommendation` 是简历评估的现有输出，依据能力证据给出宽泛方向、理由和置信度。
- `ResearchGroupMatching` 是未来独立模块，只有在 HR 提供版本化研究组要求后才启用。
- 未配置研究组要求时，API 返回 `matching_status=not_configured`，前端显示“研究组匹配尚未配置”，不得伪造匹配分。
- 未来模块预留高层接口 `match_candidate(candidate_id, requirement_version)`，读取评估与证据，输出多研究组匹配结果，但不回写原始评分和 Track 推荐。
- 研究组要求与匹配结果分别保存，至少包含必需条件、偏好条件、研究主题、排除条件、证据引用、缺失项、不确定项和需求版本。

## 4. 实施阶段

## 阶段 0：冻结回归基线与 API 契约

**目的**：先把当前行为写成测试，再逐步替换旧语义，防止脏工作区中的既有改动被误伤。

**当前基线**：2026-07-28 使用仓库 `.venv` 运行全量测试为 `93 passed`。默认 `usuall` conda 环境当前缺少 `flask`、`json_repair` 等项目依赖，正式开工前应先按 `requirements.txt` 补齐，使两个环境至少有一个被明确指定为唯一开发测试环境。

**工作项**：

1. 运行现有全量测试并记录基线；失败项先分类为既有失败或本次改造引入。
2. 为新领域术语建立 API schema：Person、Candidate、ResumeSubmission、Evaluation、CandidateSource、EngagementStatus、PublicationClaim、PublicationVerification、ExternalFact。
3. 在 `tests/` 增加契约测试，先明确以下目标行为：
   - 导入成功但未评估的简历不出现在人才库。
   - 评估分数不会改变人才跟进状态。
   - 人物调查不会自动创建 Candidate。
   - 外部论文服务失败不导致核心评估失败。
4. 保留旧 API 的兼容窗口，但在测试中标记待删除的自动分组行为。

**验收**：

- 全量测试基线可重复。
- 新领域 schema 可序列化、反序列化，并覆盖非法状态输入。
- 四条核心边界都有失败优先的契约测试。

## 阶段 1：重建人物、简历提交与人才档案数据模型

**目的**：消除 `Candidate` 身份混用，建立后续所有功能依赖的数据底座。

**数据库改造**：

1. 新增 `resume_submissions`：保存每次导入的原文件信息、解析文本、结构化简历、解析状态和创建时间。
2. 新增 `resume_versions` 或以 submission 版本号实现同一人物的历次简历保存，原文永不被新版本覆盖。
3. 调整 `candidates`：只表示已入人才库的人才档案，增加唯一 `person_id`、当前 HR 跟进状态和当前展示版本引用。
4. 新增 `candidate_sources`：同一 Candidate 可同时拥有 `resume_evaluation` 和 `person_investigation`，并记录来源时间和依据。
5. 新增 `engagement_status_history`：保存每次人工状态变更、操作者、备注和时间。
6. 调整 `evaluations`：关联 `resume_submission_id`、`resume_version_id`、`person_id`、`candidate_id`、配置版本；旧评估保留。
7. 新增身份标识与审计表：稳定标识、模糊匹配建议、人工合并/解除记录。
8. 编写增量迁移：
   - 现有 Candidate 的简历字段迁移为 ResumeSubmission/ResumeVersion。
   - 有成功 Evaluation 的记录建立或关联 Person 和 Candidate。
   - 无成功 Evaluation 的记录只保留为待评估 Submission。
   - 旧 `group` 值只作为迁移审计数据保留，不再驱动业务。

**代码改造**：

- 将 `save_candidate` 拆为 `save_resume_submission` 和 `admit_candidate_after_evaluation`。
- 新建 `talent_service`，集中处理“评估成功入库”“人物调查后人工加入”“来源追加”“HR 状态变更”。
- repository 只提供数据操作；业务事务由 service 管理，避免路由层拼装多步事务。

**验收**：

- 同一人物可关联多份简历、多个评估，但至多一个 Candidate。
- 未评估和评估失败的 Submission 不进入人才库查询结果。
- 双来源人才在两个来源筛选中均可见，总人数按 Candidate ID 去重。
- 旧数据迁移前后评估历史数量、原文和评分明细不丢失。
- HR 状态只能通过显式服务调用修改，并产生不可变历史记录。

## 阶段 2：实现入库身份归并节点

**目的**：在评分前确认人物身份，但不把历史结论带入本次评分。

**工作项**：

1. 新建 `identity_resolution` 深模块，输入当前简历身份证据，输出：
   - `matched_person_id`
   - `decision`：new / matched / needs_review / conflict
   - `confidence`
   - `supporting_evidence`
   - `conflicts`
2. 第一层确定性匹配：邮箱、ORCID、AMiner ID 等稳定唯一标识。
3. 第二层 AI 模糊匹配：姓名变体、学校/机构、时间线、方向和论文。
4. 首版采用保守策略：稳定标识精确一致可自动归并；AI 模糊结果先生成建议，不自动合并。积累离线样本并验证误合并率后，再单独放开可靠姓名+机构规则。
5. 将节点放到评分图最前部；后续评分状态只接收 Person ID 和本次身份判断，不读取历史分数、HR 状态或旧结论。

**验收**：

- 稳定标识相同的多份简历归入同一 Person。
- 只有姓名相同不会自动归并。
- 身份冲突会阻止自动归并并产生审核项。
- 评分节点的输入快照不含历史评分、舆情级别或 HR 跟进状态。

## 阶段 3：重构简历论文提取与核验

**目的**：把“候选人自述”和“外部核验事实”彻底分开，并让核验失败可独立重试。

**模型改造**：

1. `PublicationClaim` 保存标题、venue、年份、自述状态、作者角色、原文证据、AI 理由和置信度。
2. 自述状态使用受控枚举：草稿、已投稿、在审、已接收、已发表、未说明；Pydantic 只校验枚举，不再用关键词猜状态。
3. `PublicationVerification` 独立保存：匹配论文、外部来源、发表状态核验、作者顺序核验、同人置信度、核验状态、冲突项、失败原因和核验时间。
4. 核验状态统一为：已核验、待核查、存在冲突；人工确认状态另存，不能混为一列。

**流程改造**：

1. 将现有同步 `academic_check` 拆成两个步骤：
   - LangGraph 内部 AI 语义提取论文自述；所有年级均执行。
   - 核心评估保存成功后，派发 OpenAlex 外部核验任务。
2. 外部找到可靠匹配且作者身份明确时，核验发表状态和作者顺序。
3. 无明确自述但有 venue/会议时尝试外部查询；命中则可标记已发表，未命中则待核查。
4. 草稿、已投稿、在审等无公开记录时保留自述，外部核验为待核查。
5. 冲突在人工确认前不扣分；确认后只降低对应证据可信度，不修改项目能力证据。
6. 通过 Task 表支持按 Evaluation 或单篇论文重试，不重跑整份简历评分。

**验收**：

- AI 能理解自由表述的论文状态，测试不依赖固定关键词映射。
- 每条论文同时可展示自述状态和外部核验状态。
- OpenAlex 超时、无结果或限流时，评估仍成功，论文为待核查且任务可重试。
- 作者顺序只有在论文和人物都可靠对齐后才判一致或冲突。
- 待核查和未人工确认冲突不会改变总分。

## 阶段 4：收口简历评估 Agent 与入库事务

**目的**：使评估输出只表达能力和方向，并保证成功入库的事务一致性。

**工作项**：

1. 调整 `agi_talent_radar/core/graph.py:36`：身份归并 -> 标准化 -> 论文自述提取 -> 证据提取 -> 通用潜力 -> Track 路由/评分 -> 汇总 -> 格式化。
2. 保持各 Track 的纯数据权重配置，不把通过/未通过历史用于后验调权。
3. 删除分数到人才分组的映射：移除 `VALID_GROUPS`、`_group_for_score` 和评估完成后的自动 move。
4. 评估成功的单一事务：保存 Evaluation -> 关联/创建 Person -> 关联/创建 Candidate -> 追加 `resume_evaluation` 来源 -> 派发论文核验和向量同步任务。
5. 评估失败只更新 Evaluation/Submission 状态，不创建 Candidate。
6. 输出保留总分、分维度评分、证据链、推荐 Track 和培养建议，但不输出自动录取等级。
7. 输出单独提供研究组匹配状态；首版固定为 `not_configured`，直到 HR 提供具体且版本化的研究组要求。

**验收**：

- 任意分数都不会自动改变 HR 状态或创建筛选分组。
- Track 推荐始终与研究组匹配字段分开，未配置研究组要求时不会生成匹配分。
- 同一评估请求重复提交具备幂等保护，不产生重复 CandidateSource。
- 核心评估保存失败时不会出现半入库 Candidate。
- 评分配置版本、简历版本和评估时间均可追溯。

## 阶段 5：实现人才知识 Agent

**目的**：用一个自由提示词入口覆盖库内问答和已知人物调查。

**LangGraph 节点**：

1. `intent_parser`：区分库内查询、比较、统计、已知人物调查和不支持的人才发现请求。
2. `identity_resolver`：从自由文本提取姓名、机构、方向、调查范围和附加关键词；身份不足时返回澄清事件。
3. `local_retriever`：优先查询 MySQL 和后续 Qdrant。
4. `tool_planner`：判断库内信息是否足够，以及需要 AMiner、OpenAlex、Web Search 的哪几条链路。
5. `external_investigator`：三条外部链独立执行，部分失败不阻塞其他结果。
6. `evidence_normalizer`：统一来源、时间、人物身份置信度、核验状态和去重键。
7. `fact_persister`：只追加待核验外部事实，不覆盖已确认事实。
8. `answer_composer`：输出结论、警告和逐条引用。

**连接器工作**：

- 实现 `search_aminer_papers`，返回论文标题、年份、venue、作者、引用量和 AMiner 标识；按引用量识别关键高引论文。
- AMiner 用于研究范围和关键论文；OpenAlex 用于公开论文、作者顺序和撤稿交叉核验；Web Search 用于舆情和最新公开信息。
- 所有连接器返回统一 Fact，不在 Agent 节点中直接解析供应商原始响应。

**权限边界**：

- Agent 可以读人才库、调用外部工具、追加待核验事实。
- Agent 不得修改 HR 状态、确认事实、合并人物、加入/删除 Candidate 或修改评分。

**验收**：

- “只看论文”和“只查舆情”只调用需要的工具。
- 默认已知人物调查调用 AMiner、OpenAlex、Web Search；单个服务失败返回部分完成。
- 只给研究关键词且无法识别具体人物时，不执行批量人才发现。
- 库内信息足够时不调用外网。
- 新外部信息写成 pending 版本，冲突事实并存，不覆盖 confirmed 版本。

## 阶段 6：建立外部事实版本与审核模型

**目的**：让联网数据可追溯、可更新、可审核，而不是把缓存当真相。

**工作项**：

1. 扩展 `external_facts`：增加 identity_key、dedupe_key、verification_status、valid_from、supersedes_id、superseded_at、query_context、raw_payload_hash。
2. 区分 confirmed / pending / conflict / disproved / superseded 状态。
3. 新查询结果按稳定去重键归并；内容变化时创建新版本并指向旧版本。
4. 与已确认事实冲突时生成审核项，不覆盖旧值。
5. 建立人工确认、驳回和关系解除的审计记录。

**验收**：

- 重复拉取完全相同事实不会产生无限重复记录。
- 变化事实会保留旧版本和替代链。
- confirmed 事实不会被 Agent 自动降级或覆盖。
- 人才详情能区分当前事实、历史事实和待审核冲突。

## 阶段 7：接入 Embedding 与 Qdrant RAG

**目的**：为人才知识问答提供可重建的语义检索，同时保持 MySQL 为真源。

**工作项**：

1. 新增智谱 Embedding 适配器：固定 `embedding-3`、1024 维、单条不超过 3072 tokens、单批不超过 64 条。
2. 新增 Qdrant 适配器和 collection 版本规范；payload 至少包含 person_id、candidate_id、record_type、record_id、fact_status、source、fetched_at、index_version。
3. 切片对象首版覆盖：简历版本、评估摘要、评分证据、论文自述/核验、外部事实、HR 备注。每个 chunk 必须能回链到 MySQL 原文。
4. 新增 MySQL outbox/vector sync task：业务事务先提交 MySQL，再异步 embedding/upsert/delete Qdrant；失败重试。
5. 实现混合检索：
   - 精确筛选、计数、状态、排序走 MySQL。
   - 开放语义问题走 Qdrant。
   - 复合问题先用 MySQL 得到 Candidate ID 集合，再带过滤条件查 Qdrant。
6. 回答层保留 confirmed/pending/conflict 状态；支持“只看已确认信息”。
7. 提供全量重建命令，从 MySQL 重新切片并调用 embedding-3，不依赖旧 Qdrant 数据。

**部署选择**：

- Qdrant 作为独立本机服务运行，持久化目录不放在应用仓库。
- 应用通过 `QDRANT_URL`、`QDRANT_API_KEY`、`QDRANT_COLLECTION` 连接。
- 首版备份以 Qdrant snapshot 加 MySQL 业务备份为主；即使 Qdrant 丢失，也必须能从 MySQL 重建。

**验收**：

- Embedding 批处理严格遵守 64 条和 token 上限。
- Qdrant 删除后可通过重建命令恢复相同记录规模和可用检索结果。
- 向量同步失败不回滚已成功的业务写入，并会生成可重试任务。
- 回答中的每个事实引用都能定位到 MySQL 记录、来源、时间和核验状态。

## 阶段 8：拆分 Web API、增加鉴权与全局配置

**目的**：稳定后端契约，再让前端接入；同时保护内部数据和密钥。

**API 分组**：

- `/api/resume-submissions`：导入、解析状态、评估、评估历史、论文核验重试。
- `/api/candidates`：人才列表、来源筛选、详情、比较、HR 状态人工更新。
- `/api/persons`：人物主档、调查历史、人工加入人才库、身份合并审核。
- `/api/knowledge`：会话、消息流、引用和任务状态。
- `/api/facts`：待核验事实、冲突审核和历史版本。
- `/api/config`：脱敏配置读取、校验和更新。
- `/api/auth`：登录、登出、会话状态。

**鉴权**：

1. 从环境变量读取单一内部密码和 Flask session secret。
2. 登录成功写入 HttpOnly、SameSite、生产环境 Secure 的签名 Cookie。
3. 除登录和健康检查外，页面、JSON API 和 SSE 全部经过统一鉴权 middleware。
4. API 未登录返回 401；页面未登录跳转登录页。

**配置**：

1. 建立统一 Settings Provider，业务代码不再分散直接读取 `os.getenv`。
2. GET 只返回非敏感字段和 Key 的已配置/脱敏状态。
3. 更新时先校验字段和可选连接测试，再写临时文件并使用原子替换更新 `.env`。
4. 原子替换后刷新进程内 Settings；失败时保留旧文件和旧运行时配置。
5. 日志、API 错误和审计记录不得输出完整 Key。

**验收**：

- 未登录无法访问页面、API 或 SSE。
- 浏览器响应、HTML、JS 和日志中不存在完整 Key。
- 配置校验失败时 `.env` 内容和运行时配置均不改变。
- 已建立的 SSE 在会话过期或退出后不能新建受保护任务。

## 阶段 9：前端重构为 Material Design 3 工作台

**前置条件**：阶段 1-8 的 API schema 稳定后再开始，避免前端围绕旧 Candidate/group 语义返工。

**页面**：

1. 登录页。
2. 简历评估工作台：待评估 Submission、评估进度、能力评分、Track 推荐、论文自述与核验状态、历史版本对比。
3. 人才库：全部人才、简历评估来源、人物调查来源；双来源显示双标签但唯一计数。
4. 人才详情：结构化档案、历次评估、论文、外部事实、舆情、HR 状态和审计历史。
5. 人才知识对话：自由输入、工具执行状态、部分失败警告、引用抽屉和核验状态标识。
6. 待核验中心：论文冲突、外部事实冲突、身份合并建议。
7. 全局配置页：模型、Base URL、Key 状态和连接测试。

**设计约束**：

- Material Design 3 作为设计方向，先定义颜色、排版、间距、状态色和组件令牌。
- 评分、推荐 Track、论文核验、HR 跟进状态使用不同视觉语义，避免再次被理解为同一分类体系。
- 不提供独立“人物舆情调查”表单；功能由人才知识对话覆盖。

**验收**：

- 桌面和移动视口下无文本溢出和控件重叠。
- 双来源人才在两个来源视图可见，但全部人才统计不重复。
- 待核查、冲突、已确认在详情和对话引用中保持一致。
- 对话界面能展示 Agent 节点进度、实际调用工具、引用和部分失败状态。

## 阶段 10：人才关系图谱

**目的**：在结构化人才库稳定后增加可解释的关系发现视图。

**工作项**：

1. 建模 Person、School、Organization、Direction 实体节点。
2. 人才通过实体节点形成学校、机构和方向聚类，不建立同学校人才两两全连接。
3. 只有共同论文、共同项目、真实合作或人工确认关系建立 Person-Person 直接边。
4. confirmed 关系实线；AI 推断 pending 关系虚线；无来源关系不入图；disproved 关系保留历史但当前隐藏。
5. 人才节点颜色表示学校：当前学校优先，否则最高学历学校；稳定映射并提供图例和高亮。
6. 人才节点形状表示主要推荐方向；次要方向的表达在本阶段开始前再做一次专门设计确认。

**验收**：

- 每条可见关系都能打开来源证据。
- 学校/方向高密度数据不会退化成人才两两连线的毛线团。
- 同一人才的图节点、列表项和详情页指向同一 Candidate/Person ID。
- pending、confirmed、disproved 的显示规则与事实审核状态一致。

## 阶段 11：部署、可观测性与上线验收

**工作项**：

1. 更新 `requirements.txt`，加入 Qdrant 客户端和必要的配置/HTTP 依赖，锁定版本。
2. 修正 `deploy/talent-radar.service:12` 仍使用 SQLite 的旧配置，生产统一使用 MySQL。
3. 部署 Qdrant 独立服务、持久化目录、健康检查和 snapshot 计划。
4. 增加健康检查：MySQL、Qdrant、LLM、Embedding、AMiner、OpenAlex、Web Search 分开报告，不把可选外部服务失败伪装成应用宕机。
5. 为 Agent、外部调用、事实落库、向量同步记录 task_id、conversation_id、evaluation_id 和耗时，不记录敏感 Key。
6. 编写运维命令：数据库迁移、Qdrant 全量重建、失败任务重试、配置连通性检查。
7. 使用一组匿名化真实简历和已知人物问题做端到端验收。

**上线门槛**：

- 单元、数据库、API、Agent 合约测试全部通过。
- 外部服务故障注入测试证明可部分降级和独立重试。
- 鉴权覆盖检查证明除 login/health 外无匿名入口。
- 数据迁移在备份副本上演练成功，记录数和关键字段校验通过。
- Qdrant 空库重建成功，知识问答仍能恢复。
- 真实简历评估不产生自动录取/分组结论。

## 5. 推荐执行顺序与里程碑

| 里程碑 | 阶段 | 可交付结果 |
|---|---|---|
| M1 领域底座 | 0-2 | 简历提交、人物、人才三层分离；身份归并可审计 |
| M2 简历评估闭环 | 3-4 | 所有年级论文语义提取；评分与入库/HR 状态解耦 |
| M3 人才知识后端 | 5-7 | 自由提示词 Agent、AMiner/OpenAlex/Web Search、RAG/Qdrant |
| M4 平台化 | 8 | 鉴权、配置、稳定 API 和 SSE 契约 |
| M5 用户界面 | 9 | M3 人才库、对话、审核和配置界面 |
| M6 图谱与上线 | 10-11 | 关系图谱、运维、迁移和端到端验收 |

每个里程碑单独提交并保留可运行状态。不要同时重写数据库、Agent 和前端，否则出现回归时无法定位责任模块。

## 6. 测试策略

### 单元测试

- 论文 AI 输出结构校验、状态机和分数中立规则。
- 身份解析的稳定标识、冲突和模糊建议。
- 外部事实去重、版本替代和审核状态。
- 工具规划、只读权限和回答引用组装。
- Embedding 切片、批大小、token 上限和 Qdrant payload。

### 集成测试

- SQLite 仅用于快速 repository 测试；关键迁移和事务在 MySQL 测试实例验证。
- Qdrant 使用临时测试 collection，验证 upsert、过滤、删除和全量重建。
- 外部服务使用 Fake/录制响应验证成功、超时、限流、空结果和部分失败。
- Flask 测试客户端覆盖 Cookie 鉴权、API 401、SSE 和配置脱敏。

### 端到端测试

1. 导入简历 -> 评估成功 -> Person/Candidate 入库 -> 论文核验异步完成 -> RAG 可检索。
2. 导入简历 -> 核心评估成功但 OpenAlex 失败 -> Candidate 入库 -> 论文待核查 -> 单独重试成功。
3. 调查已知人物 -> 外部事实 pending -> 不自动入人才库 -> HR 手动加入 -> 来源视图更新。
4. 同一人物后续提交简历 -> 身份建议/归并 -> 单一 Candidate 同时拥有双来源。
5. 知识问答 -> 库内优先 -> 信息不足时联网 -> pending 事实落库 -> 回答带来源和状态。

## 7. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 旧 Candidate 数据迁移丢失 | 迁移前备份；先复制到新表再切读路径；记录数和哈希校验；不立即删旧列 |
| AI 身份误合并 | 首版只有稳定标识自动合并；模糊结果走审核；保留解除和审计 |
| AI 论文状态幻觉 | 强制原文证据、理由和置信度；自述与外部核验分表；无证据回退待核查 |
| 外部服务拖慢主流程 | 连接器超时；链路独立；论文外部核验和向量同步异步化 |
| Qdrant 与 MySQL 不一致 | MySQL-first + outbox 重试 + 可重复全量重建 |
| 配置界面泄露 Key | 只返回掩码状态；日志脱敏；原子更新；后端独占 `.env` 读写 |
| 单体 Flask 路由继续膨胀 | 按 auth/resume/candidate/knowledge/config Blueprint 拆分，业务事务下沉 service |
| 前端提前绑定旧模型 | 阶段 8 API 契约稳定后才做阶段 9 |

## 8. 明确不在本计划首轮实现的内容

- 按研究关键词批量发现未知人才。
- 代码仓库核验。
- 用历史通过/不通过样本后验调权。
- 自动录取、自动淘汰或按评分切换 HR 状态。
- 多角色、字段级或租户级权限系统。
- 本地 Embedding 模型和多 Provider Embedding 抽象。
- 无来源的人际关系推断。

## 9. 开工点

第一批代码只做 **阶段 0-1**：建立新 schema、迁移和领域服务，并用测试证明“导入不等于入库、评估成功才入库、分数不改变 HR 状态”。在这批完成前，不开始人才知识 Agent 或前端重构。
