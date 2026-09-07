import type { PanelTraceEvent } from "@/lib/types";
import AgentWorkbench from "@/features/admission/AgentWorkbench";
import { panelActivities } from "@/features/admission/agentActivityModel";

export default function PanelTimeline({ trace, evaluating, status }: { trace: PanelTraceEvent[]; evaluating: boolean; status?: string }) {
  return <AgentWorkbench events={panelActivities(trace)} status={status || (evaluating ? "running" : "completed")} mode="panel" />;
}
