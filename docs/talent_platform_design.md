# AGI 人才情报平台 · 后端功能与 Agent 节点设计

> 状态：设计稿 v1（未实现）。
> 定位：智谱书院内部工具，服务高校博士生联培的人员筛选（学生 / 社会人员）与受邀嘉宾核查。
> 前身：`agi_talent_radar` 简历初筛系统（OCR 解析、多 Track 评分、校准机制全部复用）。

## 1. 定位与边界

**一句话**：用「简历证据 + 外部公开事实 + 舆情风险」三类可追溯证据，为书院的人员筛选与嘉宾邀请提供「推荐 / 不推荐 + 匹配方向 + 人才画像」的决策建议。

边界（与 HRBP / 法务确认后冻结）：

1. 决策支持，不做最终决策；舆情红线必须人工确认后才生效。
2. 只处理公开职业信息：简历、论文、代码、公开报道；不碰私人社交账号。
3. 每条结论必须带可追溯来源（evidence id / URL），不给来源的判断不进报告。

## 2. 三类评估对象与两种评估模式

| 对象 | 输入 | 模式 |
|---|---|---|
| 联培学生（本/硕/博） | 简历 PDF | `full_eval` 完整评估 |
| 社会人员 | 简历 PDF | `full_eval` 完整评估 |
| 受邀嘉宾 | 姓名 + 机构 + 方向（无简历） | `guest_check` 轻量核查 |

两种模式共享外部证据链；`guest_check` 跳过简历评分，只跑身份消歧 + 舆情 + 学术/代码速查。

## 3. 核心数据模型

```
persons                人员主档（同一人多次评估归一档）
  id, name, org, direction, fingerprint(姓名+机构+方向哈希),
  person_type(student/social/guest), created_at

evaluations            评估历史（一个人可多条，含配置版本）
  id, person_id FK, mode(full_eval/guest_check), config_version,
  overall_score, level, tier, result_json, status, created_at

external_facts         外部证据缓存（TTL 过期重拉）
  id, person_id FK, source(openalex/github/zread/web/aminer),
  fact_type, payload_json, source_url, fetched_at, expires_at

reputation_reports     舆情风险报告
  id, person_id FK, evaluation_id FK, level(red/yellow/green),
  events_json(事件+来源+消歧置信度),
  review_status(pending/confirmed/dismissed), reviewer, reviewed_at

requirement_profiles   需求档案（HRBP 从研究组收集的能力/人才需求）
  id, research_group, title, direction_requirements_json,
  capability_weights_json, status(active/archived), created_at

match_results          匹配结果
  id, person_id FK, requirement_id FK, match_score,
  matched_points_json, gap_points_json, created_at

hr_outcomes            HR 回流标注（校准真值）
  id, person_id FK, stage(screen/interview/offer/enrolled/invited),
  outcome, notes, created_at
```

设计要点：

- `persons.fingerprint` 做同人归并：今年拒了明年再投、今年邀过明年再邀，历史自动带出。
- `evaluations.config_version` 记录评估时的 rubric/权重哈希，权重调整后新旧分数可比性一目了然。
- 所有外部事实进 `external_facts` 缓存表，TTL 到期才重拉，控制 API 成本与限流。

## 4. 后端功能模块

| 模块 | 职责 | 复用/新增 |
|---|---|---|
| `core/resume_ingestion.py` | PDF 文本层提取 + RapidOCR 兜底 | 已有 |
| `core/persons.py` | 人员主档 CRUD、fingerprint 归并 | 新增 |
| `core/connectors/` | 外部证据连接器：openalex / aminer / github / zread / web_search | 新增 |
| `core/tasks.py` | 异步任务队列（DB 状态机 + 线程池起步，量大便换 RQ） | 新增 |
| `agents/`（LangGraph） | 评估图，见第 5 节 | 扩展 |
| `web/workbench.py` | Flask API，见第 6 节 | 扩展 |
| `core/matching.py` | 需求档案 ↔ 候选人匹配计算 | 新增 |

连接器统一协议：

