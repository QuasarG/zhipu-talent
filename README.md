<div align="center">

# AGI Talent Radar

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C?style=flat-square&logo=langchain&logoColor=white)](https://www.langchain.com/langgraph)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI--compatible-LLM-412991?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com/docs)
[![Pydantic](https://img.shields.io/badge/Pydantic-2.13-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square)](https://www.sqlalchemy.org/)
[![MySQL](https://img.shields.io/badge/MySQL-optional-4479A1?style=flat-square&logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Tests](https://img.shields.io/badge/Tests-unittest-E5A50A?style=flat-square)](./tests)

AI 人才潜力初评助手 MVP。它基于 `10_ai_phd_resumes.jsonl` 批量读取 10 位虚拟 AI 博士简历，通过 LangGraph 节点完成脱敏、证据挖掘、跨领域打分、Critic 复核和结构化输出。

</div>

项目参考了本机 `RedNoteMatrix Copilot` 的工程组织方式：包内拆分 `agents/core/web`，脚本入口放在 `scripts/`，测试放在 `tests/`，输出样例放在 `outputs/`。

## 快速运行

1. 复制 `.env.example` 为 `.env`，填入 DeepSeek API Key：

   ```powershell
   cp .env.example .env
   # 编辑 .env：DEEPSEEK_API_KEY=sk-...
   ```

2. 安装依赖并运行：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe scripts\run_batch.py
   ```

运行后会生成：

- `outputs/talent_evaluations.json`：完整结构化结果。
- `outputs/talent_evaluations.md`：可直接阅读的排序表和候选人明细。

> 如果暂时没有 API Key，可以直接查看 `outputs/` 下的样例输出，或运行单元测试（测试使用 mock）。

测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests -v
```

启动 Web 工作台：

```powershell
$env:FLASK_APP="agi_talent_radar.web.workbench"
.\.venv\Scripts\python.exe -m flask run --host 127.0.0.1 --port 8502
```

打开：

```text
http://127.0.0.1:8502
```

工作台支持批量导入 JSONL / Markdown 简历、按分层和导入分类筛选、查看候选人详情与证据链。

## Agent 流程

批量导入时先经过轻量双节点分类 Agent：

```text
Import Agent (初评分类) -> Import Agent (回顾确认)
```

逐人深评流程：

```text
Normalizer -> Evidence Extractor -> Cross-Domain Scorer -> Critic -> Formatter
                                      ^                  |
                                      |__ 回炉重打分 _____|
```

- `Normalizer`：盲化学校与 GPA 等背景信号，统一结构。
- `Evidence Extractor`：调用 LLM 提取具体工具、具体动作、量化结果和 ownership 证据。
- `Cross-Domain Scorer`：调用 LLM 按统一 Rubric 比较不同方向候选人。
- `Critic`：调用 LLM 检查引文与评分逻辑，必要时回炉重打分。
- `Formatter`：调用 LLM 输出评分、画像、优势、风险、面谈追问和培养方向。

## 目录结构

```text
agi_talent_radar/
  agents/          LangGraph 节点
  core/            Pydantic 模型、Rubric、IO、Graph、Runner
  web/             Flask Dashboard
docs/              过程复盘
outputs/           样例输出
scripts/           批量运行脚本
tests/             单元测试
```

## 设计原则

这个 MVP 刻意避免把学校、GPA、论文名气当主评分依据。评分只吃证据项，证据项必须来自原简历，并尽量关注“做了什么、怎么做、怎么验证、本人负责到哪里”。它不是自动录用器，而是给下一轮沟通排序和生成追问的辅助工具。
