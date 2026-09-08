import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Icon from "@/components/ui/Icon";
import Avatar from "./GrokAgentAvatar";
import AssistantMessage from "@/features/chat/AssistantMessage";
import ToolCallCard from "@/features/chat/ToolCallCard";
import type { ChatMessage, CollabEvent } from "@/lib/types";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  instanceName, reduceCollabEvents,
  type ActionKind, type CollabScene, type InstanceState, type SceneInstance,
} from "./collabSceneModel";
import "./AgentCollaborationSpace.css";

type State = "working" | "done" | "failed" | "waiting" | "stopped";
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const actionLabels: Record<Exclude<ActionKind, null>, string> = {
  planning: "规划调度", reading: "阅读材料", searching: "检索查证",
  analyzing: "分析审阅", tool: "调用工具", messaging: "整理输出",
};
const stateLabels: Record<InstanceState, string> = {
  waiting: "待命", working: "正在工作", reviewing: "接收审阅", done: "已完成", failed: "执行失败",
};
const avatarState = (state: InstanceState): State =>
  state === "reviewing" ? "working" : state === "waiting" ? "waiting" : state;
const NO_ACTION = () => {};

/** 拉取协作事件流：运行中游标轮询增量，终态一次全量；404 表示早于事件协议。 */
function useCollabEvents(runKind: "panel" | "admission", runId: string | undefined, pair: { candidateId: string; jdId: string } | undefined, live: boolean) {
  const [events, setEvents] = useState<CollabEvent[]>([]);
  const [missing, setMissing] = useState(false);
  const [ready, setReady] = useState(false);
  const latestSeq = useRef(-1);
  const stopped = useRef(false);

  useEffect(() => {
    stopped.current = false;
    setEvents([]);
    setMissing(false);
    setReady(false);
    latestSeq.current = -1;

    const pull = async (afterSeq: number) => {
      if (stopped.current) return;
      try {
        const data = runId
          ? await api.agentCollab.events(runKind, runId, afterSeq)
          : pair ? await api.agentCollab.eventsForPair(pair.candidateId, pair.jdId, afterSeq) : null;
        if (stopped.current || !data) return;
        if (data.events.length) {
          latestSeq.current = data.latest_seq;
          setEvents(prev => {
            const seen = new Set(prev.map(e => e.event_id));
            return [...prev, ...data.events.filter(e => !seen.has(e.event_id))];
          });
        } else if (afterSeq < 0) {
          latestSeq.current = data.latest_seq;
        }
        setReady(true);
      } catch (error) {
        if (String(error).includes("没有事件协议记录") || String(error).includes("运行不存在")) {
          setMissing(true);
          setReady(true);
        }
      }
    };

    void pull(-1);
    if (!live) return () => { stopped.current = true; };
    const timer = window.setInterval(() => {
      if (!document.hidden) void pull(latestSeq.current);
    }, 1500);
    return () => { stopped.current = true; window.clearInterval(timer); };
    // pair 按字段依赖：对象引用每次渲染都变，整对象进依赖会重建轮询
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKind, runId, pair?.candidateId, pair?.jdId, live]);

  return { events, missing, ready };
}

