import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CollabEvent } from "@/lib/types";

export function useTalentCollaboration(runId: string | undefined, pair: { candidateId: string; jdId: string } | undefined, live: boolean, sample?: CollabEvent[]) {
  const [events, setEvents] = useState<CollabEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const candidateId = pair?.candidateId;
  const jdId = pair?.jdId;
  useEffect(() => {
    if (sample) { setEvents(sample); setLoading(false); setError(""); return; }
    let cancelled = false;
    let cursor = -1;
    let resolvedRunId = runId;
    let timer: ReturnType<typeof setTimeout>;
    setEvents([]); setLoading(true); setError("");
    const pull = async () => {
      try {
        let more = true;
        while (more && !cancelled) {
          const data = resolvedRunId ? await api.agentCollab.events("admission", resolvedRunId, cursor)
            : candidateId && jdId ? await api.agentCollab.eventsForPair(candidateId, jdId, cursor) : null;
          if (cancelled) return;
          if (!data) throw new Error("未找到本次评估");
          if ("run_id" in data && typeof data.run_id === "string") resolvedRunId = data.run_id;
          const page = data.events;
          if (page.length) {
            cursor = Math.max(cursor, ...page.map(e => e.seq));
            setEvents(previous => {
              const merged = new Map(previous.map(e => [e.event_id, e]));
              for (const event of page) merged.set(event.event_id, event);
              return [...merged.values()].sort((a, b) => a.seq - b.seq);
            });
          }
          more = page.length > 0 && cursor < data.latest_seq;
        }
        setError("");
      } catch { if (!cancelled) setError("协作过程暂时无法加载"); }
      finally {
        if (!cancelled) {
          setLoading(false);
          if (live) timer = setTimeout(() => { void pull(); }, document.hidden ? 5000 : 1500);
        }
      }
    };
    void pull();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [runId, candidateId, jdId, live, sample, attempt]);
  return { events, loading, error, retry: () => setAttempt(n => n + 1) };
}
