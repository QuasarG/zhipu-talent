# 人才评估协作界面

## 范围

人才评估的运行与报告过程入口使用协作群聊组件（`AgentGroupChat`），候选人评估（评审团）与面试准入共用同一套呈现与转写模型。

## 信息与交互

- 协作过程呈现为群聊：主席与各评审/评估 Agent 是群成员，在同一个会话里派工、汇报进展、回传结论、调用工具。
- 消息全部来自 agent-collab/v1 真实事件：`task.dispatched` = 主席派工消息（带 @接收者、材料与问题清单），`message.completed` = 成员工作说明，`result.returned` = 结论回传 / 主席综合意见，`task.failed` = 失败回传；`run.*` 与 `planning.*` 渲染为居中系统胶囊。
- 工具调用复用问答的 ToolCallCard：进行中以运行态动效出现在群里，落章后并入对应消息；不显示内部 ID、协议或事件计数。
- 顶栏为运行状态、群成员（头像 + 状态点）与任务统计（执行中 / 待处理 / 已完成 / 失败）；列表底部「正在输入」胶囊对应正在工作的成员。
- 跟随滚动：上翻即暂停拽底并出现「回到最新」；历史记录支持回看协作（播放/暂停/进度条，按消息步进）。
- 消息体复用问答的 AssistantMessage（markdown 渲染），动画沿用 `chat-enter`；打字点动画遵循 `prefers-reduced-motion`。

## 实现与边界

- `collabChatModel.ts`：纯函数把事件流折叠为聊天转写（成员、消息、任务统计），与回放共用同一解释逻辑，重复 event_id 幂等。
- 样式走 Tailwind 设计 token（`bg-surface-low`、`border-outline-variant`、语义色仅表状态），仅打字点动画使用独立 CSS。
- 页面读事件，不写数据；分页游标取已读取页尾，解析配对后固定运行 ID，卸载忽略旧请求。
- 准入链路没有主席角色，派工类消息只会出现在评审团链路；后端未提供的事件不虚构。

## 本地预览

`node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5182`（frontend 目录），访问 `/__preview/talent-collaboration`。只在开发模式启用；明确标注合成数据，不调用真实评估，不读写人才库。生产构建不包含该预览入口。

模型冒烟验证：`npx tsx scripts/verify-collab-chat.mts`（frontend 目录）。