/** 二维工位：消费 agent-collab/v1 真实事件流；实时跟随与逐事件回放共用归约器。 */
export default function AgentCollaborationSpace({ runKind, runId, pair, status }: {
  runKind: "panel" | "admission";
  runId?: string;
  pair?: { candidateId: string; jdId: string };
  status: string;
}) {
  const { t } = useI18n();
  const live = !TERMINAL.has(status);
  const { events, missing, ready } = useCollabEvents(runKind, runId, pair, live);
  const [playCount, setPlayCount] = useState(events.length);
  const [playing, setPlaying] = useState(false);
  const [instant, setInstant] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [still, setStill] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [tab, setTab] = useState<"work" | "handoff">("work");
  const [followScroll, setFollowScroll] = useState(true);
  const [pulse, setPulse] = useState<{ key: string; source: string; target: string; dx: number; dy: number } | null>(null);
  const nodes = useRef(new Map<string, HTMLButtonElement>());
  const detailScroll = useRef<HTMLDivElement>(null);
  const seenExchange = useRef<string | null>(null);

  useEffect(() => { if (live) setPlayCount(events.length); }, [live, events.length]);

  const count = live ? events.length : Math.min(playCount, events.length);
  const visible = useMemo(() => events.slice(0, count), [events, count]);
  const scene: CollabScene = useMemo(() => reduceCollabEvents(visible), [visible]);
  const lastExchange = scene.exchanges.at(-1);
  const last = visible.at(-1);
  const autoId = lastExchange && !live ? lastExchange.receiver || lastExchange.sender
    : last?.event.type === "task.dispatched" ? last.event.receiver || last.instance_id
      : last?.instance_id || lastExchange?.sender || "";
  const ids = [...scene.instances.keys()];
  const known = new Set(ids);
  const selectedId = selected && known.has(selected) ? selected : follow ? autoId || ids[0] : ids[0];
  const selectedInstance = scene.instances.get(selectedId || "");
  const leadIds = ids.filter(id => id === "chair");
  const workerIds = ids.filter(id => id !== "chair");

  const seek = (value: number) => {
    setPlaying(false);
    setPulse(null);
    seenExchange.current = null;
    setInstant(true);
    setPlayCount(value);
    window.setTimeout(() => setInstant(false), 700);
  };
  const replay = () => {
    setInstant(true);
    setPlayCount(0);
    seenExchange.current = null;
    setPulse(null);
    setPlaying(true);
    window.setTimeout(() => setInstant(false), 700);
  };
  const select = (id: string) => { setSelected(id); setFollow(false); };

  useEffect(() => {
    if (!playing || live) return;
    if (count >= events.length) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setPlayCount(c => c + 1), 900);
    return () => window.clearTimeout(timer);
  }, [playing, live, count, events.length]);

  // 新交接触发靠近动作；回放定位不重播（seek 已清空 seenExchange 且暂停）
  const exchangeKey = lastExchange?.eventId || null;
  useEffect(() => {
    if (!exchangeKey || seenExchange.current === exchangeKey) return;
    const fresh = seenExchange.current === null && !instant;
    seenExchange.current = exchangeKey;
    if (!fresh || still || !live && !playing || !lastExchange) return;
    const from = nodes.current.get(lastExchange.sender)?.getBoundingClientRect();
    const to = nodes.current.get(lastExchange.receiver)?.getBoundingClientRect();
    if (!from || !to) return;
    setPulse({
      key: exchangeKey, source: lastExchange.sender, target: lastExchange.receiver,
      dx: (to.x + to.width / 2 - from.x - from.width / 2) * .55,
      dy: (to.y + to.height / 2 - from.y - from.height / 2) * .55,
    });
    const timer = window.setTimeout(() => setPulse(null), 1400);
    return () => window.clearTimeout(timer);
  // 仅在新交接时触发动作，普通轮询不重播
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchangeKey, still, live, playing, instant]);

  useEffect(() => { if (still || !live && !playing) setPulse(null); }, [still, live, playing]);
  useEffect(() => {
    if (followScroll && detailScroll.current) detailScroll.current.scrollTop = detailScroll.current.scrollHeight;
  }, [count, selectedId, followScroll, tab]);

  if (missing) {
    return <section className="acs-root" aria-label={t("协作空间")}>
      <div className="acs-empty"><Icon name="history" size={30} />
        <p>{t("该记录产生于事件协议启用之前")}</p>
        <span>{t("切换到「Agent 协作」查看普通协作记录")}</span></div>
    </section>;
  }
  if (!ready) {
    return <section className="acs-root" aria-label={t("协作空间")}>
      <div className="acs-empty"><p>{t("正在加载协作事件…")}</p></div>
    </section>;
  }

  const renderSeat = (instance: SceneInstance, lead = false) => {
    const state = instance.state;
    const receiving = pulse?.target === instance.id;
    const moving = pulse?.source === instance.id;
    return <button type="button" key={instance.id}
      ref={el => { if (el) nodes.current.set(instance.id, el); else nodes.current.delete(instance.id); }}
      className={lead ? "acs-seat acs-lead" : "acs-seat"} data-state={state} data-instant={instant}
      aria-pressed={selectedId === instance.id} onClick={() => select(instance.id)}
      aria-label={`${instanceName(instance)} · ${instance.id} · ${t(stateLabels[state])}`}>
      <span className="acs-seat-avatar" data-moving={moving} data-receiving={receiving}
        style={moving ? { "--acs-dx": pulse!.dx + "px", "--acs-dy": pulse!.dy + "px" } as CSSProperties : undefined}>
        <Avatar role={instance.role} state={avatarState(state)} still={still}
          gaze={moving ? Math.sign(pulse!.dx) * 4 : receiving ? -Math.sign(pulse?.dx || 1) * 4 : 0} />
      </span>
      <span className="acs-seat-info">
        <span className="acs-seat-title">{instanceName(instance)}</span>
        <span className="acs-seat-id">{instance.id}{instance.turn > 1 ? ` · ${t("第 {n} 轮", { n: instance.turn })}` : ""}</span>
        <span className="acs-seat-status"><i />{t(receiving ? "收到信息" : stateLabels[state])}</span>
      </span>
      {instance.actionKind && <span className="acs-action">{t(actionLabels[instance.actionKind])}</span>}
      <span className="acs-seat-task">{instance.action || instance.taskGoal || t("等待任务开始")}</span>
    </button>;
  };

  const workItems = selectedInstance ? [
    ...[...scene.tasks.values()].filter(task => task.instanceId === selectedInstance.id)
      .map(task => ({ kind: "task" as const, seq: 0, task })),
    ...scene.messages.filter(m => m.sender === selectedInstance.id)
      .map(m => ({ kind: "message" as const, seq: m.seq, message: m })),
    ...[...scene.tools.values()].filter(tool => tool.instanceId === selectedInstance.id)
      .map(tool => ({ kind: "tool" as const, seq: tool.seq, tool })),
  ].sort((a, b) => a.seq - b.seq) : [];
  const handoffs = scene.exchanges.filter(e => e.sender === selectedId || e.receiver === selectedId);
  const workingNames = [...scene.instances.values()].filter(i => i.state === "working" || i.state === "reviewing").map(instanceName);
  const overall = live ? status === "queued" ? t("排队中") : t("运行中")
    : scene.runState === "failed" ? t("运行失败") : scene.runState === "cancelled" ? t("已停止")
      : playing ? t("回放中") : count < events.length ? t("回放已暂停") : t("已完成");

  return <section className="acs-root" data-still={still} aria-label={t("协作空间")}>
    <header className="acs-header"><div><h2>{t("协作现场")}</h2><p>{t("看见任务如何推进，查看每一次信息交接")}</p></div>
      <span className="acs-run-status" data-live={live}><i />{overall}</span>
      <button type="button" className="acs-control" aria-pressed={still} onClick={() => setStill(!still)}><Icon name="activity" size={14} />{t("减少动效")}</button>
    </header>
    <div className="acs-layout">
      <div className="acs-overview">
        <div className="acs-now"><span>{t("当前工作")}</span><p>{workingNames.length ? workingNames.join(" · ") : t(live ? "等待下一条执行事件" : "查看已记录的工作过程")}</p></div>
        <div className="acs-stage">
          {leadIds.length > 0 && <div className="acs-leads">{leadIds.map(id => renderSeat(scene.instances.get(id)!, true))}</div>}
          {runKind === "admission" && <div className="acs-leads">
            <span className="acs-seat acs-lead" data-state="waiting">
              <span className="acs-seat-avatar"><Avatar state="waiting" system /></span>
              <span className="acs-seat-info"><span className="acs-seat-title">{t("系统调度")}</span>
                <span className="acs-seat-id">system</span>
                <span className="acs-seat-status"><i />{t("确定性编排，不是 Agent")}</span></span>
            </span>
          </div>}
          <div className="acs-team">{workerIds.map(id => renderSeat(scene.instances.get(id)!))}</div>
          {!ids.length && <div className="acs-empty"><Icon name="layers" size={28} /><p>{t("等待评估启动")}</p><span>{t("收到真实执行事件后，Agent 会出现在这里")}</span></div>}
        </div>
        <div className="acs-transfer">
          <div className="acs-section-label">{t("最近交接")}{lastExchange?.at && <time>{new Date(lastExchange.at).toLocaleTimeString()}</time>}</div>
          {lastExchange ? <button type="button" onClick={() => { select(lastExchange.sender); setTab("handoff"); }}>
            <span className="acs-transfer-route">{scene.instances.get(lastExchange.sender) ? instanceName(scene.instances.get(lastExchange.sender)!) : lastExchange.sender}<Icon name="arrow-right" size={16} />{scene.instances.get(lastExchange.receiver) ? instanceName(scene.instances.get(lastExchange.receiver)!) : lastExchange.receiver}</span>
            <span className="acs-transfer-text">{lastExchange.text}</span><span className="acs-transfer-link">{t("查看完整交接")}<Icon name="arrow-up-right" size={14} /></span>
          </button> : <p>{t("等待第一次任务派发")}</p>}
        </div>
      </div>
      <aside className="acs-detail">
        {selectedInstance ? <>
          <div className="acs-detail-head">
            <Avatar role={selectedInstance.role} state={avatarState(selectedInstance.state)} small still={still} />
            <div><h3>{instanceName(selectedInstance)}</h3>
              <p>{selectedInstance.id} · {t(stateLabels[selectedInstance.state])}</p></div>
            <button type="button" className="acs-control" aria-pressed={follow} onClick={() => setFollow(!follow)}>{t(follow ? "跟随中" : "已固定")}</button>
          </div>
          <div className="acs-detail-nav"><div role="tablist" aria-label={t("工作详情")}>
            <button type="button" role="tab" aria-selected={tab === "work"} onClick={() => setTab("work")}>{t("工作记录")}</button>
            <button type="button" role="tab" aria-selected={tab === "handoff"} onClick={() => setTab("handoff")}>{t("交接记录")}<span>{handoffs.length}</span></button>
          </div><button type="button" className="acs-scroll-control" onClick={() => setFollowScroll(!followScroll)} aria-pressed={followScroll}>{t(followScroll ? "暂停跟随" : "跟随最新")}</button></div>
          <div className="acs-detail-scroll" ref={detailScroll} onWheel={() => setFollowScroll(false)} onTouchMove={() => setFollowScroll(false)}>
            {tab === "work" ? <>
              {selectedInstance.taskGoal && <div className="acs-brief"><span>{t("当前任务")}{selectedInstance.turn > 1 ? ` · ${t("第 {n} 轮", { n: selectedInstance.turn })}` : ""}</span><p>{selectedInstance.taskGoal}</p>{selectedInstance.note && <p>{t("续派指令")}：{selectedInstance.note}</p>}</div>}
              {workItems.map(item => {
                if (item.kind === "tool") {
                  const tool = item.tool;
                  return <ToolCallCard key={tool.eventId} segment={{ type: "tool", call_id: tool.callId, tool: tool.tool,
                    label: tool.tool, args_summary: tool.argsSummary,
                    status: tool.status === "running" ? undefined : tool.status === "error" ? "error" : "ok",
                    summary: tool.summary || t("运行中"), detail: tool.argsSummary }} />;
                }
                if (item.kind === "message") {
                  const message: ChatMessage = { id: item.message.eventId, conversation_id: "collab", role: "assistant",
                    content: { segments: [{ type: "text", text: item.message.text }] }, citations: [],
                    status: "completed", created_at: item.message.at || "" };
                  return <article className="acs-record" key={item.message.eventId}>
                    <div className="acs-record-meta"><span>{t("公开工作输出")}</span>{item.message.at && <time>{new Date(item.message.at).toLocaleTimeString()}</time>}</div>
                    <AssistantMessage message={message} busy={false} onDecide={NO_ACTION} hideAvatar />
                  </article>;
                }
                return <div className="acs-brief" key={item.task.key}>
                  <span>{t("任务")} · {t("第 {n} 轮", { n: item.task.turn })} · {t(item.task.state === "completed" ? "已完成" : item.task.state === "failed" ? "失败" : item.task.state === "started" ? "已开始" : "已派发")}</span>
                  <p>{item.task.goal}</p>
                </div>;
              })}
              {!workItems.length && !selectedInstance.taskGoal && <div className="acs-empty"><p>{t("尚未收到工作记录")}</p></div>}
            </> : <>
              {handoffs.map(e => <article className="acs-record acs-handoff" key={e.eventId}>
                <div className="acs-record-meta">
                  <span>{scene.instances.get(e.sender) ? instanceName(scene.instances.get(e.sender)!) : e.sender} → {scene.instances.get(e.receiver) ? instanceName(scene.instances.get(e.receiver)!) : e.receiver}</span>
                  <span>{t(e.kind === "dispatch" ? "派工" : e.succeeded ? "结论回传" : "失败回传")}</span>
                  {e.at && <time>{new Date(e.at).toLocaleTimeString()}</time>}
                </div>
                <p className="acs-handoff-text">{e.text}</p>
                {e.artifactId && <p className="acs-data-note">{t("产物")}：{e.artifactId}</p>}
                {!live && <button type="button" className="acs-control" onClick={() => seek(visible.findIndex(v => v.event_id === e.eventId) + 1)}>{t("回看此处")}</button>}
              </article>)}
              {!handoffs.length && <div className="acs-empty"><p>{t("尚无交接记录")}</p></div>}
            </>}
          </div>
          <p className="acs-data-note">{t("按真实事件更新 · 非模拟打字")}</p>
        </> : <div className="acs-empty"><p>{t("选择 Agent 查看工作详情")}</p></div>}
      </aside>
    </div>
    {!live && <footer className="acs-replay">
      <button type="button" className="acs-control" onClick={() => { if (!playing && count >= events.length) replay(); else setPlaying(!playing); }}><Icon name={playing ? "pause" : "play"} size={15} />{t(playing ? "暂停" : "播放")}</button>
      <button type="button" className="acs-control" onClick={replay}>{t("重播")}</button>
      <input type="range" min={0} max={events.length} value={count} onChange={e => seek(Number(e.target.value))} aria-label={t("回放进度")} />
      <span>{count} / {events.length} {t("条事件")}</span>
    </footer>}
  </section>;
}
