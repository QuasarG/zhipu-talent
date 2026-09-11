import type { CollabEvent } from "@/lib/types";
import AgentGroupChat from "@/features/admission/AgentGroupChat";
import { useTalentCollaboration } from "./useTalentCollaboration";

/** 人才评估协作群聊：能力映射、任务评分与总审作为群成员在同一会话推进；
 *  sample 注入合成事件仅供本地预览，不打评估接口。 */
export default function TalentCollaboration(props: {
  runId?: string;
  pair?: { candidateId: string; jdId: string };
  status: string;
  sample?: CollabEvent[];
}) {
  const live = !["completed", "failed", "cancelled"].includes(props.status);
  const { events, loading, error, retry } = useTalentCollaboration(props.runId, props.pair, live, props.sample);
  return (
    <AgentGroupChat
      runKind="admission"
      status={props.status}
      events={events}
      live={live}
      loading={loading}
      error={error}
      onRetry={retry}
    />
  );
}
