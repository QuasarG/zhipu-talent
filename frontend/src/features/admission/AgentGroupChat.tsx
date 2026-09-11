import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, CollabEvent } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import AssistantMessage from "@/features/chat/AssistantMessage";
import ToolCallCard from "@/features/chat/ToolCallCard";
import { digestMarkdown, reduceCollabChat, type CollabEntry, type CollabSpawn } from "./collabChatModel";
import "./AgentGroupChat.css";

const asMessage = (id: string, text: string): ChatMessage => ({
  id,
  conversation_id: "collab",
  role: "assistant",
  content: { segments: [{ type: "text", text }] },
  citations: [],
  status: "completed",
  created_at: "",
});

const oneLine = (text: string, max = 90): string => {
  const plain = text.replace(/```[\s\S]*?```/g, "代码块").replace(/[#*`>]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max)}…` : plain;
};

function LeadAvatar({ small = false }: { small?: boolean }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md bg-primary font-bold text-on-primary",
        small ? "h-6 w-6 text-label" : "h-8 w-8 text-body-sm"
      )}
      aria-hidden="true"
    >
      主
    </span>
  );
}

/** 主席的发言：问答同款 assistant 消息（markdown）。 */
function LeadSpeech({ entry }: { entry: Extract<CollabEntry, { kind: "lead"; variant: "speech" }> }) {
  const { t } = useI18n();
  return (
    <div className="chat-enter flex gap-3">
      <LeadAvatar />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-body-sm font-bold text-on-surface">{t("主席")}</span>
          {entry.at && <time className="text-label tabular-nums text-on-surface-variant">{new Date(entry.at).toLocaleTimeString()}</time>}
        </div>
        <AssistantMessage message={asMessage(entry.key, entry.text)} hideAvatar busy={false} onDecide={() => {}} />
      </div>
    </div>
  );
}

/** 主席亲自调用的工具：问答同款工具卡。 */
function LeadTool({ entry }: { entry: Extract<CollabEntry, { kind: "lead"; variant: "tool" }> }) {
  return (
    <div className="chat-enter pl-11">
      <ToolCallCard segment={entry.tool} />
    </div>
  );
}

/** 子 agent 内联行：默认一行摘要，点击展开它的完整工作（派工目标/工具/说明/结论）。 */
function SpawnRow({ spawn, expanded, onToggle }: { spawn: CollabSpawn; expanded: boolean; onToggle: () => void }) {
  const { t } = useI18n();
  const running = spawn.state === "running";
  const failed = spawn.state === "failed";
  const latest = spawn.result?.text ?? spawn.notes.at(-1) ?? spawn.goal;
  return (
    <div className="chat-enter">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="state-layer flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left"
      >
        <Icon name="smart_toy" size={17} className={cn("shrink-0", running ? "text-primary" : "text-on-surface-variant")} />
        <span className="shrink-0 text-body-sm font-bold text-on-surface">{spawn.name}</span>
        <span className="min-w-0 flex-1 truncate text-body-sm text-on-surface-variant">{oneLine(latest)}</span>
        {running ? (
          <span className="collab-typing inline-flex shrink-0 items-center gap-1.5 text-label text-primary">
            <span className="collab-typing-dots" aria-hidden="true"><i /><i /><i /></span>
            {t("工作中")}
          </span>
        ) : (
          <StatusChip tone={failed ? "error" : "success"} variant="dot" className="shrink-0">
            {failed ? t("失败") : t("已完成")}
          </StatusChip>
        )}
        <Icon
          name="expand_more"
          size={16}
          className={cn("shrink-0 text-on-surface-variant transition-transform duration-200 ease-emphasized", expanded && "rotate-180")}
        />
      </button>
      {expanded && (
        <div className="ml-6 space-y-2 border-l-2 border-outline-variant pb-2 pl-3 pt-1">
          {spawn.goal && <p className="text-label leading-5 text-on-surface-variant">{t("派工")}：{spawn.goal}</p>}
          {spawn.tools.map(segment => (
            <ToolCallCard key={segment.call_id} segment={segment} />
          ))}
          {spawn.notes.map((text, index) => (
            <AssistantMessage key={`${spawn.key}-note-${index}`} message={asMessage(`${spawn.key}-note-${index}`, text)} hideAvatar busy={false} onDecide={() => {}} />
          ))}
          {spawn.result && (
            <div className={cn("rounded-md border px-3 py-2", spawn.result.succeeded ? "border-success/30 bg-success-container/20" : "border-error/40 bg-error-container/30")}>
              <p className="mb-1 flex items-center gap-1.5 text-label font-bold text-on-surface-variant">
                <Icon name={spawn.result.succeeded ? "check_circle" : "error"} size={14} className={spawn.result.succeeded ? "text-success" : "text-error"} />
                {t("结论回传")}
              </p>
              <AssistantMessage
                message={asMessage(`${spawn.key}-result`, digestMarkdown(spawn.result.text))}
                hideAvatar busy={false} onDecide={() => {}}
              />
            </div>
          )}
          {!spawn.goal && !spawn.tools.length && !spawn.notes.length && !spawn.result && (
            <p className="text-label text-on-surface-variant">{t("尚未记录工作内容")}</p>
          )}
        </div>
      )}
    </div>
  );
}

