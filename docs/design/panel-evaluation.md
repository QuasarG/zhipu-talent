# 评审团评估链路（panel mode）重构方案

状态：已落地；2026-09-11 起 panel 为唯一评估引擎（tag `pre-eval-mode-convergence-20260911` 保存三模式并存的历史状态，`agent_assessor.py` 双 agent 与 `workflow` 模式已删除）。
范围：(JD×候选人) 评估链路，即 `agents/job_fit/` + `core/runner.py` 的 `jd_fit_v2` 输出。
关联：共享材料访问层已抽为 `agents/job_fit/materials.py`（MaterialsContext / 文本层 / 视觉转译 / 检索 / JSON 解析）。

---

## 1. 背景与动机

评估链路经历三版：

| 版本 | 结构 | 病根 |
|---|---|---|
| workflow（现行兜底） | 单次 `call_llm_json` 只看结构化简历 | 从不读本人原始材料，证据无从谈起 |
| agent（现行默认） | 单评估 agent 长循环 + 观察者旁路督导 | ①上下文随工具结果无限膨胀，后面 JD 的评分被前面全部阅读内容污染；②观察者只能注入 user input 建议且可被无视，每 turn 一次全量调用是纯税；③全部 JD×6 维一块大 JSON 提交，GLM 1210 高发；④任何一环挂全盘重来，无并行 |
| panel（本方案） | 主席动态派 mission + 类型化评审员 | — |

核心思路：**编排的"判断"交给主席现场决定（派谁、派几次、深挖哪里），编排的"纪律"（预算、校验、装配、裁决）留在确定性代码里。自由度在判断里，纪律在合同里。**

## 2. 不变量（冻结区，本重构一行不改）

- 评分合同：`job_fit_raw = {"assessments": [{jd_id, hard_requirements[], dimensions[6], confidence, strengths, risks, missing_information, interview_questions, assessment_summary}]}`。
- 六维与权重：`evaluator.DIMENSIONS`（direct_task_match 30 / technical_depth 20 / ownership 15 / evidence_quality 15 / engineering_scale 10 / transferability 10）。
- 门槛裁决：`_build_evaluation` / `_guard_decision`（unmet→reject；unknown→hold/reject；INTERVIEW_SCORE 70 / HOLD_SCORE 55 / 直接匹配 3.0/2.5）。**主席与评审员的输出里没有 decision 与总分字段。**
- 硬门槛 evidence 防幻觉校验：`_normalize_requirement` 拿 evidence 去结构化简历全文（`resume_corpus`）做原文包含校验，查不到降级 unknown。
- 结果组装：`run_job_fit_formatter` → `CandidateEvaluation`。
- API 与存储：`POST /api/candidates/{id}/evaluate` 的 SSE 协议（`node`/`result`/`error` 事件）、`evaluation_runs` 落库、`_run_evaluation_job` 的收尾逻辑。
- 三档模式开关：`TALENT_EVALUATION_MODE`，新增 `panel` 值；`agent`/`workflow` 原样保留。

## 3. 架构总览

```
┌─ S0 整备（确定性）──────────────────────────────────────────┐
│ 材料 → 案卷目录 dossier：文件清单(类型/段数/有无文本层)      │
│       + 结构化简历 + 成绩单核验报告                          │
│       + JD 区：spec 评分点(主) + JD 原文(参考)               │
│       + 文本层预热缓存（pdf 文字层/docx/txt）                │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ S1 评审循环（主席 agent 动态驱动）─────────────────────────┐
│ 主席每轮 call_llm_json，二选一：                             │
│   dispatch: 派 1..N 个 mission（新开或续派既有评审员）       │
│   synthesize: 收队，输出逐 JD 定性字段                       │
│ mission = 类型化评审员执行（新 context 或暂存续派）          │
│ findings 全部过 schema 校验 + 引文反查                       │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ S2 装配 + 裁决（确定性）──────────────────────────────────┐
│ findings 按 jd_id/维度归并 → job_fit_raw（主席碰不了分数）  │
│ → run_decision_guard（原节点）→ run_job_fit_formatter（原） │
└────────────────────────────────────────────────────────────┘
```

## 4. 数据合同

### 4.1 案卷目录（dossier，S0 产出，主席唯一全局视图）

