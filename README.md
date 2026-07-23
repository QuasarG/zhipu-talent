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

AI 人才潜力初评助手 MVP。它支持 PDF、JSONL、Markdown 和 TXT 简历，通过 LangGraph 完成文本提取（扫描页本地 OCR 兜底）、脱敏、证据挖掘、多 Track 路由、并行专业评估、Critic 复核和结构化输出。

</div>

项目参考了本机 `RedNoteMatrix Copilot` 的工程组织方式：包内拆分 `agents/core/web`，脚本入口放在 `scripts/`，测试放在 `tests/`，输出样例放在 `outputs/`。

## 快速运行

1. 复制 `.env.example` 为 `.env`，填入 DeepSeek API Key：

   ```powershell
   cp .env.example .env
   # 编辑 .env：DEEPSEEK_API_KEY=sk-...
   ```

2. 安装 Python 依赖：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

项目不再内置合成简历数据。正常使用时从 Web 工作台上传真实简历，候选人和评估结果会持久化到 MySQL。
如需对外部 JSONL / Markdown / TXT 文件进行离线批处理，必须显式传入路径：

```powershell
.\.venv\Scripts\python.exe scripts\run_batch.py <resume-file> [output-dir]
```

> 如果暂时没有 API Key，可以运行使用 mock 的单元测试。

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

工作台支持导入 PDF / JSONL / Markdown / TXT 简历、按分层和导入分类筛选、查看候选人详情、Track 分布与证据链。PDF 在后端直接提取文本层，扫描页自动走本地 RapidOCR 兜底，不再调用多模态模型。

## Agent 流程

批量导入时先经过轻量双节点分类 Agent：

```text
Import Agent (初评分类) -> Import Agent (回顾确认)
```

逐人深评流程：

```text
Normalizer -> Document Quality -> Evidence Extractor -> Track Router -> Route Auditor
                                                                  |-> Common Potential -> Common Critic --|
                                                                  |-> Base Track --------------------------|
                                                                  |-> Agent Track -------------------------|
                                                                  |-> Safety Track ------------------------|-> Portfolio Aggregator
                                                                  |-> Multimodal Track --------------------|
                                                                  |-> Systems Track -----------------------|
                                                                  |-> AI4Science Track --------------------|
Portfolio Aggregator -> Global Critic -> Formatter
```

- `Normalizer`：盲化学校与 GPA 等背景信号，统一结构。
- `Evidence Extractor`：调用 LLM 提取具体动作、量化结果、ownership、验证方法与 Track 提示。
- `Track Router`：将候选人分配到 1-3 个 Track，权重表示工作分布而不是能力强弱。
- `Common Potential`：统一评价问题定义、严谨性、学习迁移、ownership、可信度和成长轨迹，共 40 分。
- `Track`：按 Base、Agent、Safety、Multimodal、Systems、AI4Science 六套独立 Rubric 评分，各 60 分。
- `Portfolio Aggregator`：按 `40 + Σ(Track 权重 × 60)` 汇总最终分。
- `Global Critic`：检查路由、通用分、专业分和最终结论的一致性。
- `Formatter`：调用 LLM 输出评分、画像、优势、风险、面谈追问和培养方向。

## 目录结构

```text
agi_talent_radar/
  agents/
    routing/       多 Track 路由与路由校验
    common_potential/  通用潜力 Rubric 与节点
    aggregation/   跨 Track 聚合与全局 Critic
    tracks/
      base/        Base Track 独立 spec 与节点
      agent/       Agent Track 独立 spec 与节点
      safety/      Safety Track 独立 spec 与节点
      multimodal/  Multimodal Track 独立 spec 与节点
      systems/     Systems Track 独立 spec 与节点
      ai4science/  AI4Science Track 独立 spec 与节点
      shared/      Track 公共协议与执行骨架
  core/            Pydantic 模型、Rubric、IO、Graph、Runner
  web/             Flask Dashboard
docs/              过程复盘
outputs/           样例输出
scripts/           批量运行脚本
tests/             单元测试
```

## 设计原则

这个 MVP 刻意避免把学校、GPA、论文名气当主评分依据。评分只吃证据项，证据项必须来自原简历，并尽量关注“做了什么、怎么做、怎么验证、本人负责到哪里”。它不是自动录用器，而是给下一轮沟通排序和生成追问的辅助工具。

## PDF 文本提取与本地 OCR

PDF 导入不再依赖多模态模型。后端优先用 PyMuPDF 直接读取文本层（绝大多数简历 PDF 自带文本层，秒级完成）；单页提取字符过少时判定为扫描件，自动用本地 `rapidocr-onnxruntime` 对该页 OCR 兜底。提取出的全文交给与 TXT/Markdown 相同的文本 LLM 解析节点完成结构化，零额外 API 成本。OCR 仅本地推理，不调用任何外部服务。

```bash
pip install rapidocr-onnxruntime
```

简历中的文字始终作为不可信数据处理，不执行页面指令，也不自动访问二维码或链接。

## 数据库结构

Web 工作台使用 MySQL 持久化候选人和评估运行。应用启动时会检查 `schema_versions`，
将旧版 Track、维度和证据 JSON 回填到关系表后删除旧列。当前 schema version 为 4（含人员主档 `persons`、外部证据缓存 `external_facts`、舆情报告 `reputation_reports`、异步任务 `tasks`）。

```text
candidates
  -> evaluations
       -> evaluation_node_runs
       -> evaluation_evidence
       -> track_assignments
       -> track_evaluations
            -> dimension_scores
       -> dimension_scores (common potential)
```

`dimension_evidence_links`、`assignment_evidence_links` 和 `track_evaluation_evidence_links`
保存证据引用，不再使用 `evidence_ids` JSON 字符串关联。每次评估都会创建新的
`evaluations` 记录，保留历史版本；节点失败会记录为 `failed`，不会覆盖上一次完整结果。