/** 协作对话：主 agent（主席/系统编排）的对话流，子 agent 由它 spawn——
 *  子活动默认折叠为一行，点击展开完整工作。只渲染 agent-collab/v1 真实事件。 */
export default function AgentGroupChat({ runKind, status, events, live, loading, error, onRetry }: {
  runKind: "panel" | "admission";
  status: string;
  events: CollabEvent[];
  live: boolean;
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  const listRef = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  // 回放：cursor=null 表示跟随最新；非 live 时可按消息步进回看
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const count = live || cursor === null ? events.length : Math.min(cursor, events.length);
  const visible = useMemo(() => events.slice(0, count), [events, count]);
  const room = useMemo(() => reduceCollabChat(visible), [visible]);
  const totalEntries = useMemo(() => reduceCollabChat(events).entries.length, [events]);
  const spawnByKey = useMemo(() => new Map(room.spawns.map(spawn => [spawn.key, spawn])), [room.spawns]);
  const entryBounds = useMemo(() => {
    const indexByEvent = new Map(events.map((e, index) => [e.event_id, index + 1]));
    return room.entries.map(entry => {
      const birth = "birthEvent" in entry ? entry.birthEvent : entry.key;
      return indexByEvent.get(birth) ?? count;
    });
  }, [events, room.entries, count]);

  useEffect(() => {
    if (live) { setCursor(null); setPlaying(false); }
  }, [live]);
  useEffect(() => {
    if (!playing || live) return;
    if (count >= events.length) { setPlaying(false); return; }
    const next = entryBounds.find(bound => bound > count) ?? events.length;
    const timer = window.setTimeout(() => setCursor(next), 1200);
    return () => window.clearTimeout(timer);
  }, [playing, live, count, events.length, entryBounds]);

  useEffect(() => {
    const el = listRef.current;
    if (el && following) el.scrollTo(0, el.scrollHeight);
  }, [room.entries.length, following]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    setFollowing(bottom);
  };
  const backToLatest = () => {
    setFollowing(true);
    setCursor(null);
    setPlaying(false);
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  };
  const toggleSpawn = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const workingSpawns = room.spawns.filter(spawn => spawn.state === "running");
  const overall = live
    ? status === "queued" ? t("排队中") : t("运行中")
    : room.runState === "failed" ? t("运行失败")
      : room.runState === "cancelled" ? t("已停止")
        : playing ? t("回放中") : count < events.length ? t("回放已暂停") : t("已完成");
  const taskChips = [
    { label: "执行中", value: room.tasks.active, tone: "primary" as const },
    { label: "待处理", value: room.tasks.pending, tone: "warning" as const },
    { label: "已完成", value: room.tasks.done, tone: "success" as const },
    { label: "失败", value: room.tasks.failed, tone: "error" as const },
  ].filter(chip => chip.value > 0);

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label={t("协作对话")}>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-outline-variant px-4 py-3">
        <span className="flex items-center gap-2 text-title-sm font-bold text-on-surface">
          <Icon name="forum" size={18} className="text-on-surface-variant" />
          {t(runKind === "panel" ? "评审团协作" : "准入评估协作")}
        </span>
        <StatusChip tone={live ? "primary" : room.runState === "failed" ? "error" : "success"}
          variant={live ? "filled" : "dot"} icon={live ? "sync" : undefined}>
          {overall}
        </StatusChip>
        <div className="ml-auto flex items-center gap-1.5">
          {taskChips.map(chip => (
            <StatusChip key={chip.label} tone={chip.tone}>{t(chip.label)} {chip.value}</StatusChip>
          ))}
        </div>
      </header>

      {error && (
        <div className="mx-4 mt-3 flex items-center gap-3 rounded-md border border-error/40 bg-error-container/30 px-3 py-2" role="alert">
          <span className="text-body-sm text-error">{t(error)}</span>
          {onRetry && <button type="button" className="text-label font-bold text-error underline-offset-2 hover:underline" onClick={onRetry}>{t("重试")}</button>}
        </div>
      )}

      <div
        ref={listRef}
        onScroll={handleScroll}
        role="log"
        aria-live={live ? "polite" : "off"}
        className="relative min-h-0 flex-1 overflow-y-auto px-4 py-5"
      >
        {loading ? (
          <div className="flex h-full items-center justify-center text-body-sm text-on-surface-variant">{t("正在加载协作消息…")}</div>
        ) : room.entries.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Icon name="forum" size={36} className="text-on-surface-variant" />
            <p className="text-title-sm font-bold text-on-surface">{t(live ? "等待主 Agent 开始工作" : "这次评估没有可展示的协作过程")}</p>
            <p className="text-body-sm text-on-surface-variant">{t(live ? "主 Agent 派发子 Agent 后，对话会出现在这里" : "已有评估报告不受影响")}</p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            {room.entries.map(entry => {
              if (entry.kind === "system") {
                return (
                  <div key={entry.key} className="chat-enter flex justify-center">
                    <span className={cn(
                      "rounded-full border px-3 py-1 text-label",
                      entry.tone === "error" ? "border-error/40 bg-error-container/40 text-error"
                        : "border-outline-variant bg-surface-low text-on-surface-variant"
                    )}>
                      {t(entry.text)}
                      {entry.at && <span className="ml-2 tabular-nums opacity-70">{new Date(entry.at).toLocaleTimeString()}</span>}
                    </span>
                  </div>
                );
              }
              if (entry.kind === "lead" && entry.variant === "planning") {
                return (
                  <div key={entry.key} className="chat-enter flex items-center gap-2 px-2">
                    <LeadAvatar small />
                    <span className="text-body-sm text-on-surface-variant">
                      {t("第 {n} 轮规划", { n: entry.round })}
                      {entry.contextCount ? ` · ${t("已收到 {n} 份结论", { n: entry.contextCount })}` : ""}
                    </span>
                    {entry.at && <time className="text-label tabular-nums text-on-surface-variant opacity-70">{new Date(entry.at).toLocaleTimeString()}</time>}
                  </div>
                );
              }
              if (entry.kind === "lead" && entry.variant === "tool") {
                return <LeadTool key={entry.key} entry={entry} />;
              }
              if (entry.kind === "lead") return <LeadSpeech key={entry.key} entry={entry} />;
              const spawn = spawnByKey.get(entry.spawnKey);
              if (!spawn) return null;
              return (
                <SpawnRow
                  key={entry.key}
                  spawn={spawn}
                  expanded={expanded.has(spawn.key)}
                  onToggle={() => toggleSpawn(spawn.key)}
                />
              );
            })}
            {live && workingSpawns.length > 0 && (
              <div className="chat-enter flex flex-wrap items-center gap-2 pl-2" role="status" aria-label={t("正在输入")}>
                {workingSpawns.map(spawn => (
                  <span key={spawn.key} className="collab-typing inline-flex items-center gap-1.5 rounded-full bg-surface-low px-2.5 py-1 text-label text-on-surface-variant">
                    <span className="collab-typing-dots" aria-hidden="true"><i /><i /><i /></span>
                    {spawn.name} {t("工作中")}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {live && !following && room.entries.length > 0 && (
          <button type="button" onClick={backToLatest}
            className="sticky bottom-2 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-outline-variant bg-surface px-3 py-1.5 text-label font-medium text-primary shadow-sm">
            <Icon name="arrow_downward" size={15} />
            {t("回到最新")}
          </button>
        )}
      </div>

      {!live && room.entries.length > 0 && (
        <footer className="flex flex-wrap items-center gap-3 border-t border-outline-variant px-4 py-2.5">
          <Button type="button" variant="tonal" icon={playing ? "pause" : "play"}
            onClick={() => {
              if (playing) { setPlaying(false); return; }
              if (count >= events.length) setCursor(0);
              setPlaying(true);
            }}>
            {t(playing ? "暂停回放" : "回看协作")}
          </Button>
          <Button type="button" variant="text" icon="replay" onClick={() => { setPlaying(true); setCursor(0); }}>
            {t("从头重播")}
          </Button>
          <input
            aria-label={t("协作回放进度")}
            type="range" min={0} max={events.length} value={count}
            onChange={e => { setPlaying(false); setCursor(Number(e.target.value)); }}
            className="min-w-40 flex-1"
          />
          <span className="text-label tabular-nums text-on-surface-variant">
            {room.entries.length} / {totalEntries} {t("条消息")}
          </span>
        </footer>
      )}
    </section>
  );
}
