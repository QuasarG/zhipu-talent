import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Icon from "@/components/ui/Icon";
import Avatar from "./GrokAgentAvatar";
import AssistantMessage from "@/features/chat/AssistantMessage";
import ToolCallCard from "@/features/chat/ToolCallCard";
import type { ChatMessage } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { activeAgents, kinds, roleNames, type Activity } from "./agentActivityModel";
import "./AgentCollaborationSpace.css";

type State = "working" | "done" | "failed" | "waiting" | "stopped";
const labels: Record<State, string> = { working: "正在工作", done: "已完成", failed: "执行失败", waiting: "待命", stopped: "已停止" };
const terminal = new Set(["completed", "failed", "cancelled"]);
const isExchange = (e: Activity) => !!e.target && e.target !== e.agent && ["dispatch", "handoff"].includes(e.kind);
const identity = (e: Activity) => [e.id, e.agent, e.target, e.at, e.kind, e.text].join("|");
const NO_ACTION = () => {};


function EventContent({ event, t }: { event: Activity; t: (key: string) => string }) {
  const message: ChatMessage = { id: event.id, conversation_id: "assessment", role: "assistant",
    content: { segments: [{ type: "text", text: event.text }] }, citations: [],
    status: "completed", created_at: event.at || "" };
  return <>
    <AssistantMessage message={message} busy={false} onDecide={NO_ACTION} hideAvatar />
    {event.detail && Object.keys(event.detail).length > 0 && <details className="acs-evidence">
      <summary>{t("查看输入、输出与依据")}</summary>
      {Object.entries(event.detail).map(([key, value]) => <div key={key}><strong>{key}</strong><pre>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre></div>)}
    </details>}
  </>;
}

