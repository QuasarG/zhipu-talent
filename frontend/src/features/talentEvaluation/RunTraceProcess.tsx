import { useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatSegment } from "@/lib/types";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import AssistantMessage from "@/features/chat/AssistantMessage";
import Icon from "@/components/ui/Icon";

const EMPTY: ChatSegment[] = [];

/** 准入评估过程（奖学金同款）：一条 assistant 消息 = 全部过程叙事。
 *  运行中轮询 run 的 trace 增量渲染；完成后直接渲染落库的 trace。无重放控件。 */
export default function RunTraceProcess({ runId, runTrace, status }: {
  runId?: string;
  runTrace?: ChatSegment[];
  status: string;
}) {
  const { t } = useI18n();
  const live = !["completed", "failed", "cancelled"].includes(status);
  const [segments, setSegments] = useState<ChatSegment[]>(runTrace ?? EMPTY);
  const containerRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => { setSegments(runTrace ?? EMPTY); }, [runTrace]);

  useEffect(() => {
    if (!live || !runId) return;
    const timer = window.setInterval(async () => {
      try {
        const data = await api.interviewAssessments.trace(runId);
        setSegments((data.run_trace ?? []) as ChatSegment[]);
      } catch {
        // 网络抖动下一轮再试
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [live, runId]);

  useEffect(() => {
    const el = containerRef.current;
    if (el && stick.current) el.scrollTo(0, el.scrollHeight);
  }, [segments.length]);

  const message: ChatMessage = {
    id: `run-${runId ?? "pair"}`,
    conversation_id: "",
    role: "assistant",
    content: { segments },
    citations: [],
    status: live ? "running" : "completed",
    created_at: "",
  };

  return (
    <div
      ref={containerRef}
      onScroll={e => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      }}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div className="mx-auto w-full max-w-4xl px-5 py-4">
        <div className="mb-5">
          <h2 className="text-title-lg">{t("评估过程")}</h2>
          <p className="mt-1 text-body-sm text-on-surface-variant">
            {t("主 agent 的工作记录：派出哪些子 agent、核对了什么、如何下结论")}
          </p>
        </div>
        {segments.length === 0 ? (
          <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
            <Icon name="forum" size={30} />
            <p className="text-body-sm">{t(live ? "等待主 Agent 开始工作" : "这次评估没有可展示的协作过程")}</p>
          </div>
        ) : (
          <AssistantMessage message={message} busy={live} onDecide={() => {}} />
        )}
      </div>
    </div>
  );
}
