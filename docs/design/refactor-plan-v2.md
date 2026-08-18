# AGI Talent Radar 重构方案 v2.0（2026-08-16 终审版）

> 本文档是重构的唯一执行依据，取代 `docs/design/` 下所有旧设计稿（旧稿已归档 `docs/design/archive/`）。
> 场景（leader 拍板）：简历初筛——**系统只展示信息，不输出"是否建议面试"**。

## 0. 已拍板裁决清单（全部讨论的收敛点）

| # | 裁决 |
|---|---|
| R1 | 系统输出**两个分**：能力分（JD 无关、绝对尺）× 匹配分（JD 相关、纯计算）。两列展示，永不合成 |
| R2 | 不输出档位/建议/任何决策措辞；面试决策纯人工，**埋点记录**（interview_status / outcome） |
| R3 | 证据三分类：`title_fact`（赢过/做成：状元、CCF-A 一作、best paper）/ `action_fact` / `vague_claim`；三通道：锚定 / 常规 / 推断（×0.8 固定折扣） |
| R4 | 放大镜原则：细节只放大实质，不加分。详写 vs 简写分差压到 ~20% |
| R5 | 背景双轨：能力链**抹除**背景（不分级、不进证据链）；匹配链**保留原 title**（学校/公司是合法亲和特征，不涉及歧视——生源已自筛选） |
| R6 | 删除 `publication_scorer`、`safety_net` 节点；其职能由锚定通道统一接管 |
| R7 | 方向图取代"一 JD 一 track"：~10 个方向各带独立 rubric（60 分预算），作为 track 分的依据；方向图人批、版本化冻结 |
| R8 | JD 池扁平：全部 JD 参与匹配，仅"有效/归档"两态；**相似即合并**，合并走版本链（superseded_by） |
| R9 | L1 全量做（召回+对账单，零 LLM）；L2 只在 HR 点击后做（正式契合分） |
| R10 | 证据冻结：raw_text hash 命中复用证据集；评分与匹配共享同一批冻结证据 |
| R11 | 统一单轮评分 + consistency 管线定期测 std（无阈值后没有"贴线"触发器） |
| R12 | 面试回流不做校准，只做分布对比分析 |

---

## 1. 管线全景

```
需求侧（JD）                          供给侧（简历）

JD 进池（粘贴/爬虫）                   简历导入
  │                                    │
  ▼                                    ▼
智能解析+结构化标签                    ① 解析+身份判定+论文核验
(must_have/bonus/direction_weights)    │
  │                                    ▼
相似检测→合并/新版本                   ② 文本清洗 → 双视图
  │                                    │   能力视图：抹背景
  │                                    │   匹配视图：留 title
  │                                    ▼
  │                                  ③ 证据抽取（三分类）→ 冻结落库
  │                                    │
  │                                    ▼
  │                                  ④ 能力评分（通用六维 40 + 方向 rubric 60）
  │                                    │
  │                                    ▼
  └──────── ⑤ L1 全量匹配（粗分+对账单）──────── 展示：能力分 × 匹配分（双列）
                    │
                    ▼ HR 点击
              ⑥ L2 深析（正式契合分+报告）
                    │
                    ▼
              ⑦ HR 人工决策 → 埋点（进面/结果）
```

---

## 2. 能力链重构（供给侧）

### 2.1 节点手术表

| 节点 | 处置 | 说明 |
|---|---|---|
| normalizer | **重写** | 删除五张档位规则表、LLM 裁决、`education_blind`、`organization_signal_tiers`；改为输出双视图（能力视图抹背景 / 匹配视图留 title）。隐私红线保留：身份证件号、电话等仍抹 |
| evidence_extractor | **重写** | 输出加 `info_class`（三类）；`title_fact` 禁止 LLM 打 strength；`action_fact` 标闭环标记（指标/验证/产物）；`vague_claim` 进推断暂估 |
| （新）evidence_freeze | **新增** | raw_text sha256 → 命中则复用整份证据集，跳过抽取 |
| track_router | 改 | 路由目标从 JD 改为方向图方向 |
| dynamic_tracks | 改 | spec 来源从 JD 池改为方向图 rubric |
| common_scorer / common_critic | 改 | gate 修正（见 2.2） |
| publication_scorer | **删** | 论文质量走 title_fact 锚定 |
| safety_net | **删** | 稀缺成就（状元/金牌）走 title_fact 锚定 |
| portfolio_aggregator | 改 | 只聚合能力分；匹配分不进聚合 |
| formatter | 改 | 输出契约见 §4；无任何决策措辞 |