```python
dossier = {
  "resume": resume_dump,               # 结构化简历（现 _system_prompt 同款字段裁剪）
  "academic_report": {...},            # 论文核验报告
  "files": [                           # 案卷目录：主席看这个决定派活
    {"file": "grzs.docx", "kind": "resume", "segments": 6, "text_layer": true},
    {"file": "cjd.pdf", "kind": "unknown", "segments": 0, "text_layer": false},  # 扫描件
    ...
  ],
  "jobs": [{
    "jd_id": "...", "title": "...",
    "spec": {                          # jd_spec.py 拆解的评分点（主输入）
      "dimensions": [{"key","label","max_points","evidence_rule"}],
      "evidence_focus": "...", "high_score_rule": "...", "keywords": [...]
    },
    "raw_ref": "jobs/JD-A.txt",        # JD 原文写入临时文件挂进材料区（硬门槛须对照原文措辞）
  }, ...],
}
```

- spec 为空的老 JD：`spec=null`，主席简报注明"按原文自行拆解硬门槛"，原文照挂。
- JD 原文落成材料目录下的临时文件（评估结束即删），这样评审员用现有 `read_text` 就能读，不用加新工具。
- 视觉转译**不在此全量做**：S0 只预热文本层；`read_pages` 按需触发，转译结果进 pipeline 级共享缓存（`MaterialsContext.vision_cache/text_cache`，全队复用，谁先转谁缓存）。

### 4.2 主席决策（每轮 `call_llm_json`，无 function-calling）

```json
// dispatch —— missions 数组 1..N 个
{"action": "dispatch",
 "missions": [{
    "mission_id": "m1",                // 新 id=新开；已有 id=续派（会话暂存，见 §6.3）
    "type": "verify | deep_read | jd_match | cross_check | generic",
    "goal": "一句话目标（前端时间线直接展示）",
    "files": ["NLP-EMNLP.pdf"],        // 指定材料（可空=评审员自查目录）
    "questions": ["论文是否被公开库收录"],
    "resume_claims": ["《...》ACL 2024"],  // 仅 verify 用：主席从简历提取的待核验 claim
    "note_to_worker": "续派时可写：你之前已读过X，直接从Y继续"
 }]}
// synthesize —— 逐 JD 定性字段（没有分数！）
{"action": "synthesize",
 "per_jd": [{"jd_id": "...", "confidence": 0.7,
             "strengths": [{"summary","evidence":[]}],
             "risks": [{"summary","evidence":[]}],
             "interview_questions": ["..."],
             "missing_information": ["..."],
             "assessment_summary": "一句话"}]}
```

非法 JSON / action 不认识 / mission type 不在菜单 → 整轮作废，回喂错误重试（≤2 次），仍败强制 synthesize。

### 4.3 主席系统提示词要点

注入四块：①评审团制度说明（你是组长，评分裁决是制度定的，你只管派活和写综合意见）；②dossier 全文；③**类型菜单**（从注册表生成，每个类型一行"什么时候用"）；④纪律（覆盖率要求：简历含论文/奖项而未派 verify 不得收队；JD 全部要有 jd_match 覆盖；发现 findings 矛盾应补派 cross_check 或在 missing_information 注明）。

### 4.4 findings（评审员产出，按类型各有小 schema）

全部经独立 JSON 通道提交（`call_llm_tools(tools=[])` + `_parse_json_block` json_repair 兜底），校验失败带错误回喂重试 ≤2。

| 类型 | schema 要点 | 引文反查 |
|---|---|---|
| `verify` | `{"claims": [{"claim", "verdict": "verified|supported|claimed|unverifiable", "source", "quote"}]}` | quote 须在材料文本中存在 |
| `deep_read` | `{"assessments": [{"jd_id", "dimensions": [{key(主席指定), score, rationale, evidence["文件名 第N页: ..."]}]}]}`——直接产出维度分，证据笔记进 evidence | quotes 须在材料文本中存在 |
| `jd_match` | `{"hard_requirements": [{requirement, status, evidence(简历原文), rationale}], "dimensions": [{key ∈ {direct_task_match, transferability}, score 0-5, rationale, evidence}]}` | evidence 走简历语料反查（与 `_normalize_requirement` 同基准） |
| `cross_check` | `{"arbitrations": [{"question", "conclusion", "quotes": []}]}` | quotes 反查 |
| `generic` | 任一维度的 `{key, score, rationale, evidence[]}` 笔记 | evidence 反查 |

反查失败的条目**剔除该条**（不是打回整份）并在 findings 里标记 `dropped_quotes`，评审员可见。整份 schema 校验失败才打回重交。

### 4.5 装配产物

即 §2 的 `job_fit_raw`。来源映射：

