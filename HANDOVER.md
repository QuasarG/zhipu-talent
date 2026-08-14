# 项目交接文档（2026-08-10）

> 面向下一个接手的工具/工程师。读完这份 + `docs/evaluation_dataflow.md` 即可开工。

## 1. 这是什么

智谱人才雷达：书院学生简历评估 + 人才库 + 人才问答 Agent + Z.AI 奖学金初筛。
技术栈：Flask + LangGraph + SQLite（生产）/ React + Vite + Tailwind（MD3 自研组件库）。
线上：`http://121.40.110.250/`（阿里云，需登录）。

## 2. 服务器与部署（重要，踩过坑）

- 服务器 `121.40.110.250`，root 登录。**可用 SSH 私钥是 `duhangyuan.pem`**（在用户 Windows 的
  `~/.ssh/`，已复制到 WSL `/root/.ssh/`）；`id_ed25519_digitalocean` 对任何用户都不可达。
- **2026-08-10 状态：sshd 卡死**（TCP 可连、认证永不返回），需在阿里云控制台 VNC 里
  `systemctl restart sshd`。HTTP 服务不受影响。
- 部署目录：`/opt/zhipu-talent/`，`releases/<时间戳>` + `current` 软链；venv 共享在
  `/opt/zhipu-talent/venv`；DB 是 SQLite `/var/lib/zhipu-talent/talent_radar.db`（WAL 已开）。
- systemd 单元 `/etc/systemd/system/talent-radar.service`（源文件在仓库 `deploy/`），
  gunicorn 1 worker × 24 threads，绑 127.0.0.1:8503，nginx 反代 80。
- **部署流程**（本地工作区直接打包，不走 git）：
  ```bash
  release=/opt/zhipu-talent/releases/$(date +%Y%m%d%H%M%S)
  ssh ... "mkdir -p $release"
  tar czf - --exclude=.git --exclude=node_modules --exclude=.venv --exclude=__pycache__ \
    --exclude=tmp --exclude=outputs* --exclude=data --exclude=.env --exclude='*.pid' --exclude='*.log' \
    . | ssh ... "tar xzf - -C $release"
  # 然后 chown、ln -sfn current、systemctl restart talent-radar、curl 健康检查（302/200 即活）
  ```
  **教训**：release 目录名必须取自 tar 命令自己的输出，严禁在服务器上 `ls | sort` 现猜
  （tar 保留旧 mtime，会选错目录切错版本，犯过两次）。
- 服务密钥在 `/etc/zhipu-talent.env`（LLM_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL 等，LLM 走智谱 GLM glm-5.2）。
  注意：`pip install -r requirements.txt` 里的 `zai>=0.2` 在服务器镜像源找不到，但 venv 已装过，
  报错可忽略。
- 改 gunicorn 参数要同步改服务器上的 unit 文件 + `systemctl daemon-reload`。

## 3. 代码地图

- `agi_talent_radar/agents/` — 评估 LangGraph 各节点（normalizer 脱敏 / evidence_extractor /
  track 路由与六个 track / common_potential / aggregation / formatter）
- `agi_talent_radar/core/` — db(orm/migrations/repository/runtime)、llm_client、scoring_config、
  connectors（web_search/aminer/dblp/openalex…）
- `agi_talent_radar/knowledge_agent/` — 人才问答 ReAct Agent（手写循环 + HITL 门控中断续跑）
- `agi_talent_radar/scholarship/` — 奖学金初筛模块（四阶段：资格筛选→脱敏评分→舆情加减→排序，
  与书院评估完全独立）
- `agi_talent_radar/web/` — workbench.py（主路由）+ auth.py + knowledge_api.py + config_api.py
- `frontend/src/pages|features|components/ui` — React SPA；UI 只用 `components/ui` 下的现成组件
- `docs/evaluation_dataflow.md` — **评估链路逐节点数据流**（本次会话整理，必读）

## 4. 本次会话（08-06 ~ 08-10）已完成

