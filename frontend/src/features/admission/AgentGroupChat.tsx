import { useEffect, useMemo, useRef, useState } from "react";
import type { CollabEvent } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import AssistantMessage from "@/features/chat/AssistantMessage";
import { reduceCollabChat, type ChatMember, type ChatMemberState, type CollabChatEntry } from "./collabChatModel";
import "./AgentGroupChat.css";

const ROLE_GLYPH: Record<string, string> = {
  chair: "主", verify: "证", deep_read: "读", jd_match: "岗", cross_check: "仲",
  generic: "评", mapper: "映", task_scorer: "评", reviewer: "审",
};

const memberStateLabel: Record<ChatMemberState, string> = {
  waiting: "待命", working: "正在工作", done: "已完成", failed: "执行失败",
};

function ChatAvatar({ member, stopped }: { member: ChatMember; stopped: boolean }) {
  const glyph = ROLE_GLYPH[member.role] || (member.role === "system" || member.id === "system" ? "系" : "协");
  const isChair = member.id === "chair" || member.role === "chair";
  const isSystem = member.role === "system" || member.id === "system";
  const state: ChatMemberState = stopped && member.state === "working" ? "done" : member.state;
  return (
    <span className="relative shrink-0" aria-hidden="true">
      <span
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-md text-body-sm font-bold",
          isChair ? "bg-primary text-on-primary"
            : isSystem ? "bg-surface-high text-on-surface-variant"
              : "bg-secondary-container text-on-secondary-container"
        )}
      >
        {glyph}
      </span>
      <span
        className={cn(
          "absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface-lowest",
          state === "working" ? "bg-primary" : state === "done" ? "bg-success"
            : state === "failed" ? "bg-error" : "bg-outline"
        )}
      />
    </span>
  );
}

function EntryRow({ entry, member, stopped }: { entry: CollabChatEntry; member?: ChatMember; stopped: boolean }) {
  const badgeTone = entry.badgeTone ?? "neutral";
  return (
    <div className="chat-enter flex gap-3">
      <ChatAvatar member={member ?? { id: entry.senderId, role: entry.senderId === "chair" ? "chair" : entry.senderId, name: entry.senderName, state: "waiting" }} stopped={stopped} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-body-sm font-bold text-on-surface">{entry.senderName}</span>
          {entry.mentionName && (
            <span className="flex items-center gap-0.5 text-label text-on-surface-variant">
              <Icon name="arrow_right_alt" size={14} />
              <span className="font-medium text-primary">@{entry.mentionName}</span>
            </span>
          )}
          {entry.badge && (
            <StatusChip tone={badgeTone} variant={badgeTone === "error" ? "filled" : "dot"}
              icon={badgeTone === "error" ? "error" : undefined}>
              {entry.badge}
            </StatusChip>
          )}
          {entry.at && (
            <time className="text-label tabular-nums text-on-surface-variant">
              {new Date(entry.at).toLocaleTimeString()}
            </time>
          )}
        </div>
        <AssistantMessage message={entry.message} hideAvatar busy={false} onDecide={() => {}} />
      </div>
    </div>
  );
}