### 2.2 gate 修正清单

| 现状 | 改为 |
|---|---|
| 无证据 → 封顶 1.0 | 只用于"推断通道也无货"的维度 |
| 无数字 → 封顶 2.5（看文本有无数字） | 改为抽取期标注"有无实质可核验结果"（产物/验收/发表/对照），不看字面数字 |
| `has_specific_tool` 算验证 | 移出验证三元组 |
| portfolio floors 纯条数触发 | 删；峰值地板只由 title_fact 产生 |
| 高分要"多来源多条" | 计数对象改为成就单元（同 source 证据折叠） |

### 2.3 锚定通道规则表（初版，可调）

| title_fact 档位 | 例 | 锚定效果 |
|---|---|---|
| S | 顶会 best/outstanding paper 一作、IOI/ICPC 金 | 相关维度穿透一切 gate，overall 峰值地板 85 |
| A | CCF-A 一作/共一（verified）、省状元 | 穿透计数 gate，峰值地板 80 |
| B | CCF-A 非一作、CCF-B 一作、国家级一等奖 | 穿透计数 gate，不贡献地板 |

---

## 3. 方向图（track 分的依据）

- **产出方式**：Moka 全量 JD（159+，定期重爬）embedding 聚类 → LLM 命名+蒸馏 rubric（从该方向真实 JD 要求）→ **人批** → 冻结版本
- **规模**：~10 个方向，每方向 rubric 预算 60 分（保住 40+60 量纲）
- **演化**：JD 映射置信度低 → 提议新方向 → 人批入库；方向图变更 = 版本 bump，存量评估不重跑
- **过渡**：现行已激活的 JD spec 继续当 track 用，方向图人批入库之日退役

---

## 4. JD 池重构（需求侧）

### 4.1 数据与行为

- 全量 Moka JD（159）+ 手工 JD 全部入池，扁平，无内外部/分层；状态仅 **有效 / 归档**
- 每条 JD 的结构化字段：`must_have[]` / `bonus[]` / `direction_weights{}` / `team`（部门，筛选用）
- **合并即版本**：入池时 requirement 向量检索全库，相似度 ≥ τ_merge（初值 0.90，可调）→ 前端提示"与 XX 高度相似"→ 确认后生成合并新版本，旧版 `superseded_by` 指向新版；Moka 重爬凭 job id 走同一版本链
- **激活语义死亡**：方向图上线后，JD 不再有"参与评分"的激活态；过渡期保留（仅已激活的 7 条 AI院 JD）

### 4.2 前端重做

- 部门筛选（按 `team` 聚合下拉）、状态筛选、全文搜索
- 有效 JD 显著标识；归档折叠
- 合并提示的确认 UI（并排对比新旧）
- 每个 JD 展开 → 「契合候选人」排行（匹配矩阵反向视图）

---

## 5. 匹配层（L1 全量 + L2 点击）

### 5.1 L1 计算规范（精确版——输入绝不止 title）

**输入（双侧全结构化）**：

| 侧 | 字段 |
|---|---|
| JD | `direction_weights{}`、`must_have[]`、`bonus[]`、`affinity{}`（可选：偏好学校/公司/实验室清单）、`team` |
| 候选人 | `direction_profile{}`（方向分/60）、冻结证据集（每条：quote、signals、info_class、dimension）、背景事实（学校原 title、历任机构原 title） |

**计算**（所有常数集中在配置，可调）：

```
① 方向分量  dir = Σ(direction_weight_k × 方向分_k / 60)          ∈ [0,1]
② 门槛分量  must = must_have 命中数 / must_have 总数             ∈ [0,1]
③ 加分分量  bonus = bonus 命中数 / bonus 总数                     ∈ [0,1]
④ 亲和分量  aff = JD affinity 清单与候选人背景事实的命中率         ∈ [0,1]（无清单则不计入，权重重归一）

L1 分 = 100 × (0.45·dir + 0.30·must + 0.15·bonus + 0.10·aff)
```