1. 问答引用卡片升级：人物引用带完整 meta（机构/方向/分组/评估分），卡片双按钮跳人才库定位
   （`/talent-pool?focus=`）和完整档案（`/talent-pool/<id>`）；所有人物工具的引用都挂了 meta。
2. 舆情 HITL：新门控工具 `request_reputation_review`，问答中评价类舆情阻断成卡片逐条人工核验，
   驳回条目不进总结，落 `ReputationReportORM`。外部来源引用默认"已确认"（不再满屏待核验）。
3. 研究组匹配功能整体下线（JD 常变不维护），前后端/测试/文档全清。
4. 代码库大扫除：删 legacy jinja 前端、tmp/、flask 日志；**修复全部 16 条红测试，基线 294 全绿
   （此后任何新红测试都是真问题）**；补了 review_reputation 缺失的路由装饰器。
5. 人才库批量评估：修 500（PersonORM 未导入）、dismissed 候选人重评自动回队列（group 复位
   pending）、保留期豁免 running、前端自动跳简历评估页聚焦、全部跳过时显示原因。
6. 奖学金初筛模块从零建成（见 §3），DB 迁移 v16。
7. 并发：SQLite WAL + busy_timeout（有 8 线程并发写回归测试）、gunicorn 8→24 线程、
   LLM client 单例。

## 5. 讨论已定、尚未实施的设计（优先级从高到低）

1. **评估报告重构 + 工作台化**（用户痛点"不得劲"的根源）：
   - 人才库默认视图改优先级队列（建议沟通/待核验/待定/暂缓），图谱降级为 tab；
   - 每人一个"系统建议动作"接 HR 状态机；无简历人物分流；
   - 报告改决策三段式：结论卡（值不值得聊+为什么+下一步）→ 风险挂动作（去核验/面谈问）→
     维度详情折叠；弱化绝对分，展示池内相对位置。
2. **兜底节点（safety_net）**：评估链末端新增节点，输入原始简历+全部评分结果，输出特殊情况
   清单（被埋没的亮点/警惕异常/非典型背景），每条带证据+置信度+是否建议核验，**不改分数**。
   案例：高考 704 市状元但项目空洞的简历，能力分 34 是对的，但状元信号必须被显式列出。
3. **评分可信度地基**：
   - 一致性：证据提取一次冻结复用（同简历同证据集），评分 3 轮取中位数；验收目标"中位数极差 ≤5"；
   - 区分度：**锚定 rubric**——现状是"锚定了看什么、没锚定几分长什么样"（维度有 evidence_rule，
     0-5 只有一句话档位）。要给每档写行为锚点实例，用团队自己的真实案例（如 AlignCalib=4 分锚点），
     锚点纳入 config_version。
   - 权重调整 UI 排最后，且必须带版本管理和一键回默认。
4. **飞书问卷接入**：奖学金材料入口。已查证：lark-event 不支持多维表格事件；走 Base 自动化
   webhook 或服务器轮询（推荐轮询）。钩子已留：`scholarship/ingest.py:create_application_from_payload`。
   **阻塞点：问卷后台不在用户手里。**
5. 会话防重入仍是软检查（同会话同时双击可能双跑），要堵就做唯一索引。

## 6. 开发约定

- 测试：WSL 里用 `.venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_e2e_integration.py`
  （.venv 是 Windows 版，靠 WSL interop 跑；当前基线 294 passed）。
- 前端：`cd frontend && npm run build`（含 tsc）+ `npx oxlint <改动文件>`，产物直出
  `agi_talent_radar/web/static/dist/`。
- UI 只用 `frontend/src/components/ui/` 现成组件；中文注释、禁止长分割线、禁止 argparse。
- **git 工作区有 300+ 个未提交文件**（多账号/分组等一大批功能从未提交）。用户知情但选择暂不提交；
  接手后第一件事建议和用户确认是否整理提交，否则任何 git 操作都很危险。
- AGENTS.md 要求傲娇猫娘人格（Neko）——如果下一个工具没这个设定，忽略即可。
