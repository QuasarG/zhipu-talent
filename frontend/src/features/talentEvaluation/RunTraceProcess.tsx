import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, ChatSegment } from "@/lib/types";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import AssistantMessage from "@/features/chat/AssistantMessage";
import ToolCallCard from "@/features/chat/ToolCallCard";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { nestTraceSegments } from "@/features/chat/traceSegments";

const EMPTY: ChatSegment[] = [];

type SpawnSegment = Extract<ChatSegment, { type: "spawn" }>;

/** 评估过程（奖学金同款）：一条 assistant 消息 = 全部过程叙事。
 *  运行中轮询活跃运行增量渲染；完成后直接渲染落库的 trace。无重放控件。
 *  点击 spawn 行在右侧展开该子 agent 的工作面板。 */
export default function RunTraceProcess({ segments = EMPTY, live = false, runId, status }: {
  segments?: ChatSegment[];
  live?: boolean;
  runId?: string;
  status?: string;
}) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [trace, setTrace] = useState<ChatSegment[]>(segments);
  const [openSpawnId, setOpenSpawnId] = useState<string | null>(null);

  const applyTrace = (next: ChatSegment[]) => {
    if (next.length) setTrace(next);
  };

  useEffect(() => { setTrace(segments); }, [segments]);

  // 运行中轮询活跃运行：run_trace 每个事件落库，增量可见
  useEffect(() => {
    if (!live || !runId) return;
    const timer = window.setInterval(async () => {
      try {
        const runs = await api.interviewAssessments.active();
        const current = (runs as Array<{ id: string; run_trace?: ChatSegment[] }>).find(run => run.id === runId);
        if (current?.run_trace) applyTrace(current.run_trace);
      } catch {
        // 网络抖动下一轮再试
      }
    }, 2500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, runId]);

  const nested = useMemo(() => nestTraceSegments(trace), [trace]);
  const message: ChatMessage = {
    id: `run-${runId ?? "process"}`,
    conversation_id: "",
    role: "assistant",
    content: { segments: nested },
    citations: [],
    status: live ? "running" : "completed",
    created_at: "",
  };
  const busy = live || status === "running";

  useEffect(() => {
    const el = containerRef.current;
    if (el && stick.current) el.scrollTo(0, el.scrollHeight);
  }, [nested.length]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const openSpawn = openSpawnId
    ? (nested.find(segment => segment.type === "spawn" && segment.spawn_id === openSpawnId) as SpawnSegment | undefined)
    : undefined;

  return (
    <div className="flex h-full min-h-0">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-4xl px-5 py-4">
          <div className="mb-5">
            <h2 className="text-title-lg">{t("评估过程")}</h2>
            <p className="mt-1 text-body-sm text-on-surface-variant">
              {t("主 agent 的工作记录：派出哪些子 agent、核对了什么、如何下结论")}
            </p>
          </div>
          {nested.length === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
              <Icon name="forum" size={30} />
              <p className="text-body-sm">{t(live ? "等待主 Agent 开始工作" : "这次评估没有可展示的协作过程")}</p>
            </div>
          ) : (
            <AssistantMessage
              message={message}
              busy={busy}
              onDecide={() => {}}
              onSpawnOpen={segment => setOpenSpawnId(segment.spawn_id)}
            />
          )}
        </div>
      </div>

      {openSpawn && (
        <aside className="flex w-[360px] shrink-0 flex-col border-l border-outline-variant bg-surface-lowest">
          <header className="flex shrink-0 items-center gap-2 border-b border-outline-variant px-4 py-3">
            <Icon name="smart_toy" size={17} className="text-on-surface-variant" />
            <span className="min-w-0 flex-1 truncate text-body-sm font-bold text-on-surface">{openSpawn.agent}</span>
            <StatusChip tone={openSpawn.status === "failed" ? "error" : openSpawn.status === "running" ? "primary" : "success"} variant="dot">
              {openSpawn.status === "running" ? t("工作中") : openSpawn.status === "failed" ? t("失败") : t("已完成")}
            </StatusChip>
            <button type="button" aria-label={t("关闭")} title={t("关闭")}
              onClick={() => setOpenSpawnId(null)}
              className="flex size-7 shrink-0 items-center justify-center rounded-full text-on-surface-variant hover:bg-surface-low hover:text-on-surface">
              <Icon name="close" size={15} />
            </button>
          </header>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {openSpawn.prompt && (
              <section>
                <p className="text-label text-on-surface-variant">{t("派工 prompt")}</p>
                <p className="mt-1 whitespace-pre-wrap text-body-sm leading-6 text-on-surface">{openSpawn.prompt}</p>
              </section>
            )}
            {openSpawn.summary && (
              <section>
                <p className="text-label text-on-surface-variant">{t("结论")}</p>
                <p className="mt-1 text-body-sm leading-6 text-on-surface">{openSpawn.summary}</p>
              </section>
            )}
            {(openSpawn.children ?? []).map((child, index) => (
              child.type === "tool"
                ? <ToolCallCard key={child.call_id || index} segment={child} />
                : child.type === "text"
                  ? <p key={index} className="whitespace-pre-wrap text-body-sm leading-6 text-on-surface">{child.text}</p>
                  : null
            ))}
            {!(openSpawn.children ?? []).length && !openSpawn.summary && !openSpawn.prompt && (
              <p className="text-label text-on-surface-variant">{t("尚未记录工作内容")}</p>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
