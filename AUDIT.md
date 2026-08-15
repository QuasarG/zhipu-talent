# 项目审计报告（2026-08-15，audit/product-tech-review 分支）

> 方法：全量代码走查（前端/后端两个只读侦察）+ 真实使用数据（老服务器 SQLite 只读查询）+ 产品链路人工走查。
> 原则：ponytail——删减优先，每个结论给证据，每个行动项给代价。

## 一、真实使用画像（产品判断的地基）

| 数据 | 值 | 含义 |
|---|---|---|
| evaluations / dimension_scores | 157 / 3263 | **评估是绝对核心**，人均跑过 2-3 轮（评分可信度迭代） |
| persons / candidates | 28 / 23 | 人才库小；评估→入库转化率 100% 量级，链路通 |
| chat conversations / messages | 5 / 36 | 问答用过但很浅（人均 7 条） |
| grill_sessions | **1** | 深挖面谈基本没人用 |
| engagement_status_history | 22 | HR 状态流转在用，但频率低 |
| users | 9 | 内部小工具，无并发压力 |
| scholarship / reputation | 0 / 2 | 奖学金模块上线后零使用 |

**产品结论**：这是一个"评估机+人才账本"在被真实使用，问答是辅路，grill 和奖学金目前是负重。一切改进应围绕"评估→入库→流转"主链路加密，而不是铺新模块。

## 二、产品视角：功能必要性

### 该砍/该降级的
- **grill（候选人深挖面谈）**：1 个会话。全套工作台（画像卡/大纲/交付物/9 个前端组件 + 独立 agent 循环）维护成本与使用量严重倒挂。建议：不删代码，从导航撤掉入口，降级为实验功能（README 记录开启方式）。
- **奖学金模块**：0 申请。独立四阶段 pipeline 是当时为 Z.AI 奖学金初筛赶工的，事件结束后无消费方。建议同上：撤导航入口，代码冻结。
- **OnboardingTour 里的模型名文案**（"当前是 GLM-5.2[1M]"）：模型名硬编码在引导文案里，每次换模型都要改两处词典。该文案不该提模型名。

### 缺失的（按主链路价值排序，TODO.md 已识别、经代码核实全部属实）
1. **T4 评估→人才库跳转**（高）：评估页 `person_id` 数据都有（CandidateMetaDropdown 已显示"人才库 ID"），但零跳转。用户核实：两套数据模型间的"心智撕裂"是真实痛点。
2. **T5 状态历史 UI**（高）：后端 API 完整（engagement_status_history 22 条真实数据），前端 `api.engagementHistory` 定义了但零调用。半成品。
3. **T3 档案页发起问答**（中高）：档案→问答断链。
4. **T8 guest 可评估**（中）：批量评估选到 guest 就整按钮禁用——反直觉规则，用户会以为是 bug。
5. **T6 评估报告复制 Markdown**（中）：评估结果无法离开系统，说服力断在页面里。

### 不建议做的（对 9 用户内部工具）
- T7 看板（@dnd-kit 拖拽 2-3 天，28 个人用看板是杀鸡牛刀）
- T9 数据看板（人均 28 人的库，统计问答已覆盖）
- T10 筛选持久化、T11 评论流、T12 渠道追踪（使用量撑不起）

## 三、技术审计

### 高优先（真实风险）
- **`GET /api/persons` N+1**：每 person 3 次额外查询（find_candidate_by_person + 2 lazy load），28 人=84+ 查询。数据量小时无感，但这写法会随库线性恶化。`list_candidates_for_queue`、`batch-evaluate`、`pending-publications` 同病。
- **异常文本直接外泄**：`except Exception as exc: return jsonify({"detail": str(exc)}), 500` 模式遍布 workbench.py——traceback/内部路径可能直接进响应。无统一 errorhandler。
- **91 处手写 `jsonify({"detail": ...})`**：错误码/文案无规范，前端只能靠字符串匹配。

### 中优先（维护成本）
- **workbench.py 1678 行**：36 路由 + 导入流水线(370行) + 30 个序列化器(383行) 挤一文件。导入流水线和序列化器与路由零耦合，可整体搬走。
- **7 个 agent 模块零测试**：formatter(209行)/evidence_extractor/safety_net/publication_scorer/aggregation/scoring_normalization/org_normalizer——其中 safety_net 和 evidence_extractor 恰恰是"评估可信度"的关键节点。
- **前端死依赖 4 个**：lucide-react、@dnd-kit/sortable、@dnd-kit/utilities、@iconify-json/material-symbols 全部零 import（Icon 用的是本地 JSON 子集）。白装。
- **SSE 消费样板 5 处重复**、**侧栏 relativeTime 逐字重复**（chat/grill 各一份）。

### 低优先（记录即可）
- 巨型组件（ResumeContent 723 行等）——内部已按子组件切分，只是同文件；不痛不痒。
- localStorage 键前缀三套并存（talent-radar-/zhipu_talent./talent-pool.）。
- repository.py 同构 CRUD（list_candidates vs list_candidates_by_group）。

### 做得好的（保持）
- 前端类型安全：全 src 零 `: any`/`@ts-ignore`。
- 密钥卫生：零硬编码，.env 已 ignore，设置页脱敏。
- SSE 解析单一实现（parseSSE），消费侧重复但核心不重复。
- 316 个后端测试用例、309 passed 基线。

## 四、本分支已落地的行动

（ponytail 阶梯：每项先问"能不能不写"）

1. **产品连岛**：T4 评估→人才库跳转 + T5 状态历史时间轴 + T8 guest 批量评估改为自动跳过。
2. **死代码清理**：4 个零 import 依赖移除、knowledge 空目录、引导文案去模型名。
3. **N+1 修复**：/api/persons 批量预载。
4. **异常卫生**：统一 errorhandler，500 不再外泄内部异常文本。

## 五、建议后续（不在本分支做）

- grill/奖学金撤导航（需要产品确认，改一行路由的事）
- agents/ 7 个零测试模块补最小 happy-path 测试（优先 safety_net/evidence_extractor）
- workbench.py 拆分（先搬导入流水线，纯移动零逻辑变更）
