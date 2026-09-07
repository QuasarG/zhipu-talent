import { useState } from "react";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { useI18n } from "@/lib/i18n";
import type { InterviewAssessmentRun } from "@/lib/types";
import AgentWorkbench from "./AgentWorkbench";
import AgentCollaborationSpace from "./AgentCollaborationSpace";
import { admissionActivities } from "./agentActivityModel";

/** 运行/回放共用的协作视图：活动流（默认）与协作空间（席位化动效）同源切换。 */
export default function EvaluationActivityViews({ run }: { run: InterviewAssessmentRun }) {
  const { t } = useI18n();
  const [view, setView] = useState<"timeline" | "space">("timeline");
  const events = admissionActivities(run.run_trace || []);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center border-b border-outline-variant px-4 py-2">
        <SegmentedButtons
          options={[
            { value: "timeline", label: t("活动流"), icon: "activity" },
            { value: "space", label: t("协作空间"), icon: "layers" },
          ]}
          value={view}
          onChange={setView}
        />
      </div>
      <div className="min-h-0 flex-1">
        {view === "timeline"
          ? <AgentWorkbench key={run.id} events={events} status={run.status} mode="admission" />
          : <AgentCollaborationSpace key={run.id} events={events} status={run.status} />}
      </div>
    </div>
  );
}
