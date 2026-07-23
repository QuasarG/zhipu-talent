# TODO · AGI 人才情报平台

> 定位：智谱书院内部工具，用「简历证据 + 外部公开事实 + 舆情风险」三类可追溯证据，
> 为联培学生/社会人员筛选与嘉宾邀请提供「推荐/不推荐 + 匹配方向 + 人才画像」。
> 设计稿：`docs/talent_platform_design.md`（含完整架构图与节点详设）。

## 已完成

- [x] **OCR 管线替换**：PDF 文本层提取 + RapidOCR 兜底，移除视觉模型与外观分（`ea9aac4`）
- [x] **权重校准**：通用 40 + Track 60，无验证封顶 2.5，真实简历验证（通过 64.8 / 未通过 53.8）
- [x] **Step 0 · 人员主档**（`9765bcc`）：persons 主档（fingerprint 归并）、external_facts 缓存、reputation_reports、tasks 任务表，schema v4，evaluations 挂 person_id + config_version
- [x] **Step 1 · 舆情链 + guest_check**（`64ce2d4`）：连接器框架、智谱 web_search、消歧→检索→分类→红黄绿分级、无需简历的嘉宾核查服务、人工复核流
- [x] **Step 2 · 学术核查链**（`edcfca8`）：OpenAlex 连接器、论文声称提取/核查/对齐（作者归属/一作/撤稿硬冲突判 mismatch）

## 待开发

### Step 3 · 决策组装 + 舆情闸门 + 复核流（下一块，最大）

- [ ] `formatter` 升级为 `decision_composer`：推荐/不推荐结论 + 匹配方向 + 人才画像 + 风险面板
- [ ] 舆情链、学术链接入主评估 graph（外部链结果与评分在 decision_composer 汇合，互不侵入）
- [ ] `reputation_gate`：红→强制不推荐，黄→挂人工复核，绿→不干预（舆情不做分数加减）
- [ ] `review_router`：红/疑似写 reputation_reports(pending)，人工确认/驳回后才终态
- [ ] API：`POST /api/reputation/<id>/review`、guest_check 发起端点、人员主档查询端点
- [ ] 前端：报告页加「证据对齐 ✓/✗」与「舆情风险面板（红黄绿+来源链接+复核按钮）」

### Step 4 · 匹配模块（阻塞：等 HRBP 需求文档）

- [ ] `requirement_profiles` 表 CRUD（研究组 + 方向要求 + 能力权重，schema 待 HRBP 反馈冻结）
- [ ] `match_scorer`：需求档案 ↔ Track 分布 + 外部对齐事实，输出匹配分 + 匹配点/缺口点
- [ ] API：需求档案管理 + `GET /api/persons/<id>/matches`

### Step 5 · 代码核查链（阻塞：Coding Plan / ZRead MCP）

- [ ] `connectors/github.py`：GitHub 官方 API，贡献事实（commit 归属、PR、star、活跃度）
- [ ] `connectors/zread.py`：ZRead MCP（search_doc / get_repo_structure / read_file）项目深度解读
- [ ] `agents/code/`：github_lookup → repo_reader → contribution_alignment（识别 fork 充原创、刷 commit）

### Step 6 · 前端 2.0

- [ ] 三模式入口：招聘筛选 / 嘉宾核查 / 人才库
- [ ] 报告页四块：评分与 Track 分布 + 证据对齐 + 舆情面板 + 匹配方向雷达
- [ ] 活动视图：一批嘉宾的批量核查清单（风险等级排序，红色置顶）

### 增强项（有闲再做）

- [ ] OpenReview 连接器：真正核查「在投」状态（ICLR 等会议投稿公开）
- [ ] AMiner 连接器：中文学术数据补强（需申请 open.aminer.cn 数据接口，可走内部渠道）
- [ ] 异步任务队列升级：DB 任务表 + 线程池 → RQ/Celery + Redis（量级上来后）
- [ ] 人员主档智能归并增强：同名不同人的拆分与人工合并入口

## 外部依赖（需要人去推动）

- [ ] **HRBP 需求文档**：各研究组的能力/人才需求，决定 Step 4 的 schema（负责人：对接 HRBP）
- [ ] **GLM Coding Plan**：ZRead MCP + 高级搜索能力，决定 Step 5（也可先只用 GitHub 官方 API）
- [ ] **合规确认**（法务/HRBP）：评估告知条款、舆情收录边界（只公开职业信息）、数据保留期与删除权
- [ ] **AMiner 数据接口申请**（可选，走智谱内部渠道更快）

## 遗留技术债

- [ ] 证据提取器轮次间波动大（同一简历 owned/metric flag 可差 7 个），排名决策应走多轮均值（`run_consistency_eval.py`）
- [ ] 通过组均分 64.8 距目标 70 差 5 分，卡在早期阶段候选人（博一/本科无发表）——需要「按候选阶段校准预期」规则或方向匹配信号（属 Step 3/4 连带解决）
- [ ] git index.lock 反复出现（疑似 IDE/同步盘占用），提交前注意检查