```python
class Connector(Protocol):
    source: str
    def search(self, identity: PersonIdentity) -> list[Fact]: ...
    # Fact = {fact_type, payload, source_url, confidence}
    # 统一要求：结果写 external_facts 缓存；失败降级为空集合并记录 warning
```

## 5. Agent 评估图（节点设计）

### 5.1 总图

```
intake_router          判断模式：full_eval / guest_check
      │
person_resolver        主档归并（fingerprint 命中则带出历史摘要）
      │
      ├──── full_eval ──────────────────────────────┐
      │  resume_chain（已有）                        │
      │  parser → normalizer → evidence_extractor    │
      │                                              │
      ├──── 并行外部证据链（两种模式都跑） ──────────┤
      │  academic_chain                              │
      │    claim_extractor → academic_lookup         │
      │    → claim_alignment                         │
      │  code_chain                                  │
      │    github_lookup → repo_reader(ZRead)        │
      │    → contribution_alignment                  │
      │  reputation_chain                            │
      │    identity_disambiguator → risk_searcher    │
      │    → event_classifier → risk_grader          │
      │                                              │
      ▼                                              ▼
track_router → common_scorer/critic → track scorers   （仅 full_eval，已有）
      │
match_scorer           需求档案 ↔ Track 分布 + 外部事实（有激活需求档案时）
      │
reputation_gate        舆情结论转决策闸门：红→不推荐，黄→人工复核标记
      │
decision_composer      汇总：推荐结论 + 匹配方向 + 人才画像 + 风险面板
      │
review_router          红/疑似命中 → human_review 待办；绿 → 直接终态
```

### 5.2 新节点详设

**intake_router**
- 输入有简历 → `full_eval`；只有姓名/机构/方向 → `guest_check`。
- guest_check 跳过 resume_chain 与全部评分节点，外部证据链跑完后直接进 decision_composer。

**person_resolver**
- fingerprint = normalize(姓名 + 机构 + 方向) 哈希；命中主档则把历史评估摘要、过往舆情结论注入 state，供 decision_composer 引用（"2025-07 初筛未通过"）。

**academic_chain**
- `claim_extractor`（LLM）：从简历/输入提取论文声称清单（标题、会议/期刊、年份、作者位次）。
- `academic_lookup`（连接器，无 LLM）：OpenAlex 优先，AMiner 补中文；按标题模糊匹配 + 作者消歧。
- `claim_alignment`（LLM）：逐条对齐 → `verified / mismatch / unverifiable`；输出差异点（如"声称一作实为三作""声称已发表实为在投"）、被引数、撤稿标记（Retraction Watch）。

**code_chain**
- `github_lookup`：从简历提取 GitHub ID / 仓库链接 → 官方 API 拉贡献事实（commit 归属、PR、star、活跃度）。
- `repo_reader`：对候选人自建仓库调 ZRead MCP（search_doc / get_repo_structure / read_file）生成项目深度解读。
- `contribution_alignment`（LLM）：对齐"声称贡献 vs 实际提交"，识别 fork 充原创、刷 commit 等。

**reputation_chain（核心新链）**
- `identity_disambiguator`（LLM）：构造消歧指纹（姓名 + 机构 + 方向 + 代表成果），后续每条检索命中都先过消歧判断：`confirmed / probable / rejected(同名)`。对不上的一律进"疑似"，不得用于降级。
- `risk_searcher`（连接器 + 模板）：web_search_prime 跑模板检索词——
  `{name} {org} 抄袭`、`{name} 学术不端`、`{name} 撤稿`、`{name} 争议/纠纷`、PubPeer/Retraction Watch 定向检索；web_reader 抓正文。
- `event_classifier`（LLM）：命中文本 → 事件分类（学术不端 / 抄袭争议 / 公开冲突 / 法律纠纷 / 其他负面 / 误报），提取时间、对方、当前状态（已澄清/进行中）。
- `risk_grader`（规则 + LLM）：红 = 消歧 confirmed 且学术不端/实锤抄袭；黄 = probable 命中或一般争议；绿 = 无命中或全部 rejected。输出必须带 URL 列表。

