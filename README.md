<div align="center">

# 智谱人才研究平台

**内部人才研究、简历评估与知识管理工具**

</div>

## 功能

- **人才问答**：自然语言提问，AI Agent 自动检索人才库、查论文、查舆情，生成调查报告
- **简历评估**：导入 PDF/图片简历，自动结构化解析、论文核验、多维度 AI 评分
- **人才库**：统一档案管理、关系图谱可视化、分组收纳、对比滑轨、版本对比
- **JD 池**：JD 粘贴即录入（智能解析标题/团队），LLM 起草岗位 Track 评估规格，人批激活后驱动评估
- **画像澄清（Grill）**：面向用人部门的需求澄清问答，蓝本岗位检索自 Moka 全量 JD 向量库

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask、SQLAlchemy、LangGraph |
| 前端 | React 19、TypeScript、Tailwind CSS 4、Vite |
| LLM | 智谱 GLM-5.2（评估/问答，OpenAI 兼容端点）、智谱 ZAI（OCR/Embedding/Web Search） |
| 向量库 | Qdrant（人才知识 talent_knowledge / 岗位库 grill_jobs 双集合） |
| 数据库 | MySQL（生产）/ SQLite（本地可选） |

## 快速开始

```bash
# 1. 克隆 + 装依赖
git clone <repo-url> && cd zhipu_talent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env   # 填入 API Key

# 3. 装前端依赖 + 构建
cd frontend && npm install && npm run build && cd ..

# 4. 启动后端
.\.venv\Scripts\python.exe -m flask --app agi_talent_radar.web.workbench:app run --port 8503
```

打开 `http://localhost:8503` 即可。

> 开发模式：前端 `npm run dev`（5173）+ 后端设 `VITE_DEV=1`，vite proxy 自动转发 API 到 8503。

## 部署

服务器部署用 `deploy/` 目录下的 systemd service + nginx 配置：

```bash
sudo cp deploy/talent-radar.service /etc/systemd/system/
sudo cp deploy/nginx-talent-radar.conf /etc/nginx/sites-enabled/
```

数据库 schema 首次请求时自动迁移（版本化，幂等）。

### 生产环境变量（`/etc/zhipu-talent.env`）

| 变量 | 说明 |
|---|---|
| `LLM_API_KEY` | 智谱开放平台 Key（GLM-5.2 + Web Search + Embedding + OCR 一把通吃） |
| `OPENAI_MODEL` / `OPENAI_BASE_URL` | `glm-5.2` / `https://open.bigmodel.cn/api/paas/v4` |
| `AMINER_API_TOKEN` | AMiner 论文核验/学者检索（可选） |
| `FLASK_SESSION_SECRET` | 会话密钥（必填，随机长串） |
| `QDRANT_URL` / `QDRANT_COLLECTION` | 向量库地址/集合名 |

设置页（/settings）可在线更新 Key（原子写回 .env，脱敏显示）。

### 健康检查与运维

```bash
curl -s http://127.0.0.1:8503/health   # 应用 + 外部服务探测（有缓存）
systemctl status talent-radar          # 应用（gunicorn 127.0.0.1:8503）
systemctl status qdrant                # 向量库（数据在 /var/lib/qdrant）
journalctl -u talent-radar -n 50       # 日志（500 详情只在日志，响应不外泄）
```

### 备份与恢复

```bash
# 生产库为 MySQL（localhost:3306/talent_radar）
mysqldump -uroot -p talent_radar --single-transaction > backup.sql
# 简历原件 + Qdrant 存储（停服后冷拷一致性最佳）
tar czf backup.tgz /var/lib/zhipu-talent
# 恢复：解回原路径后 systemctl restart talent-radar
```

### 故障排查速查

| 症状 | 先看 |
|---|---|
| 首页 502 | `systemctl status talent-radar` + 日志尾 50 行 |
| 评估一直失败 | 设置页「重新检测」看 llm/embedding 状态 |
| 语义检索空结果 | qdrant 是否 active、集合是否存在 |
| 问答报「服务器内部错误」 | `journalctl -u talent-radar` 搜对应时间点 traceback |

## 项目结构

```
agi_talent_radar/
  agents/          简历解析、评估链、论文核验、JD spec 起草
  grill/           画像澄清问答（蓝本岗位检索）
  core/            数据模型、LLM 客户端、DB 运行时
  knowledge_agent/ 人才问答 ReAct Agent
  web/             Flask API + SPA 静态服务
frontend/
  src/features/    问答、简历评估、人才库
  src/components/  UI 组件库（MD3 设计系统）
deploy/            systemd + nginx
docs/
  design/          产品/架构设计稿（含评估维度与数据流）
  reviews/         审计与复盘（AUDIT.md = 评分体系偏差分析）
  CONTEXT.md       领域语义约定；HANDOVER.md = 交接手册
samples/           简历样例数据
outputs/           评估产物归档（final/ 双轮终版、real/ 真实简历验证）
tests/             pytest 基线（全绿后方可提交）
```

> 文档入口：新接手先读 `docs/HANDOVER.md` 与 `docs/reviews/AUDIT.md`。