- `hard_requirements`、`direct_task_match`、`transferability` ← jd_match mission（每 JD 必须有一份）。
- `technical_depth`、`engineering_scale`、`ownership` ← deep_read / generic mission 笔记，主席在派单时指定维度主题，装配按 topic→维度 key 对号入座。
- `evidence_quality` ← verify 的 claim_ledger **规则映射**（§7），不由任何 LLM 直评。
- 定性字段 ← 主席 synthesize。

## 5. mission 类型注册表（差异化做在模板层）

每个类型四件套：提示词模板 + 工具白名单 + findings 校验器 + 轮数预算。执行循环只有一个通用 mission runner，类型只是注入项。**加工种 = 注册表加条目，循环零改动。**

| type | 工具白名单 | 预算 | 提示词纪律要点 |
|---|---|---|---|
| `verify` | read_text, read_pages, verify_paper, web_search | 6 | 无公开源只能标 claimed，禁止推测；出外网唯一授权靠白名单强制，不是提示词恳求 |
| `deep_read` | read_text, read_pages, search_text | 8 | 分页读完指定材料；引文必须到页；只评主席指定的维度主题 |
| `jd_match` | read_text, search_text（+简历语料） | 6 | 继承 JOB_FIT_PROMPT 事实纪律段：met 必引简历原文、unknown≠unmet、偏好不入硬门槛、评分点(evidence_rule)是找证据导航 |
| `cross_check` | read_text, search_text | 4 | 只回答主席指出的矛盾点，不扩展新话题 |
| `generic` | 全部 6 只读工具 | 6 | 兜底，现为通用评审员提示词 |

注册表实现为 `panel.py` 内的 dict 常量（模板、白名单、预算都是数据），不建类层次。

## 6. 主席循环与预算

### 6.1 轮结构

```
for round in 1..PANEL_LEAD_MAX_ROUNDS(12):
    state = {dossier, missions_done: [{id,type,goal,status,findings摘要}], rounds_left}
    decision = call_llm_json(主席提示, state)     # 重试≤2
    dispatch → 逐个 mission 跑 runner（v1 串行），findings 入 state
    synthesize → break
预算耗尽 / 重试失败 → 注入"立即 synthesize"指令跑最后一轮，仍败按失败收尾
```

主席输入只有 dossier + findings **摘要**（每条 mission 摘到 ~300 字），永远不看材料原文——上下文天然有界。

### 6.2 预算表

| 护栏 | 默认（env 可调） | 耗尽行为 |
|---|---|---|
| mission 总数 | `PANEL_MAX_MISSIONS=8` | 拒绝新 dispatch，提示收队 |
| 单次续派工具轮 | `PANEL_MISSION_ROUNDS=6` | 带已读信息返回 |
| mission 生命周期工具轮 | `PANEL_MISSION_LIFETIME_ROUNDS=10` | 强制终结该会话，只收已有 findings |
| 主席决策轮 | `PANEL_LEAD_MAX_ROUNDS=12` | 强制 synthesize |
| findings 整份校验 | 重试 ≤2 | mission 标 failed |

### 6.3 会话暂存与续派

- `mission_sessions: {mission_id: messages}` 内存表，存活期 = 本次评估运行。
- 派工单 `mission_id` 已存在 → 追加 user 指令续跑，评审员带着已读内容继续（省重复阅读的工具轮与 token）；新 id → 全新 context（只含 mission 简报 + 案卷目录）。
- 适用：部分失败重试（图片转译超时重试那张图）、findings 校验打回、主席要求深挖已读材料、cross_check 复用相关 mission 的上下文。
- 评审员不能再派 agent（单层，无递归）。
- 上下文跨 mission 不共享；唯一跨任务信息通道是主席在简报/续派指令里写的内容。

## 7. 装配规则（确定性）

```python
def assemble(dossier, missions, lead_synthesis) -> job_fit_raw:
    # 分数只能来自 mission findings；主席定性字段原样并入
    # evidence_quality 规则映射（唯一不由 LLM 直评的维度）：
    #   w = Σ(verified:1.0 / supported:0.6 / claimed:0.2 / unverifiable:0.1) / claim 数
    #   score = clamp(1 + 4*w, 0, 5)
    #   代表作论文(简历 publications 的首条) verdict ∈ {claimed, unverifiable} → score ≤ 2.5
    #   （对齐奖学金评审的反通胀锚点）
    # 缺维（mission failed 且主席未补）→ 2.0 + rationale "该维评估未覆盖，按保守缺省"
    #   + missing_information 注明 + 该 JD confidence ×0.5
    # 无 verify mission 且简历含论文/奖项 → evidence_quality = 2.5 缺省 + 注明未查证
    # 组装后直接交 run_decision_guard / run_job_fit_formatter（原节点函数）
```

