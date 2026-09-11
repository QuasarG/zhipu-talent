# 人才评估协作界面

## 范围

人才评估的运行与报告过程使用「单条 assistant 消息」呈现（奖学金评估过程同款），候选人评估（评审团）与面试准入共用同一渲染链路。

## 信息与交互

- 评估过程 = 一条 assistant 消息：主 agent（评审团主席 / 准入系统编排）的全部工作叙事按真实顺序生长——文本（markdown）、工具卡、子 agent 行。
- 子 agent 以 `spawn` 段内联：默认一行摘要（名称 · 最新动态 · 运行中动效/终态 chip），点击展开该子 agent 自己的工作段（工具卡、说明文本）。
- live：浏览器 SSE / 轮询 run trace 增量渲染（复用问答 `applyEvent` 与 `AssistantMessage`）；完成后过程叙事落库（panel_trace / run_trace），历史直接渲染同一条消息。
- 不做重放：没有回放进度条、暂停/播放控件；历史即最终 trace 的静态渲染。

## 实现与边界

- 段模型复用问答 `ChatSegment`，新增 `spawn` 段类型；后端产出 text/tool/spawn 三类段。
- 样式走 Tailwind 设计 token，语义色仅表状态；动画沿用 `chat-enter`，遵循 `prefers-reduced-motion`。
- 前端只渲染后端真实事件，不虚构工作流状态。

## 模型冒烟

panel 链路事件词汇与 trace 装配由 `tests/test_job_fit_panel.py` 覆盖；准入链路由 `tests/test_interview_admission_evaluator.py` 覆盖。