**标签命中判定**（不字符串匹配）：must_have/bonus 每条标签在 JD 解析时embedding；候选人每条证据 quote 在冻结时 embedding（两批向量都预计算缓存）。标签 × 证据逐对余弦，max ≥ τ_hit（初值 0.72，标注样本后校准）记一次命中，**命中必须带 evidence 引用**。

**输出**：L1 粗分（标注"参考"）+ 对账单（命中/缺口清单，每条带 evidence id）+ 置信备注（如"must_have 为空，门槛分量缺失"）。
L1 结果缓存键：`(evaluation_id, jd_id, jd_version)`；JD 版本 bump 或重评估时失效重算。**全量常开**。

### 5.2 L2（点击触发）

- HR 在对账单/排行里点「生成契合分析」→ LLM 读冻结证据全文 + JD 原文 → 正式契合分（0-100）+ 逐条要求核验报告
- 缓存键同 L1；**L2 不做全量预计算**，HR 用 L1 粗分决定点谁
- 费用纪律：L1 零 LLM，L2 一次一调用

---

## 6. 输出契约与前端呈现

| 字段 | 说明 |
|---|---|
| `overall_score` | 0-100 能力分，配 `config_version` |
| `direction_profile` | 方向 Top-2 + 分数 |
| `jd_matches` | L1 粗分 Top-N + 对账单；L2 生成后替换为正式契合分 |
| `core_strengths` / `potential_risks` / `interview_questions` | 全绑 evidence id |
| `packaging_risk` / `low_information` | 标记，不改分 |

前端：详情页双列「能力分 × 契合去向」；简历评估页评估结果下挂「推荐去向」卡（L1）+「选择 JD 深入匹配」按钮（L2）。**全站删除"建议面试/暂缓"类措辞**（LevelThresholds 的 tier/pool 文案下线）。

---

## 7. 数据埋点

- `persons` 加字段：`interview_status`（未标记/已进面/未进面）、`interview_at`、`interview_outcome`（通过/未通过/待定）
- HR 在人物页手动标记；分析视图（先做简单）：分数分布 vs 进面决策散点、通过者分数分布——回答"分数和人工决策对不对得上"
- **不做**自动校准，数据先攒着

---

## 8. 数据模型 / API 变更清单

**ORM**：`jd_entries` +`must_have`(Text JSON) +`bonus` +`direction_weights` +`affinity` +`version` +`superseded_by`；新表 `direction_specs`（方向图：key/label/rubric_json/version/status）；`persons` +三个埋点字段；`evaluations` 不动（旧评估按 config_version 自然隔离，不回填）

**API**：JD 合并检测 `GET /api/jds/similar?text=`；合并提交 `POST /api/jds/{id}/merge`；方向图 CRUD `/api/directions/*`；匹配 `GET /api/persons/{id}/matches`（L1 全量）、`POST /api/persons/{id}/match/{jd_id}`（L2 触发）；埋点 `POST /api/persons/{id}/interview-status`

---

## 9. 实施阶段与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | JD 池：Moka 全量入库 + 前端重做（部门筛选/有效突出）+ 相似合并 | 池内 159+ 条；合并提示抽查准确 |
| P1 | normalizer 双视图重写 + 删 publication_scorer/safety_net + 证据三分类 + gate 修正 | 同实质详/简写分差 ≤20%；320+ 测试绿 |
| P2 | 推断通道 + 证据冻结 | 模糊简历不吃死刑；同简历两跑证据一致 |
| P3 | Moka 聚类 → 方向图草案 → 人批入库 → 评估切换方向 rubric | 方向图上线；JD 激活语义退役 |
| P4 | L1 全量匹配（含 embedding 命中管线）+ 前端对账单 | 28 人 × 全池出分；命中清单可查证 |
| P5 | L2 点击深析 + 埋点字段与分布视图 | 点击出报告；埋点可录可看 |

## 10. 明确不做

- 不输出面试建议/档位；不做一 JD 一 track；不做自进化；不做信息置信度 rubric；不做面试回流自动校准；幻觉校验维持现状
