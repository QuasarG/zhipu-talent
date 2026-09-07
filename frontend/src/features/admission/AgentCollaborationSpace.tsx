import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import { activeAgents, kinds, roleNames, type Activity } from "./agentActivityModel";
import "./AgentCollaborationSpace.css";

type AgentState = "working" | "receiving" | "done" | "idle";
const stateLabels: Record<AgentState, string> = { working: "正在工作", receiving: "收到信息", done: "已完成", idle: "待命" };
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

interface SpaceAgent {
  id: string; role: string; mission: string | null; goal: string | null;
  shape: number; tone: number; state: AgentState; x: number; y: number;
}

/** 从活动流推导空间状态：加入顺序定席位、最新交接定动效，输入幂等（trace 全量重放安全）。 */
function deriveSpace(events: Activity[], running: boolean, terminal: boolean) {
  const order: string[] = [];
  const roleOf = new Map<string, string>();
  const goalOf = new Map<string, string>();
  const missionOf = new Map<string, string>();
  const lastIncoming = new Map<string, Activity>();
  const exchanges: Activity[] = [];
  for (const e of events) {
    roleOf.set(e.agent, e.role);
    if (e.goal) goalOf.set(e.agent, e.goal);
    if (e.mission) missionOf.set(e.agent, e.mission);
    for (const id of [e.agent, e.target]) if (id && !order.includes(id)) order.push(id);
    if ((e.kind === "dispatch" || e.kind === "handoff") && e.target && e.agent !== e.target) {
      exchanges.push(e);
      lastIncoming.set(e.target, e);
    }
  }
  const working = new Set(activeAgents(events, running).map(e => e.agent));
  const workers = order.filter(id => id !== "system");
  const agents: SpaceAgent[] = order.map(id => {
    let state: AgentState = "idle";
    if (working.has(id)) state = "working";
    else if (terminal) state = "done";
    else if (lastIncoming.has(id)) state = "receiving";
    let shape = 0;
    for (const c of id) shape = (shape * 31 + c.charCodeAt(0)) % 997;
    const seat = workers.indexOf(id);
    const angle = Math.PI / 2 + (Math.max(seat, 0) / Math.max(workers.length, 1)) * Math.PI * 2;
    return {
      id, role: roleOf.get(id) || "system", mission: missionOf.get(id) ?? null, goal: goalOf.get(id) ?? null,
      shape: shape % 6, tone: id === "system" ? 0 : 14 + Math.min(Math.max(seat, 0), 5) * 13,
      state, x: id === "system" ? 50 : 50 + 36 * Math.cos(angle), y: id === "system" ? 9 : 56 + 34 * Math.sin(angle),
    };
  });
  return { agents, exchanges };
}

function Avatar({ agent, state, pulse }: { agent: SpaceAgent; state: AgentState; pulse?: boolean }) {
  const tone = agent.id === "system" ? "var(--color-primary)" : agent.tone >= 100
    ? "var(--color-surface)"
    : `color-mix(in oklab, var(--color-primary), var(--color-surface) ${agent.tone}%)`;
  return <span className="acs-avatar" data-shape={agent.id === "system" ? undefined : agent.shape}
    data-state={state} data-pulse={pulse} style={{ "--acs-tone": tone } as CSSProperties} aria-hidden="true">
    {agent.id === "system" ? <Icon name="layers" size={26} /> : <span className="acs-body"><span className="acs-eyes"><i /><i /></span></span>}
  </span>;
}

