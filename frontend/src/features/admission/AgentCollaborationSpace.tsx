import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { CollabEvent } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import AgentGroupChat from "./AgentGroupChat";

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

/** 协作群聊：消费 agent-collab/v1 真实事件流；实时跟随与逐事件回放共用同一转写模型。 */
export default function AgentCollaborationSpace({ runKind, runId, pair, status }: {
  runKind: "panel" | "admission";
  runId?: string;
  pair?: { candidateId: string; jdId: string };
  status: string;
}) {
  const { t } = useI18n();
  const live = !["completed", "failed", "cancelled"].includes(status);
  const { events, missing, ready } = useCollabEvents(runKind, runId, pair, live);

  if (missing) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-title-sm font-bold text-on-surface">{t("该记录产生于事件协议启用之前")}</p>
        <p className="text-body-sm text-on-surface-variant">{t("切换到「活动流」查看普通协作记录")}</p>
      </div>
    );
  }
  if (!ready) {
    return <div className="flex h-full items-center justify-center text-body-sm text-on-surface-variant">{t("正在加载协作消息…")}</div>;
  }
  return <AgentGroupChat runKind={runKind} status={status} events={events} live={live} />;
}
