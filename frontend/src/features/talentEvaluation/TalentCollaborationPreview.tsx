import { useEffect, useState } from "react";
import type { CollabEvent } from "@/lib/types";
// 这里只负责喂入合成事件做视觉验收；真正的实现位于 TalentCollaboration，
// 由 AdmissionPane 与 BatchViews 的正式人才评估入口共用。
import TalentCollaboration from "./TalentCollaboration";

// 合成样例仅供本地预览，不调用评估接口，不写入业务数据。
const script: Array<[string, string, CollabEvent["event"]]> = [
  ["system", "system", { type: "run.started" }],
  ["mapper", "mapper", { type: "instance.created" }],
  ["system", "system", { type: "task.dispatched", receiver: "mapper", instruction: "从项目材料中梳理候选人的能力证据" }],
  ["mapper", "mapper", { type: "task.started" }],
  ["mapper", "mapper", { type: "result.returned", receiver: "system", digest: "识别出工程实现和实验设计两组证据，交由任务评估分别核验。" }],
  ["engineering", "task_scorer", { type: "instance.created" }],
  ["research", "task_scorer", { type: "instance.created" }],
  ["system", "system", { type: "task.dispatched", receiver: "engineering", instruction: "核验检索服务的工程实现与个人贡献" }],
  ["engineering", "task_scorer", { type: "task.started" }],
  ["system", "system", { type: "task.dispatched", receiver: "research", instruction: "核验实验对照、指标选择与结论可靠性" }],
  ["research", "task_scorer", { type: "task.started" }],
  ["engineering", "task_scorer", { type: "tool.started", tool: "read_pages", call_id: "sample-read", args_summary: "项目说明，第 3–5 页" }],
  ["engineering", "task_scorer", { type: "tool.completed", call_id: "sample-read", status: "ok", summary: "找到服务设计与贡献说明" }],
  ["engineering", "task_scorer", { type: "message.completed", text: "### 工程依据\n材料说明了索引构建、接口设计与部署过程。个人贡献仍需在面试中核实。" }],
  ["engineering", "task_scorer", { type: "result.returned", receiver: "research", digest: "工程指标口径已确认，供实验对照一起审阅。" }],
  ["engineering", "task_scorer", { type: "result.returned", receiver: "system", digest: "工程实现证据完整；建议面试核实个人负责的模块边界。" }],
  ["research", "task_scorer", { type: "result.returned", receiver: "system", digest: "有实验指标，但缺少消融对照；这一点需保留为待核实项。" }],
  ["reviewer", "reviewer", { type: "instance.created" }],
  ["system", "system", { type: "task.dispatched", receiver: "reviewer", instruction: "综合两组发现，检查结论是否有充分依据" }],
  ["reviewer", "reviewer", { type: "task.started" }],
  ["reviewer", "reviewer", { type: "result.returned", receiver: "system", digest: "保留工程优势及实验对照的待核实项，评估内容已整理完成。" }],
  ["system", "system", { type: "run.completed" }],
];
const sampleEvents: CollabEvent[] = script.map(([id, role, event], seq) => ({ protocol: "agent-collab/v1", run_id: "local-demo", run_kind: "admission", event_id: `sample-${seq}`, seq, at: null, instance_id: id, agent_type: role, task_id: id, task_kind: null, turn_no: 1, message_id: null, cause_event_id: null, event }));

export default function TalentCollaborationPreview() {
  const [count, setCount] = useState(15);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    if (count >= sampleEvents.length) { setRunning(false); return; }
    const timer = setTimeout(() => setCount(n => n + 1), 1800);
    return () => clearTimeout(timer);
  }, [running, count]);
  const [sample, setSample] = useState(sampleEvents.slice(0, count));
  useEffect(() => setSample(sampleEvents.slice(0, count)), [count]);
  return <main style={{ maxWidth: 1280, margin: "0 auto", padding: 24 }}>
    <header style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "center", marginBottom: 20 }}><h1>人才评估 · 交互预览</h1><span>演示数据，不是真实评估</span>
      <button onClick={() => { setCount(0); setRunning(true); }}>从头演示</button><button onClick={() => setRunning(!running)}>{running ? "暂停演示" : "继续演示"}</button><button onClick={() => { setCount(sampleEvents.length); setRunning(false); }}>查看完成态</button>
    </header>
    <div style={{ height: "calc(100vh - 110px)", minHeight: 600 }}><TalentCollaboration sample={sample} status={count >= sampleEvents.length ? "completed" : "running"} /></div>
  </main>;
}