**match_scorer**
- 输入：激活态 requirement_profiles + 候选人 Track 分布 + 外部事实。
- 输出：match_score、匹配点、缺口点（如"需求：大模型安全实战经验；缺口：候选人仅有 NLP 应用经历"）。
- 需求档案 schema 等 HRBP 收集后冻结，先按「方向要求 + 能力权重」两字段设计。

**reputation_gate**
- 舆情不进分数加减，只做闸门：红 → 推荐结论强制"不推荐"；黄 → 结论挂"需人工复核"；绿 → 不干预。
- 理由：分数是能力评估，舆情是风险事件，两者量纲不同，混在一起两头都解释不清。

**review_router**
- 红/疑似 → 写 reputation_reports(review_status=pending)，报告页显示"待人工确认"，人工确认/驳回后才算终态。

### 5.3 复用节点的改造

| 现有节点 | 改造 |
|---|---|
| `normalizer` / `evidence_extractor` | 不变 |
| `track_router` / scorers | 不变；输出同时喂 match_scorer |
| `formatter` | 升级为 decision_composer：新增匹配方向、外部对齐结果、风险面板字段 |
| `aggregation` | overall_score 不再等于最终推荐，推荐结论由 decision_composer 综合分数+闸门得出 |

## 6. API 端点（Flask）

```
POST /api/persons                 录入（简历上传 或 姓名+机构+方向）
GET  /api/persons                 人才库列表（类型/状态/分数筛选）
GET  /api/persons/<id>            主档 + 全部评估历史 + 舆情状态
POST /api/evaluations             发起评估（async，返回 task_id）
GET  /api/tasks/<id>              任务状态/进度（SSE 沿用现有模式）
GET  /api/evaluations/<id>        评估报告详情
POST /api/reputation/<id>/review  舆情人工复核（confirm/dismiss + 备注）
GET  /api/requirements            需求档案列表
POST /api/requirements            HRBP 录入需求档案
GET  /api/persons/<id>/matches    候选人与各需求档案的匹配结果
POST /api/hr-outcomes             HR 回流标注（筛选/面试/入职结果）
```

## 7. 任务编排

- 起步：DB 任务表（queued/running/done/failed + 节点进度）+ ThreadPoolExecutor，复用现有 IMPORT_CONCURRENCY 模式。
- 外部连接器全部同步改异步任务，失败自动重试 2 次后降级为空集合并记 warning——某个数据源挂了不能拖死整个评估。
- 量级上来后再换 RQ/Celery + Redis，接口保持不变。

## 8. 前端映射（工作台 2.0，随模块迭代）

- 三模式入口：招聘筛选 / 嘉宾核查 / 人才库。
- 报告页四块：评分与 Track 分布（已有）+ 证据对齐视图（声称 ✓/✗ 外部事实）+ 舆情风险面板（红黄绿 + 来源链接 + 人工复核按钮）+ 匹配方向雷达。
- 活动视图：一批嘉宾的批量核查清单（风险等级排序，红色置顶）。

## 9. 分期

| 期 | 内容 | 依赖 |
|---|---|---|
| P1 | persons 主档 + reputation_chain + guest_check 模式 + 复核界面 | web_search/web_reader（Coding Plan） |
| P2 | academic_chain（OpenAlex 免费先行） | 无 |
| P3 | requirement_profiles + match_scorer | HRBP 需求文档 |
| P4 | code_chain（GitHub API + ZRead MCP） | Coding Plan |
| P5 | 前端 2.0 统一改版 | P1-P4 |

## 10. 合规清单（冻结前必须确认）

1. 评估告知：简历收集与公开信息核查需候选人/嘉宾知情同意（报名流程加告知条款）。
2. 舆情只收录公开报道与公开学术记录，不收录私人社交内容。
3. 负面信息展示必须带来源链接，系统措辞只做事实转述不做定性判断。
4. 数据保留期与删除权：候选人要求删除时可删主档及全部评估记录。
