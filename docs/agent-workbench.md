# Agent 协作工作台

两个入口共用活动流组件，但不混淆实际执行架构：

- 候选人评估（唯一链路，panel）：主席动态派发 verify、deep_read、jd_match、cross_check、generic 任务，当前实现逐个执行，可续派同一任务上下文。
- 面试准入批次：能力映射、并行任务评分、证据修复、独立总审、确定性系统裁决；独立于候选人评估链路。

顶部呈现实际开始且尚未完成的实例；中央呈现按时间排列的公开工作说明、工具调用与返回摘要、派工和回传；右侧按真实实例筛选。历史报告通过独立 trace 接口按需读取，列表接口保持精简。

事件保留 agent_id、agent_type、target_id、event_kind、detail；panel 工具事件另带 tool、call_id。没有收发字段的旧记录不会推断交接关系。工作说明不是模型隐藏推理，工具返回展示摘要而非完整原始响应。

限制：panel 延续现有最近 400 条记录上限，超长运行不保证完整历史；历史数据缺失的字段无法追溯补齐。本次不改评分算法、调度策略或并发上限。

验证：Python 定向回归；frontend 下运行 `node --experimental-strip-types --test scripts/test-agent-activity.mjs` 和 `npm run build`。遵照用户要求不使用浏览器自动化。
