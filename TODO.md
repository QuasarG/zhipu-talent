# TODO · 智谱人才情报（三功能）

> 定位：智谱书院内部工具。三个**边界独立**的功能 + 一个共享 `persons` 主档底座。
> 每个功能可独立演示、独立交付。设计稿：`docs/talent_platform_design.md`。

## 产品结构

```
① 嘉宾画像+舆情   ② 简历初筛(含校准)   ③ 人才库
       └──────────┬─────────────────┘
                  ▼
           共享底座：persons 主档 + connectors + external_facts 缓存
```

**核心架构决策**：评分、匹配、舆情三者量纲不同，**永远分开**。
- 简历评分只评「能力」（绝对值）
- 匹配是「跟岗位的契合度」（相对值，独立模块，等 HR 需求，不阻塞②）
- 舆情是「风险闸门」（红黄绿，不进分数）

## 已完成（零件已造好，待组装）

- [x] **OCR 管线替换**：PDF 文本层提取 + RapidOCR 兜底（`ea9aac4`）
- [x] **权重校准**：通用 40 + Track 60，无验证封顶 2.5，真实简历验证（通过 64.8 / 未通过 53.8）
- [x] **Step 0 · 人员主档**（`9765bcc`）：persons 主档（fingerprint 归并）、external_facts 缓存、reputation_reports、tasks 任务表，schema v4
- [x] **Step 1 · 舆情链 + guest_check**（`64ce2d4`）：连接器框架、智谱 web_search、消歧→检索→分类→红黄绿分级、无需简历的嘉宾核查服务、人工复核流
- [x] **Step 2 · 学术核查链**（`edcfca8`）：OpenAlex 连接器、论文声称提取/核查/对齐（作者归属/一作/撤稿硬冲突判 mismatch）

## 待开发

### 功能① · 嘉宾画像 + 舆情筛查

输入：姓名 + 机构（+可选方向）
输出：研究方向画像 + 代表成果核查(✓/✗) + 舆情分级(红黄绿+来源)

复用现成积木：`run_guest_check` / `run_reputation_check` / `run_academic_check` / `get_or_create_person`

- [x] `core/connectors/aminer.py` MCP 连接器（SSE 协议，调 `search_person` 拿研究方向；`search_paper`/`get_*` 余额不足暂返回空）
- [x] 研究方向提取节点 + `GuestProfile` 数据模型（方向画像 + 成果核查 + 舆情汇总）
- [x] `core/guest_profile_service.py` 编排（AMiner 方向 → 学术链核查 → 舆情链分级，三链组装）
- [x] external_facts TTL 读缓存 helper（修复 `run_guest_check` 只写不读的问题）
- [x] 单元测试（mock 连接器，6 个全绿）
- [ ] AMiner `search_paper`/`get_person_detail` 付费接口接入（等账户充值，当前 `search_person` 免费够用）

### 功能② · 简历初筛（含打分校准）

输入：简历 PDF
输出：能力评分 + 画像 + 面谈追问（**不接舆情、不做匹配、不做决策闸门**）

前置技术债（调参前必须还清，否则参数散落 9 个文件越调越乱）：
- [ ] 评分参数集中化到单一 config 对象（common 权重 + 6 track dimensions 权重 + 2.5/3.5/1 封顶值 + floor dicts）
- [ ] 统一 4-5 处复制的 90/80/60 阈值（aggregation/formatter/workbench 各引用同一处）
- [ ] 统一 common/track 两份封顶逻辑的微妙差异
- [ ] 扩展 `config_version` hash 覆盖（封顶值、阈值纳入，调参后数据库能看出变过）

校准（10-30 条标注数据，不做网格搜索）：
- [ ] 增强 `scripts/run_real_screening.py`：支持指定配置对比、输出分离度报告 + 误判清单
- [ ] 按候选阶段校准预期（早期候选人博一/本科单独一套潜力预期线，补回 64.8→70 的 5 分差距）

匹配模块（独立，不阻塞②）：`match_scorer` 吃 Track 分布输出匹配分，等 HRBP 需求文档冻结 schema。

### 功能③ · 人才库

输入：无（纯查询）
输出：评估过的嘉宾 + 简历的列表/详情（含历史归并、舆情状态）

web 层几乎从零，DB 基础已在（PersonORM、evaluations 关联）：
- [ ] repository 查询层：`list_persons(filters, pagination)` / `get_person_detail(id)` / `list_reputation_by_person(id)`
- [ ] API 端点：`GET /api/persons` / `GET /api/persons/<id>` / `GET /api/persons/<id>/reputation` / `POST /api/reputation/<id>/review`
- [ ] 前端最小页面：人才库列表（姓名/类型/分数/舆情等级，可筛选排序）+ 详情页（评估历史 + 舆情面板）

## 实施顺序

| 顺序 | 功能 | 理由 | 工作量 |
|---|---|---|---|
| **1** | 功能①嘉宾画像 | 复用最多，AMiner 预留接口明确，能最快出可见成果 | 中 |
| **2** | 功能③人才库查询 | 轻量查询层，让①②的结果有展示出口 | 小-中 |
| **3** | 功能②打分校准 | 技术债重（参数集中化是大重构），数据少需谨慎迭代 | 大 |

## 明确不做的事（防止范围蔓延）

- ❌ **不做 `decision_composer` 决策组装** —— 三功能独立就不需要这个揉合点
- ❌ **不做 `reputation_gate` 闸门接进主 graph** —— 舆情归①，评分归②，各管各的
- ❌ **不做代码核查链**（github/zread）—— 等 Coding Plan
- ❌ **不做前端 2.0 大改版** —— 功能③只做最小可用页面
- ❌ **不做匹配模块** —— 等 HRBP 需求

## 外部依赖（需要人去推动）

- [ ] **HRBP 需求文档**：各研究组的能力/人才需求，决定匹配模块 schema
- [ ] **GLM Coding Plan**：ZRead MCP + 高级搜索能力（也可先只用 GitHub 官方 API）
- [ ] **合规确认**（法务/HRBP）：评估告知条款、舆情收录边界、数据保留期与删除权
- [ ] **AMiner 账户充值**（MCP 已接通 `search_person` 免费；`search_paper`/`get_person_detail` 需付费）

## 遗留技术债

- [ ] 证据提取器轮次间波动大（同一简历 owned/metric flag 可差 7 个），排名决策应走多轮均值（`run_consistency_eval.py`）
- [ ] 通过组均分 64.8 距目标 70 差 5 分，卡在早期阶段候选人（博一/本科无发表）——功能②按阶段校准解决
- [ ] git index.lock 反复出现（疑似 IDE/同步盘占用），提交前注意检查