/** 固定工作区 + 真实工作记录；回放按事件推进，不模拟模型 token 输出。 */
export default function AgentCollaborationSpace({ events, status }: { events: Activity[]; status: string }) {
  const { t } = useI18n();
  const live = !terminal.has(status);
  const [cursor, setCursor] = useState(events.length);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [still, setStill] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [tab, setTab] = useState<"work" | "handoff">("work");
  const [followScroll, setFollowScroll] = useState(true);
  const [pulse, setPulse] = useState<{ key: string; source: string; target: string; dx: number; dy: number } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const nodes = useRef(new Map<string, HTMLButtonElement>());
  const detailScroll = useRef<HTMLDivElement>(null);
  const seen = useRef<string | null>(null);
  const initialized = useRef(false);
  const previousLive = useRef(live);
  const count = live ? events.length : Math.min(cursor, events.length);

  useEffect(() => {
    if (live || previousLive.current) setCursor(events.length);
    previousLive.current = live;
  }, [live, events.length]);
  const visible = useMemo(() => events.slice(0, count), [events, count]);
  const allIds = useMemo(() => [...new Set(events.flatMap(e => [e.agent, ...(e.target ? [e.target] : [])]))], [events]);
  const known = new Set(visible.flatMap(e => [e.agent, ...(e.target ? [e.target] : [])]));
  const ids = allIds.filter(id => known.has(id));
  const meta = new Map(events.map(e => [e.agent, e]));
  const latest = new Map(visible.map(e => [e.agent, e]));
  const working = new Set(activeAgents(visible, status === "running" || !live && count < events.length).map(e => e.agent));
  const exchanges = visible.filter(isExchange);
  const lastExchange = exchanges.at(-1);
  const last = visible.at(-1);
  const autoId = last?.target && isExchange(last) ? last.target : last?.agent;
  const selectedId = follow ? autoId || ids[0] : selected && known.has(selected) ? selected : ids[0];
  const leadIds = ids.filter(id => id === "chair" || id === "system");
  const workerIds = ids.filter(id => id !== "chair" && id !== "system");
  const nameOf = (id: string) => t(roleNames[meta.get(id)?.role || ""] || id);
  const stateOf = (id: string): State => {
    const e = latest.get(id);
    if (e?.status === "failed" || e?.status === "error" || e?.kind === "error") return "failed";
    if (working.has(id)) return "working";
    if (e && (["completed", "done", "skipped"].includes(e.status) || e.kind === "handoff")) return "done";
    if (status === "cancelled" || status === "failed") return "stopped";
    return "waiting";
  };
  const select = (id: string) => { setSelected(id); setFollow(false); setHighlight(null); };
  const chooseHandoff = (e: Activity) => { select(e.agent); setTab("handoff"); setHighlight(identity(e)); setFollowScroll(false); };
  const seek = (value: number) => { setCursor(value); setPlaying(false); setPulse(null); seen.current = null; };
  const replay = () => { initialized.current = true; seen.current = null; setPulse(null); setCursor(0); setPlaying(true); };

  useEffect(() => {
    if (!playing || live) return;
    if (cursor >= events.length) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setCursor(c => c + 1), 1000);
    return () => window.clearTimeout(timer);
  }, [playing, live, cursor, events.length]);

  const exchangeKey = lastExchange ? identity(lastExchange) : null;
  useEffect(() => {
    if (!initialized.current) { initialized.current = true; seen.current = exchangeKey; return; }
    if (!exchangeKey || seen.current === exchangeKey) return;
    seen.current = exchangeKey;
    if (still || !live && !playing || !lastExchange) return;
    const from = nodes.current.get(lastExchange.agent)?.getBoundingClientRect();
    const to = nodes.current.get(lastExchange.target!)?.getBoundingClientRect();
    if (!from || !to) return;
    setPulse({ key: exchangeKey, source: lastExchange.agent, target: lastExchange.target!,
      dx: (to.x + to.width / 2 - from.x - from.width / 2) * .55,
      dy: (to.y + to.height / 2 - from.y - from.height / 2) * .55 });
    const timer = window.setTimeout(() => setPulse(null), 1400);
    return () => window.clearTimeout(timer);
  // 只在新交接时触发，普通轮询不重播动作。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchangeKey, still, live, playing]);
  useEffect(() => { if (still || !live && !playing) setPulse(null); }, [still, live, playing]);
  useEffect(() => {
    if (followScroll && detailScroll.current) detailScroll.current.scrollTop = detailScroll.current.scrollHeight;
  }, [count, selectedId, followScroll, tab]);
  useEffect(() => {
    if (!highlight || !detailScroll.current) return;
    const element = [...detailScroll.current.querySelectorAll<HTMLElement>("[data-exchange]")].find(el => el.dataset.exchange === highlight);
    if (element) detailScroll.current.scrollTop = element.offsetTop - detailScroll.current.offsetTop - 12;
  }, [highlight, tab]);

  const renderAgent = (id: string, lead = false) => {
    const state = stateOf(id);
    const event = latest.get(id);
    const receiving = pulse?.target === id;
    const moving = pulse?.source === id && id !== "system";
    return <button type="button" key={id} ref={el => { if (el) nodes.current.set(id, el); else nodes.current.delete(id); }}
      className={lead ? "acs-seat acs-lead" : "acs-seat"} data-state={state} aria-pressed={selectedId === id}
      onClick={() => select(id)} aria-label={nameOf(id) + " · " + id + " · " + t(labels[state])}>
      <span className="acs-seat-avatar" data-moving={moving} data-receiving={receiving}
        style={moving ? { "--acs-dx": pulse.dx + "px", "--acs-dy": pulse.dy + "px" } as CSSProperties : undefined}>
        <Avatar role={meta.get(id)?.role} state={state} system={id === "system"} still={still}
          gaze={moving ? Math.sign(pulse.dx) * 4 : receiving ? -Math.sign(pulse?.dx || 1) * 4 : 0} />
      </span>
      <span className="acs-seat-info"><span className="acs-seat-title">{nameOf(id)}</span>
        <span className="acs-seat-id">{id === "system" ? t("确定性调度") : meta.get(id)?.mission || id}</span>
        <span className="acs-seat-status"><i />{t(receiving ? "收到信息" : labels[state])}</span>
      </span>
      <span className="acs-seat-task">{event?.text || t("等待任务开始")}</span>
    </button>;
  };
  const workEvents = visible.filter(e => e.agent === selectedId && !isExchange(e));
  const handoffs = exchanges.filter(e => e.agent === selectedId || e.target === selectedId);
  const completedTools = new Map(workEvents.filter(e => e.kind === "tool_result" && e.callId).map(e => [e.callId!, e]));
  const action = latest.get(selectedId || "");
  const runningNames = ids.filter(id => working.has(id)).map(nameOf);
  const overall = live ? status === "queued" ? "排队中" : "运行中" : playing ? "回放中" : count < events.length ? "回放已暂停" : status === "failed" ? "运行失败" : status === "cancelled" ? "已停止" : "已完成";

  return <section className="acs-root" data-still={still} aria-label={t("协作空间")}>
    <header className="acs-header"><div><h2>{t("协作现场")}</h2><p>{t("看见任务如何推进，查看每一次信息交接")}</p></div>
      <span className="acs-run-status" data-live={status === "running"}><i />{t(overall)}</span>
      <button type="button" className="acs-control" aria-pressed={still} onClick={() => setStill(!still)}><Icon name="activity" size={14} />{t("减少动效")}</button>
    </header>
    <div className="acs-layout">
      <div className="acs-overview">
        <div className="acs-now"><span>{t("当前工作")}</span><p>{runningNames.length ? runningNames.join(" · ") : t(live ? "等待下一条执行事件" : "查看已记录的工作过程")}</p></div>
        <div className="acs-stage">
          {leadIds.length > 0 && <div className="acs-leads">{leadIds.map(id => renderAgent(id, true))}</div>}
          <div className="acs-team">{workerIds.map(id => renderAgent(id))}</div>
          {!ids.length && <div className="acs-empty"><Icon name="layers" size={28} /><p>{t("等待评估启动")}</p><span>{t("收到真实执行事件后，Agent 会出现在这里")}</span></div>}
        </div>
        <div className="acs-transfer">
          <div className="acs-section-label">{t("最近交接")}{lastExchange?.at && <time>{new Date(lastExchange.at).toLocaleTimeString()}</time>}</div>
          {lastExchange ? <button type="button" onClick={() => chooseHandoff(lastExchange)}>
            <span className="acs-transfer-route">{nameOf(lastExchange.agent)}<Icon name="arrow-right" size={16} />{nameOf(lastExchange.target!)}</span>
            <span className="acs-transfer-text">{lastExchange.text}</span><span className="acs-transfer-link">{t("查看完整交接")}<Icon name="arrow-up-right" size={14} /></span>
          </button> : <p>{t("等待第一次任务派发")}</p>}
        </div>
      </div>
      <aside className="acs-detail">
        {selectedId ? <>
          <div className="acs-detail-head"><Avatar role={meta.get(selectedId)?.role} state={stateOf(selectedId)} system={selectedId === "system"} small still={still} />
            <div><h3>{nameOf(selectedId)}</h3><p>{meta.get(selectedId)?.mission || selectedId} · {t(labels[stateOf(selectedId)])}</p></div>
            <button type="button" className="acs-control" aria-pressed={follow} onClick={() => setFollow(!follow)}>{t(follow ? "跟随中" : "已固定")}</button>
          </div>
          <div className="acs-detail-nav"><div role="tablist" aria-label={t("工作详情")}>
            <button type="button" role="tab" aria-selected={tab === "work"} onClick={() => setTab("work")}>{t("工作记录")}</button>
            <button type="button" role="tab" aria-selected={tab === "handoff"} onClick={() => setTab("handoff")}>{t("交接记录")}<span>{handoffs.length}</span></button>
          </div><button type="button" className="acs-scroll-control" onClick={() => setFollowScroll(!followScroll)} aria-pressed={followScroll}>{t(followScroll ? "暂停跟随" : "跟随最新")}</button></div>
          <div className="acs-detail-scroll" ref={detailScroll} onWheel={() => setFollowScroll(false)} onTouchMove={() => setFollowScroll(false)}>
            {tab === "work" ? <>
              <div className="acs-brief"><span>{t("当前任务与动作")}</span><p>{action?.goal || meta.get(selectedId)?.goal || action?.text || t("等待任务开始")}</p></div>
              {workEvents.map(e => {
                if (e.kind === "tool_result" && e.callId && workEvents.some(x => x.kind === "tool_call" && x.callId === e.callId)) return null;
                if (e.kind === "tool_call" && e.callId) {
                  const result = completedTools.get(e.callId);
                  return <ToolCallCard key={e.id} segment={{ type: "tool", call_id: e.callId, tool: e.tool || t("工具调用"), label: e.text,
                    args_summary: JSON.stringify(e.detail || {}), status: result ? ["failed", "error"].includes(result.status) ? "error" : "ok" : !live && count === events.length ? "error" : undefined,
                    summary: result?.text || t("未记录工具返回"), detail: result ? JSON.stringify(result.detail || {}) : JSON.stringify(e.detail || {}) }} />;
                }
                return <article className="acs-record" key={e.id} data-failed={["failed", "error"].includes(e.status)}>
                  <div className="acs-record-meta"><span>{t(kinds[e.kind] || e.kind)}</span>{e.at && <time>{new Date(e.at).toLocaleTimeString()}</time>}</div>
                  <EventContent event={e} t={t} />
                  {e.kind === "legacy" && <p className="acs-legacy">{t("历史记录未保存收发对象，不推断交接关系")}</p>}
                </article>;
              })}
              {!workEvents.length && <div className="acs-empty"><p>{t("尚未收到工作记录")}</p></div>}
            </> : handoffs.map(e => <article className="acs-record acs-handoff" key={identity(e)} data-exchange={identity(e)} data-highlight={highlight === identity(e)}>
              <div className="acs-record-meta"><span>{nameOf(e.agent)} → {nameOf(e.target!)}</span><span>{t(kinds[e.kind] || e.kind)}</span></div>
              <EventContent event={e} t={t} />
              {!live && <button type="button" className="acs-control" onClick={() => { seek(events.indexOf(e) + 1); setFollow(false); }}>{t("回看此处")}</button>}
            </article>)}
            {tab === "handoff" && !handoffs.length && <div className="acs-empty"><p>{t("尚无交接记录")}</p></div>}
          </div>
          <p className="acs-data-note">{t("按真实事件更新 · 非模拟打字")}</p>
        </> : <div className="acs-empty"><p>{t("选择 Agent 查看工作详情")}</p></div>}
      </aside>
    </div>
    {!live && <footer className="acs-replay"><button type="button" className="acs-control" onClick={() => { if (!playing && count >= events.length) replay(); else setPlaying(!playing); }}><Icon name={playing ? "pause" : "play"} size={15} />{t(playing ? "暂停" : "播放")}</button>
      <button type="button" className="acs-control" onClick={replay}>{t("重播")}</button>
      <input type="range" min={0} max={events.length} value={count} onChange={e => seek(Number(e.target.value))} aria-label={t("回放进度")} />
      <span>{count} / {events.length} {t("条事件")}</span>
    </footer>}
  </section>;
}