降级不是静默的：缺维缺省分、未查证缺省分都在 rationale 与 missing_information 里写明，且压 confidence。**绝不静默补 0 分**（0 分会把人错误推向 reject）。

## 8. 失败语义

| 层级 | 失败 | 行为 |
|---|---|---|
| 评审员工具轮 | 单工具异常 | 工具返回 error 详情，消耗当轮，评审员自行调整 |
| 评审员 findings | schema/引文校验不过 | 打回重试 ≤2，仍败 → mission=failed，主席收到通知 |
| 主席决策 | JSON 非法 | 回喂错误重试 ≤2，仍败 → 强制 synthesize |
| 主席 synthesize | 校验不过/轮尽 | 定性字段留空（装配容错），评估照常出分 |
| 整体 | 主席循环崩溃 | 抛错 → `_run_evaluation_job` 现有失败落库路径，错误带 stage 归因 |

决策（decision）只依赖维度分与硬门槛，定性字段全灭不影响裁决——关键路径只有 mission findings，主席合成是增强不是阻塞。

## 9. SSE 事件协议

沿用现有 `{type:"node", node, label, status, phase, message}`，panel 模式的节点序列：

```
material_desk（材料整备，done）
panel_lead（评审循环，running → done）—— 期间以增量 node 事件播报：
    message = "任务① verify 论文与奖项查证：2 项确认，1 项失败"
assembly（装配+裁决，done）
```

新增可选字段 `mission_id`/`mission_type`（老前端忽略未知字段，向后兼容）。v1 前端**零改动可跑**（时间线按 message 文本展示）；按 mission_id 分组的 UI 增强列为后续优化。

## 10. 模块改动清单

| 文件 | 改动 |
|---|---|
| `agents/job_fit/panel.py` | **新建**：TYPE_REGISTRY、MaterialsContext 预热（复用 agent_assessor 的提取函数）、主席循环、mission runner、mission_sessions、assemble()。预计 ~400 行 |
| `agents/job_fit/agent_assessor.py` | 不动（agent 模式回滚用）。`MaterialsContext`/`_extract_text_layer`/`_parse_json_block` 从这里 import 复用，不复制 |
| `core/runner.py` | 新增 `run_candidate_panel_stream(...)`：整备 yield → 主席循环 yield → 调 `run_decision_guard`/`run_job_fit_formatter` 原节点 → result。~60 行 |
| `web/workbench.py` | `_run_evaluation_job` 分流加 `elif mode == "panel"`，一行 |
| `frontend` | v1 零改动；mission 分组展示为后续优化 |

## 11. 测试计划

`tests/test_job_fit_panel.py`，FakeLLM 脚本化（主席决策序列 + 评审员工具调用序列），不打外网：

1. 类型注册表：白名单生效（deep_read 拿不到 web_search）、预算封顶。
2. 主席循环：dispatch→synthesize 正常收队；非法 JSON 重试；轮数耗尽强制 synthesize。
3. 会话续派：同 mission_id 续跑时 messages 复用（工具轮计数累计）、生命周期轮封顶。
4. findings 校验：引文反查剔除坏条目；整份校验打回与 failed 标记。
5. 装配：维度对号入座、evidence_quality 映射表全分支、缺维降级、无 verify 缺省。
6. 端到端（fake）：panel 全程产出能通过 `_build_evaluation` + `run_job_fit_formatter`，输出与 workflow 模式同构。

真实 e2e：`TALENT_EVALUATION_MODE=panel` 下对 grzs（陈鼎熙，13 文件包）跑一次，核对 SSE 时间线、evaluations 落库、decision 与维度分合理。

## 12. 环境变量

```
PANEL_MAX_MISSIONS = 8
PANEL_LEAD_MAX_ROUNDS = 12
PANEL_MISSION_ROUNDS = 6
PANEL_MISSION_LIFETIME_ROUNDS = 10
```

`TALENT_EVALUATION_MODE` 已随 agent/workflow 模式删除；panel 是唯一评估路径。

## 13. 上线与删除计划（已执行）

panel 验收通过后，双 agent 循环与观察者已删除，共享的工具与材料访问迁入 `agents/job_fit/materials.py`，`TALENT_EVALUATION_MODE` 开关移除。
