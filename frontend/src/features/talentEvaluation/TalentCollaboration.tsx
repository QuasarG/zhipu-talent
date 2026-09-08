import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { CollabEvent, ChatMessage, WorkflowNodeEvent } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import Avatar from "@/features/admission/GrokAgentAvatar";
import { reduceCollabEvents, type SceneInstance } from "@/features/admission/collabSceneModel";
import AssistantMessage from "@/features/chat/AssistantMessage";
import ToolCallCard from "@/features/chat/ToolCallCard";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import { useTalentCollaboration } from "./useTalentCollaboration";
import "./TalentCollaboration.css";

const names: Record<string, string> = { mapper: "能力分析", task_scorer: "任务评估", reviewer: "总审", system: "系统调度" };
const states = { waiting: "等待派工", working: "分析中", reviewing: "审阅中", done: "已完成", failed: "执行失败" };
const actions = { planning: "规划任务", reading: "阅读材料", searching: "查找依据", analyzing: "审阅发现", tool: "处理材料", messaging: "整理发现" };
const noop = () => {};
const brief = (text: string, max = 86) => {
  const plain = text.replace(/[#*`]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max)}…` : plain;
};

export default function TalentCollaboration(props: {
  runId?: string; pair?: { candidateId: string; jdId: string }; status: string;
  trace?: WorkflowNodeEvent[]; sample?: CollabEvent[];
}) {
  const { t } = useI18n();
  const live = !["completed", "failed", "cancelled"].includes(props.status);
  const { events, loading, error, retry } = useTalentCollaboration(props.runId, props.pair, live, props.sample);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [exchangeId, setExchangeId] = useState<string | null>(null);
  const [still, setStill] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [history, setHistory] = useState(false);
  const detail = useRef<HTMLElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(880);
  const [moving, setMoving] = useState<string | null>(null);
  const seenExchange = useRef<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const count = cursor === null || live ? events.length : Math.min(cursor, events.length);
  const visible = useMemo(() => events.slice(0, count), [events, count]);
  const scene = useMemo(() => reduceCollabEvents(visible), [visible]);
  const instances = [...scene.instances.values()].filter(i => i.role !== "system");
  const terminal = ["completed", "failed", "cancelled"].includes(scene.runState) || (!live && count === events.length);
  const goal = (instance: SceneInstance) => instance.taskGoal || props.trace?.find(e => e.agent_id === instance.id || e.node_id === instance.id)?.label || t(names[instance.role] || "材料评估");
  const agentTitle = (instance: SceneInstance | undefined) => {
    if (!instance) return t("系统调度");
    const base = names[instance.role] || t("任务评估");
    const task = goal(instance);
    if (instance.role === "task_scorer" && /工程|服务|实现/.test(task)) return `${base} · 工程`;
    if (instance.role === "task_scorer" && /实验|指标|结论/.test(task)) return `${base} · 实验`;
    return base;
  };
  const name = (id: string) => agentTitle(scene.instances.get(id));
  const lastExchange = scene.exchanges.at(-1);
  const exchange = scene.exchanges.find(e => e.eventId === exchangeId) || lastExchange;
  const focused = scene.instances.get(selected || "");
  const milestones = useMemo(() => events.map((e, index) => ({ e, count: index + 1 }))
    .filter(({ e }) => ["instance.created", "task.started", "task.dispatched", "result.returned", "task.failed", "run.completed", "run.cancelled", "run.failed"].includes(e.event.type)), [events]);
  const close = () => { setSelected(null); setExchangeId(null); setHistory(false); opener.current?.focus(); };
  const open = (id: string | null, message: string | null = null) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSelected(id); setExchangeId(message); setHistory(false);
  };
  const openDetails = selected !== null || exchangeId !== null || history;
  const empty = events.length === 0;
  useEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.min(880, entry.contentRect.width)));
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, [loading, empty]);
  useEffect(() => {
    const id = lastExchange?.eventId || null;
    const previous = seenExchange.current;
    seenExchange.current = id;
    if (!id || id === previous || !previous || still || (!live && !playing)) { setMoving(null); return; }
    setMoving(id);
    const timer = setTimeout(() => setMoving(null), 1400);
    return () => clearTimeout(timer);
  }, [lastExchange?.eventId, live, playing, still]);
  useEffect(() => {
    if (openDetails) detail.current?.focus();
  }, [openDetails]);
  useEffect(() => {
    setCursor(null); setPlaying(false); setSelected(null); setExchangeId(null); setHistory(false);
  }, [props.runId, props.pair?.candidateId, props.pair?.jdId]);
  useEffect(() => {
    if (!playing || live) return;
    const next = milestones.find(m => m.count > count) || (count < events.length ? { count: events.length } : null);
    if (!next) { setPlaying(false); return; }
    const timer = setTimeout(() => setCursor(next.count), 1800);
    return () => clearTimeout(timer);
  }, [playing, live, count, milestones, events.length]);

  const positions = new Map<string, { x: number; y: number }>();
  const narrow = width < 680;
  positions.set("system", { x: width / 2, y: 42 });
  const columns = [instances.filter(i => i.role === "mapper"), instances.filter(i => !["mapper", "reviewer"].includes(i.role)), instances.filter(i => i.role === "reviewer")];
  const layoutJitter = (id: string) => [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  columns.forEach((column, col) => column.forEach((i, row) => {
    const seed = layoutJitter(i.id);
    positions.set(i.id, { x: width * (col + .5) / 3 + (seed % 34) - 17 + (row % 2 ? 24 : -24), y: 310 + row * 180 + (seed % 26) - 13 });
  }));
  if (narrow) columns.flat().forEach((i, row) => positions.set(i.id, { x: width / 2 + (layoutJitter(i.id) % 22) - 11, y: 260 + row * 170 }));
  const stageHeight = narrow ? 310 + instances.length * 170 : 410 + Math.max(0, ...columns.map(c => c.length - 1)) * 180;
  const motionActive = !still && (live || playing);
  const senderPoint = exchange && positions.get(exchange.sender);
  const receiverPoint = exchange && positions.get(exchange.receiver);
  const from = exchange && (senderPoint || (exchange.sender === "system" ? positions.get("system") : undefined));
  const to = exchange && (receiverPoint || (exchange.receiver === "system" ? positions.get("system") : undefined));
  const directConversation = Boolean(exchange && senderPoint && receiverPoint && exchange.sender !== exchange.receiver);
  const bubbleTarget = from || to;
  // 低位 Agent 的气泡向空侧偏移，避免遮住上方工位的任务说明；尾巴仍回指发送方。
  const bubbleHalf = Math.min(150, Math.max(120, (width - 40) / 2));
  const bubbleShift = bubbleTarget && bubbleTarget.y > 430
    ? (bubbleTarget.x <= width * .58 ? 154 : -154)
    : 0;
  const bubbleCenter = bubbleTarget
    ? Math.max(bubbleHalf + 20, Math.min(width - bubbleHalf - 20, bubbleTarget.x + bubbleShift))
    : 0;
  const bubblePoint = bubbleTarget
    ? { x: bubbleCenter, y: Math.max(145, bubbleTarget.y - 90), tailOffset: bubbleTarget.x - bubbleCenter } : null;
  const active = instances.filter(i => ["working", "reviewing"].includes(i.state));
  const headline = loading ? "正在加载评估过程" : terminal ? props.status === "failed" || scene.runState === "failed" ? "评估中断" : props.status === "cancelled" || scene.runState === "cancelled" ? "评估已停止" : "评估已完成"
    : active.length > 1 ? "多位 Agent 正在并行评估" : active.length ? `${agentTitle(active[0])}正在工作` : "等待任务推进";
  const messages = focused ? scene.messages.filter(m => m.sender === focused.id) : [];
  const tools = focused ? [...scene.tools.values()].filter(m => m.instanceId === focused.id) : [];
  const handoffs = history ? scene.exchanges : exchangeId && exchange ? [exchange] : scene.exchanges.filter(e => (e.sender === selected || e.receiver === selected) && !(e.kind === "dispatch" && focused && e.text === goal(focused)));

  return <section className="talent-collab" data-still={still} aria-label={t("人才评估协作")}>
    <header className="tc-heading">
      <div><h2 aria-live="polite">{t(headline)}</h2><p>{t("能力分析、任务评估与总审，由系统协调推进")}</p></div>
      <details className="tc-options"><summary>{t("显示选项")}</summary><label><input type="checkbox" checked={still} onChange={e => setStill(e.target.checked)} />{t("减少动效")}</label></details>
    </header>
    {error && <div className="tc-notice" role="alert">{t(error)} <button onClick={retry}>{t("重试")}</button></div>}
    {!loading && !events.length ? <div className="tc-empty"><h3>{t(live ? "等待评估开始" : "这次评估没有可展示的协作过程")}</h3><p>{t(live ? "Agent 开始工作后会出现在这里" : "已有评估报告不受影响")}</p></div> :
      <div className="tc-scroll" ref={viewport}><div className="tc-stage" data-narrow={narrow} style={{ height: stageHeight, width }}>
        <div className="tc-lane-labels"><span>{t("理解候选人")}</span><span>{t("分工核验")}</span><span>{t("综合审阅")}</span></div>
        <button className="tc-coordinator" onClick={() => { opener.current = document.activeElement as HTMLElement; setHistory(true); }}><span className="tc-coordinator-mark" aria-hidden="true" /><strong>{t("系统调度")}</strong><span>{t("查看交接")}</span></button>
        {instances.length === 0 && <div className="tc-stage-empty"><span className="tc-stage-empty-dot" aria-hidden="true" /><strong>{t("正在搭建协作小组")}</strong><p>{t("系统会先分派能力分析 Agent")}</p></div>}
        {instances.map(instance => {
          const point = positions.get(instance.id)!;
          const involved = exchange?.sender === instance.id || exchange?.receiver === instance.id;
          const counterpart = exchange?.sender === instance.id ? to : exchange?.receiver === instance.id ? from : undefined;
          const lookingDirection = counterpart ? Math.sign(counterpart.x - point.x) * 4 : 0;
          const approachX = counterpart ? Math.max(-72, Math.min(72, (counterpart.x - point.x) / 2)) : 0;
          // 交流只在角色上方横向靠近，不能压住自己的工位线和任务文字。
          const approachY = counterpart ? -18 : 0;
          const action = terminal && ["working", "reviewing", "waiting"].includes(instance.state) ? t("已停止") : t(instance.actionKind && instance.state === "working" ? actions[instance.actionKind] : states[instance.state]);
          const state = terminal && ["working", "reviewing", "waiting"].includes(instance.state) ? "stopped" : instance.state === "reviewing" ? "working" : instance.state;
          const actionTone = instance.state === "failed" ? "error" : terminal && ["working", "reviewing", "waiting"].includes(instance.state) ? "neutral" : instance.state === "done" ? "success" : ["working", "reviewing"].includes(instance.state) ? "primary" : "neutral";
          return <button key={instance.id} className="tc-station" data-role={instance.role} data-active={!terminal && ["working", "reviewing"].includes(instance.state)} data-selected={selected === instance.id} data-involved={involved} style={{ left: point.x, top: point.y } as CSSProperties} onClick={() => open(instance.id)} aria-label={`${t(names[instance.role] || "任务评估")}：${goal(instance)}，${action}`}>
            <span className="tc-character" data-moving={motionActive && moving === exchange?.eventId && exchange?.sender === instance.id} data-working={motionActive && !terminal && ["working", "reviewing"].includes(instance.state)} data-communicating={motionActive && directConversation && involved} style={{ "--tc-travel-x": `${approachX}px`, "--tc-travel-y": `${approachY}px`, "--tc-delay": `${(instance.bornSeq % 5) * -0.7}s` } as CSSProperties}><Avatar role={instance.role} state={state} still={still || !live && !playing || terminal} gaze={involved && !terminal ? lookingDirection : 0} /></span>
            <span className="tc-desk"><strong>{t(agentTitle(instance))}</strong><StatusChip className="tc-state-chip" tone={actionTone as "success" | "error" | "primary" | "neutral"}>{action}</StatusChip></span>
            <span className="tc-task">{brief(goal(instance), 64)}</span>
          </button>;
        })}
        {exchange && <button className="tc-message" key={exchange.eventId} aria-label={t("点击查看完整交接")} style={bubblePoint ? { left: bubblePoint.x, top: bubblePoint.y, "--tc-tail-offset": `${bubblePoint.tailOffset}px` } as CSSProperties : undefined} onClick={() => open(null, exchange.eventId)}>
          <span className="tc-message-meta"><strong>{t(name(exchange.sender))}</strong><span className="tc-speaking">{t("和")}</span><strong>{t(name(exchange.receiver))}</strong><small>{t(exchange.kind === "dispatch" ? "派发任务" : exchange.succeeded ? "交付发现" : "报告问题")}</small></span>
          <p>{brief(exchange.text) || t("查看本次交接内容")}</p><span className="tc-message-open">{t("查看完整内容")}</span>
        </button>}
      </div></div>}
    <footer className="tc-footer">
      {!live && events.length > 0 && <><Button type="button" variant="tonal" icon={playing ? "pause" : "replay"} onClick={() => { if (playing) setPlaying(false); else { if (count >= events.length) setCursor(0); setPlaying(true); } }}>{t(playing ? "暂停回放" : "回看协作")}</Button>
        {cursor !== null && <><input aria-label={t("协作回放进度")} type="range" min="0" max={events.length} value={count} onChange={e => { setPlaying(false); setCursor(Number(e.target.value)); }} /><Button type="button" variant="text" icon="arrow_back" onClick={() => { setCursor(null); setPlaying(false); }}>{t("回到结果")}</Button></>}
      </>}
      <span>{t("点击 Agent 查看任务与依据")}</span>
    </footer>
    {openDetails && <aside ref={detail} tabIndex={-1} className="tc-detail" aria-label={t("工作详情")} onKeyDown={e => { if (e.key === "Escape") close(); }}>
      <header><h3>{t(history ? "交接记录" : focused ? names[focused.role] || "任务评估" : "本次交接")}</h3><button onClick={close}>{t("关闭详情")}</button></header>
      <div className="tc-detail-body">
        {focused && <section><h4>{t("负责的任务")}</h4><p>{goal(focused)}</p>{focused.note && <p>{focused.note}</p>}</section>}
        {handoffs.map(e => <section key={e.eventId}><h4>{t(name(e.sender))}<span className="tc-speaking">{t("正在交流")}</span>{t(name(e.receiver))}</h4><p>{e.text || t("本次交接未记录正文")}</p></section>)}
        {messages.length > 0 && <details><summary>{t("查看工作内容")}</summary>{messages.map(m => {
          const message: ChatMessage = { id: m.eventId, conversation_id: "collab", role: "assistant", content: { segments: [{ type: "text", text: m.text }] }, citations: [], status: "completed", created_at: m.at || "" };
          return <AssistantMessage key={m.eventId} message={message} busy={false} onDecide={noop} hideAvatar />;
        })}</details>}
        {tools.length > 0 && <details><summary>{t("查看材料与工具")}</summary>{tools.map(tool => <ToolCallCard key={tool.eventId} segment={{ type: "tool", call_id: tool.callId, tool: tool.tool, label: tool.tool, args_summary: tool.argsSummary, status: tool.status === "running" ? undefined : tool.status, summary: tool.summary, detail: tool.argsSummary }} />)}</details>}
        {!handoffs.length && !messages.length && !tools.length && <p className="tc-muted">{t("尚未交付工作内容")}</p>}
      </div>
    </aside>}
  </section>;
}
