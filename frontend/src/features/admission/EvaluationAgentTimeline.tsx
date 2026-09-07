import type { InterviewAssessmentRun } from "@/lib/types";
import AgentWorkbench from "./AgentWorkbench";
import { admissionActivities } from "./agentActivityModel";

export default function EvaluationAgentTimeline({ run }: { run: InterviewAssessmentRun; compact?: boolean }) {
  return <AgentWorkbench key={run.id} events={admissionActivities(run.run_trace || [])} status={run.status} mode="admission" />;
}
