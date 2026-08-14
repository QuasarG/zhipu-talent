<div align="center">

# 智谱人才研究平台

**内部人才研究、简历评估与知识管理工具**

</div>

## 功能

- **人才问答**：自然语言提问，AI Agent 自动检索人才库、查论文、查舆情，生成调查报告
- **简历评估**：导入 PDF/图片简历，自动结构化解析、论文核验、多维度 AI 评分
- **人才库**：统一档案管理、关系图谱可视化、分组收纳、版本对比

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask、SQLAlchemy、LangGraph |
| 前端 | React 19、TypeScript、Tailwind CSS 4、Vite |
| LLM | 智谱 GLM-5.2（评估/问答，OpenAI 兼容端点）、智谱 ZAI（OCR/Embedding/Web Search） |
| 向量库 | Qdrant（人才知识检索） |
| 数据库 | SQLite（生产）/ MySQL（可选） |

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

## 项目结构

```
agi_talent_radar/
  agents/          简历解析、评估链、论文核验
  core/            数据模型、LLM 客户端、DB 运行时
  knowledge_agent/ 人才问答 ReAct Agent
  web/             Flask API + SPA 静态服务
frontend/
  src/features/    问答、简历评估、人才库
  src/components/  UI 组件库（MD3 设计系统）
deploy/            systemd + nginx
```