/** Agent 协作的空间视图：席位、状态姿态与交接动效，详情为所选实例的活动记录。 */
export default function AgentCollaborationSpace({ events, status }: { events: Activity[]; status: string }) {
  const { t } = useI18n();
  const live = !TERMINAL.has(status);
  const [cursor, setCursor] = useState(events.length);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [still, setStill] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [pulse, setPulse] = useState<{ id: string; agent: string; target: string; dx: number; dy: number } | null>(null);
  const [followScroll, setFollowScroll] = useState(true);
  const seenExchange = useRef<string | null>(null);
  const detailScroll = useRef<HTMLDivElement>(null);

  useEffect(() => { if (live) setCursor(events.length); }, [live, events.length]);

  const visible = useMemo(() => events.slice(0, live ? events.length : cursor), [events, live, cursor]);
  const space = useMemo(() => deriveSpace(visible, live || playing, !live && cursor >= events.length),
    [visible, live, playing, cursor, events.length]);

  useEffect(() => {
    const ex = space.exchanges.at(-1);
    if (!ex || ex.id === seenExchange.current) return;
    seenExchange.current = ex.id;
    if (still) return;
    const from = space.agents.find(a => a.id === ex.agent);
    const to = space.agents.find(a => a.id === ex.target);
    if (!from || !to) return;
    setPulse({ id: ex.id, agent: ex.agent, target: ex.target!, dx: to.x - from.x, dy: to.y - from.y });
  }, [space, still]);

  useEffect(() => {
    if (!follow) return;
    const last = visible.at(-1);
    if (!last) return;
    const next = last.target && (last.kind === "dispatch" || last.kind === "handoff") ? last.target : last.agent;
    if (next) setSelected(next);
  }, [visible, follow]);

  useEffect(() => {
    if (!playing || live) return;
    if (cursor >= events.length) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setCursor(c => c + 1), 650);
    return () => window.clearTimeout(timer);
  }, [playing, live, cursor, events.length]);

  useEffect(() => {
    if (followScroll && detailScroll.current) detailScroll.current.scrollTop = detailScroll.current.scrollHeight;
  }, [visible.length, selected, followScroll]);

  const selectedId = selected && space.agents.some(a => a.id === selected) ? selected : space.agents[0]?.id;
  const agent = space.agents.find(a => a.id === selectedId);
  const nameOf = (id: string) => {
    const a = space.agents.find(x => x.id === id);
    return t(roleNames[a?.role || "system"] || a?.role || id);
  };
  const agentEvents = visible.filter(e => e.agent === selectedId || e.target === selectedId);
  const agentExchanges = space.exchanges.filter(e => e.agent === selectedId || e.target === selectedId);
  const currentExchange = space.exchanges.at(-1);
  const chip = "rounded px-2 py-1 text-label hover:bg-surface-low focus-visible:outline-2 focus-visible:outline-primary cursor-pointer";

  return (
    <section className="flex h-full min-h-0 flex-col bg-surface-lowest" aria-label={t("协作空间")}>
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-outline-variant px-4 py-2.5">
        <h2 className="text-title-lg font-semibold">{t("协作空间")}</h2>
        {live ? (
          <span className="flex items-center gap-2 text-label text-on-surface-variant">
            <span className="h-2 w-2 rounded-full bg-primary motion-safe:animate-pulse" />
            {t(status === "queued" ? "排队中" : "运行中")}
          </span>
        ) : (
          <span className="flex items-center gap-2" role="group" aria-label={t("回放控制")}>
            <button type="button" className={chip} aria-pressed={playing}
              onClick={() => { if (!playing && cursor >= events.length) setCursor(0); setPlaying(!playing); }}>
              <Icon name={playing ? "pause" : "play"} size={14} className="mr-1 inline-block align-[-2px]" />
              {t(playing ? "暂停" : "播放")}
            </button>
            <button type="button" className={chip} onClick={() => { setCursor(0); setPlaying(true); }}>{t("重播")}</button>
            <input type="range" min={0} max={events.length} value={live ? events.length : cursor}
              onChange={e => { setCursor(Number(e.target.value)); setPlaying(false); }}
              aria-label={t("回放进度")} className="w-32 accent-[var(--color-primary)]" />
            <span className="text-label tabular-nums text-on-surface-variant">{visible.length} / {events.length}</span>
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          <button type="button" className={chip} aria-pressed={follow} onClick={() => setFollow(!follow)}>
            {t(follow ? "跟随最新 Agent" : "已固定所选 Agent")}
          </button>
          <button type="button" className={chip} aria-pressed={still} onClick={() => setStill(!still)}>{t("减少动效")}</button>
        </span>
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className={cn("acs-stage m-4 mt-3", still && "acs-still")}>
            <div className="acs-meeting" aria-hidden="true" />
            {space.agents.map(a => (
              <button type="button" key={a.id} className="acs-agent" data-state={a.state}
                style={{ left: `${a.x}%`, top: `${a.y}%` }} aria-pressed={a.id === selectedId}
                aria-label={`${nameOf(a.id)} · ${t(stateLabels[a.state])}`}
                onClick={() => { setSelected(a.id); setFollow(false); }}>
                <span key={pulse?.id || "rest"} className={cn("acs-slot", pulse?.agent === a.id && "approach")}
                  style={pulse?.agent === a.id
                    ? ({ "--acs-dx": pulse.dx, "--acs-dy": pulse.dy } as CSSProperties) : undefined}>
                  <Avatar agent={a} state={a.state} pulse={pulse?.target === a.id} />
                  <span className="acs-agent-name">{nameOf(a.id)}</span>
                  <span className="acs-agent-state">{t(stateLabels[a.state])}</span>
                </span>
              </button>
            ))}
            {!space.agents.length && <p className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-body-sm text-on-surface-variant">{t("等待评估启动")}</p>}
          </div>
          <div className="flex min-h-[52px] shrink-0 items-center gap-2 border-t border-outline-variant px-4 py-2.5 text-body-sm">
            {currentExchange ? (
              <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left cursor-pointer"
                onClick={() => { setSelected(currentExchange.agent); setFollow(false); }}>
                <Icon name="arrow-right" size={16} className="shrink-0 text-primary" />
                <span className="min-w-0 truncate">
                  <span className="font-semibold">{nameOf(currentExchange.agent)} → {nameOf(currentExchange.target!)}</span>
                  <span className="ml-2 text-on-surface-variant">{currentExchange.text}</span>
                </span>
              </button>
            ) : <p className="text-on-surface-variant">{t(live ? "等待第一次任务派发" : "尚未收到协作记录")}</p>}
          </div>
        </div>
        <aside className="flex min-h-0 w-full shrink-0 flex-col border-t border-outline-variant lg:w-96 lg:border-t-0 lg:border-l">
          {agent && (
            <>
              <div className="flex shrink-0 items-center gap-3 border-b border-outline-variant px-4 py-3">
                <Avatar agent={agent} state={agent.state} />
                <div className="min-w-0">
                  <p className="truncate text-title font-semibold">{nameOf(agent.id)}</p>
                  <p className="truncate text-label text-on-surface-variant">
                    {t(stateLabels[agent.state])}{agent.goal ? ` · ${agent.goal}` : ""}
                  </p>
                </div>
              </div>
              <div ref={detailScroll} className="min-h-0 flex-1 overflow-y-auto px-4 admission-panel-scrollbar"
                onScroll={e => {
                  const el = e.currentTarget;
                  setFollowScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
                }}>
                {agentEvents.map(e => (
                  <article key={e.id} className="border-b border-outline-variant py-3">
                    <div className="flex flex-wrap items-center gap-x-2 text-label">
                      <span className="font-semibold">{t(roleNames[e.role] || e.role)}</span>
                      {e.target && <><Icon name="arrow-right" size={12} /><span>{nameOf(e.target)}</span></>}
                      <span className="text-on-surface-variant">· {t(kinds[e.kind] || e.kind)}</span>
                      {e.at && <time className="ml-auto tabular-nums text-on-surface-variant">{new Date(e.at).toLocaleTimeString()}</time>}
                    </div>
                    <p className={cn("mt-1.5 whitespace-pre-wrap break-words text-body-sm leading-relaxed",
                      e.status === "failed" ? "text-error" : "text-on-surface")}>{e.text}</p>
                    {e.detail && Object.keys(e.detail).length > 0 && (
                      <details className="mt-1.5">
                        <summary className="cursor-pointer rounded py-0.5 text-label font-medium text-primary focus-visible:outline-2 focus-visible:outline-primary">{t("查看输入、输出与依据")}</summary>
                        <div className="mt-1.5 space-y-2 border-t border-outline-variant pt-2">
                          {Object.entries(e.detail).map(([key, value]) => (
                            <div key={key}>
                              <p className="text-label font-semibold">{key}</p>
                              <pre className="mt-0.5 max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans text-body-sm leading-relaxed text-on-surface-variant">
                                {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </article>
                ))}
                {!agentEvents.length && <p className="py-8 text-center text-body-sm text-on-surface-variant">{t("尚未收到协作记录")}</p>}
                <p className="pb-1 pt-4 text-label font-semibold">{t("交接记录")}</p>
                {agentExchanges.map(e => (
                  <button type="button" key={`x${e.id}`}
                    className="block w-full border-b border-outline-variant py-2 text-left hover:bg-surface-low focus-visible:outline-2 focus-visible:outline-primary cursor-pointer"
                    onClick={() => { setSelected(e.agent); if (!live) { setCursor(Number(e.id) + 1); setPlaying(false); } }}>
                    <span className="text-label text-on-surface-variant">{nameOf(e.agent)} → {nameOf(e.target!)}</span>
                    <p className="mt-0.5 text-body-sm">{e.text}</p>
                  </button>
                ))}
                {!agentExchanges.length && <p className="py-2 text-body-sm text-on-surface-variant">{t("尚无交接记录")}</p>}
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