/** 协作群聊：主席与评审员作为群成员在同一个会话里派工、汇报、调用工具。
 *  只渲染 agent-collab/v1 真实事件；消息体复用问答的 assistant 消息渲染。 */
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
  const stickToBottomRef = useRef(true);
  const [following, setFollowing] = useState(true);
  // 回放：cursor=null 表示跟随最新；非 live 时可用进度条逐条回看
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  const count = live || cursor === null ? events.length : Math.min(cursor, events.length);
  const visible = useMemo(() => events.slice(0, count), [events, count]);
  const room = useMemo(() => reduceCollabChat(visible), [visible]);
  const totalEntries = useMemo(() => reduceCollabChat(events).entries.length, [events]);
  const memberById = useMemo(() => new Map(room.members.map(member => [member.id, member])), [room.members]);
  // 回放按“消息”步进：记录每条 entry 对应的事件数边界
  const entryBounds = useMemo(() => {
    const indexByEvent = new Map(events.map((e, index) => [e.event_id, index + 1]));
    return room.entries.map(entry => indexByEvent.get(entry.key) ?? count);
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
    stickToBottomRef.current = bottom;
    setFollowing(bottom);
  };
  const backToLatest = () => {
    stickToBottomRef.current = true;
    setFollowing(true);
    setCursor(null);
    setPlaying(false);
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  };

  const stopped = !live;
  const workingMembers = room.members.filter(member => member.state === "working");
  const rosterLimit = 6;
  const roster = room.members.slice(0, rosterLimit);
  const rosterOverflow = room.members.slice(rosterLimit);
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
    <section className="flex h-full min-h-0 flex-col" aria-label={t("协作群聊")}>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-outline-variant px-4 py-3">
        <span className="flex items-center gap-2 text-title-sm font-bold text-on-surface">
          <Icon name="forum" size={18} className="text-on-surface-variant" />
          {t(runKind === "panel" ? "评审团群聊" : "准入评估群聊")}
        </span>
        <StatusChip tone={live ? "primary" : room.runState === "failed" ? "error" : "success"}
          variant={live ? "filled" : "dot"} icon={live ? "sync" : undefined}>
          {overall}
        </StatusChip>
        <div className="flex flex-wrap items-center gap-1.5" aria-label={t("群成员")}>
          {roster.map(member => (
            <span key={member.id}
              title={t(memberStateLabel[stopped && member.state === "working" ? "done" : member.state])}
              className="flex items-center gap-1.5 rounded-full border border-outline-variant py-0.5 pl-1 pr-2.5">
              <ChatAvatar member={member} stopped={stopped} />
              <span className="text-label font-medium text-on-surface">{member.name}</span>
            </span>
          ))}
          {rosterOverflow.length > 0 && (
            <span
              className="rounded-full border border-outline-variant px-2.5 py-1 text-label font-medium text-on-surface-variant"
              title={rosterOverflow.map(member => member.name).join("、")}
            >
              +{rosterOverflow.length}
            </span>
          )}
        </div>
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
            <p className="text-title-sm font-bold text-on-surface">{t(live ? "等待第一位 Agent 发言" : "这次评估没有可展示的协作消息")}</p>
            <p className="text-body-sm text-on-surface-variant">{t(live ? "主席派工后，对话会出现在这里" : "已有评估报告不受影响")}</p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5">
            {room.entries.map(entry => {
              if (entry.kind === "system") {
                return (
                  <div key={entry.key} className="chat-enter flex justify-center">
                    <span className={cn(
                      "rounded-full border px-3 py-1 text-label",
                      entry.tone === "error" ? "border-error/40 bg-error-container/40 text-error"
                        : "border-outline-variant bg-surface-low text-on-surface-variant"
                    )}>
                      {t(entry.text || "")}
                      {entry.at && <span className="ml-2 tabular-nums opacity-70">{new Date(entry.at).toLocaleTimeString()}</span>}
                    </span>
                  </div>
                );
              }
              if (entry.kind === "planning") {
                return (
                  <div key={entry.key} className="chat-enter flex justify-center">
                    <span className="rounded-full border border-outline-variant bg-surface-low px-3 py-1 text-label text-on-surface-variant">
                      {t(entry.senderName)} · {t("第 {n} 轮规划", { n: entry.round ?? 1 })}
                      {entry.contextCount ? ` · ${t("已收到 {n} 份结论", { n: entry.contextCount })}` : ""}
                      {entry.at && <span className="ml-2 tabular-nums opacity-70">{new Date(entry.at).toLocaleTimeString()}</span>}
                    </span>
                  </div>
                );
              }
              return <EntryRow key={entry.key} entry={entry} member={memberById.get(entry.senderId)} stopped={stopped} />;
            })}
            {live && workingMembers.length > 0 && (
              <div className="chat-enter flex flex-wrap items-center gap-2 pl-11" role="status" aria-label={t("正在输入")}>
                {workingMembers.map(member => (
                  <span key={member.id} className="collab-typing inline-flex items-center gap-1.5 rounded-full bg-surface-low px-2.5 py-1 text-label text-on-surface-variant">
                    <span className="collab-typing-dots" aria-hidden="true"><i /><i /><i /></span>
                    {member.name} {t("正在工作")}
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
