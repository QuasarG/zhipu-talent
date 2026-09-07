import { useMemo, useState } from "react";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import type { PanelTraceEvent } from "@/lib/types";

/**
 * 评审团（panel）评估过程视图：主席条 + mission 卡片流 + 确定性裁决行。
 * 数据来自 evaluation_run.panel_trace（record_node_event 全量落库的事件轨迹）。
 */

type MissionType = "verify" | "deep_read" | "jd_match" | "cross_check" | "generic";

const TYPE_META: Record<MissionType, { label: string; icon: string; chip: string }> = {
  verify: { label: "查证", icon: "fact_check", chip: "bg-secondary-container text-on-secondary-container" },
  deep_read: { label: "深读", icon: "menu_book", chip: "bg-primary-container text-on-primary-container" },
  jd_match: { label: "岗位对照", icon: "work", chip: "bg-tertiary-container text-on-tertiary-container" },
  cross_check: { label: "仲裁", icon: "balance", chip: "bg-error-container text-on-error-container" },
  generic: { label: "通用", icon: "search", chip: "bg-surface-high text-on-surface-variant" },
};

interface MissionView {
  id: string;
  type: MissionType;
  goal: string;
  status: "running" | "done" | "failed";
  activities: Array<{ ts: string | null; message: string; status: string }>;
}

interface PanelViewModel {
  dossierMessage: string;
  materialDone: boolean;
  chairMessage: string;
  chairDone: boolean;
  missions: MissionView[];
  guardMessage: string;
  formatterMessage: string;
  leadRunning: boolean;
}

function deriveModel(trace: PanelTraceEvent[]): PanelViewModel {
  const model: PanelViewModel = {
    dossierMessage: "",
    materialDone: false,
    chairMessage: "",
    chairDone: false,
    missions: [],
    guardMessage: "",
    formatterMessage: "",
    leadRunning: false,
  };
  const byId = new Map<string, MissionView>();
  for (const event of trace) {
    if (event.node === "material_desk") {
      model.dossierMessage = event.message || model.dossierMessage;
      if (event.status === "done") model.materialDone = true;
      continue;
    }
    if (event.node === "decision_guard") {
      model.guardMessage = event.message;
      continue;
    }
    if (event.node === "result_formatter") {
      model.formatterMessage = event.message;
      continue;
    }
    if (event.node !== "panel_lead") continue;
    if (event.mission_id) {
      let mission = byId.get(event.mission_id);
      if (!mission) {
        mission = {
          id: event.mission_id,
          type: (event.mission_type as MissionType) || "generic",
          goal: event.mission_goal || event.message,
          status: "running",
          activities: [],
        };
        byId.set(event.mission_id, mission);
        model.missions.push(mission);
      }
      if (event.mission_goal) mission.goal = event.mission_goal;
      mission.activities.push({ ts: event.ts, message: event.message, status: event.status });
      if (event.mission_status) mission.status = event.mission_status;
      if (/失败/.test(event.message)) mission.status = "failed";
      model.leadRunning = mission.status === "running" || model.leadRunning;
    } else {
      // 主席自身的动作（收队/收工等）
      model.chairMessage = event.message;
      if (/收队|收工/.test(event.message)) model.chairDone = true;
      model.leadRunning = !model.chairDone;
    }
  }
  model.leadRunning = model.leadRunning || (model.missions.some((m) => m.status === "running") && !model.chairDone);
  return model;
}

function StageDots({ model, evaluating }: { model: PanelViewModel; evaluating: boolean }) {
  const { t } = useI18n();
  const stages: Array<{ label: string; state: "done" | "running" | "pending" }> = [
    { label: t("材料整备"), state: model.materialDone ? "done" : evaluating ? "running" : "pending" },
    {
      label: t("评审团评审"),
      state: model.chairDone ? "done" : model.materialDone ? "running" : "pending",
    },
    {
      label: t("主席合成"),
      state: model.guardMessage ? "done" : model.chairDone ? "running" : "pending",
    },
    { label: t("硬门槛裁决"), state: model.guardMessage ? "done" : "pending" },
    { label: t("报告生成"), state: model.formatterMessage ? "done" : "pending" },
  ];
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {stages.map((stage, index) => (
        <span key={stage.label} className="flex items-center gap-1.5">
          {index > 0 && <span className="w-4 h-px bg-outline-variant" />}
          <span
            className={cn(
              "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label",
              stage.state === "done" && "bg-primary-container text-on-primary-container",
              stage.state === "running" && "bg-secondary-container text-on-secondary-container",
              stage.state === "pending" && "text-on-surface-variant",
            )}
          >
            {stage.state === "done" && <Icon name="check" size={12} />}
            {stage.state === "running" && <Icon name="sync" size={12} className="animate-spin" />}
            {stage.label}
          </span>
        </span>
      ))}
    </div>
  );
}

function MissionCard({ mission, defaultExpanded }: { mission: MissionView; defaultExpanded: boolean }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const meta = TYPE_META[mission.type] || TYPE_META.generic;
  const running = mission.status === "running";
  const failed = mission.status === "failed";
  const visible = expanded ? mission.activities : mission.activities.slice(-1);

  return (
    <div
      className={cn(
        "rounded-xl border bg-surface-low overflow-hidden transition-colors",
        running ? "border-primary" : failed ? "border-error/60" : "border-outline-variant",
      )}
    >
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-high/60"
        onClick={() => setExpanded((value) => !value)}
      >
        <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label font-bold shrink-0", meta.chip)}>
          <Icon name={meta.icon} size={12} />
          {t(meta.label)}
        </span>
        <span className="flex-1 min-w-0 text-body-sm text-on-surface truncate" title={mission.goal}>
          {mission.goal}
        </span>
        {running && <Icon name="sync" size={16} className="animate-spin text-primary shrink-0" />}
        {!running && !failed && <Icon name="check_circle" size={16} className="text-success shrink-0" />}
        {failed && <Icon name="warning" size={16} className="text-error shrink-0" />}
        <Icon name={expanded ? "expand_less" : "expand_more"} size={16} className="text-on-surface-variant shrink-0" />
      </button>
      <div className="px-3 pb-2 space-y-1">
        {visible.map((activity, index) => (
          <p key={index} className="text-body-sm text-on-surface-variant flex gap-2">
            {activity.ts && <span className="tabular-nums shrink-0 opacity-70">{activity.ts.slice(11, 19)}</span>}
            <span className="min-w-0">{activity.message}</span>
          </p>
        ))}
        {failed && (
          <p className="text-body-sm text-on-surface-variant italic">
            {t("该任务结论未纳入评分，相关维度按保守缺省处理并已注明。")}
          </p>
        )}
      </div>
    </div>
  );
}

export default function PanelTimeline({ trace, evaluating }: { trace: PanelTraceEvent[]; evaluating: boolean }) {
  const { t } = useI18n();
  const model = useMemo(() => deriveModel(trace), [trace]);
  const doneCount = model.missions.filter((mission) => mission.status === "done").length;
  const failedCount = model.missions.filter((mission) => mission.status === "failed").length;
  const finished = !!model.formatterMessage;
  const failedRun = failedCount > 0 && model.missions.length === failedCount && finished;

  return (
    <div className="space-y-4">
      <header className="pb-3 border-b-2 border-outline-variant flex items-start justify-between gap-4">
        <div>
          <h2 className="text-title-lg font-bold text-on-surface">{t("评估协作记录")}</h2>
          <p className="mt-1 text-body-sm text-on-surface-variant">
            {t("评审团模式 · 主席 × 类型化评审员 × 确定性裁决")}
          </p>
          <div className="mt-3">
            <StageDots model={model} evaluating={evaluating} />
          </div>
        </div>
        <StatusChip
          tone={failedRun ? "error" : finished ? "success" : evaluating ? "primary" : "neutral"}
          variant={evaluating || failedRun ? "filled" : "dot"}
          icon={failedRun ? "error" : finished ? "check_circle" : evaluating ? "sync" : "schedule"}
        >
          {failedRun ? t("评估失败") : finished ? t("已完成") : evaluating ? t("运行中") : t("待运行")}
        </StatusChip>
      </header>

      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-low border border-outline-variant">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label font-bold bg-inverse-surface text-inverse-on-surface shrink-0">
          <Icon name="psychology" size={12} />
          {t("主席")}
        </span>
        <p className="flex-1 min-w-0 text-body-sm text-on-surface truncate">
          {model.chairMessage ||
            (evaluating ? t("正在审阅案卷目录，决定派出评审任务…") : t("尚未启动评审"))}
        </p>
        <span className="text-label text-on-surface-variant tabular-nums shrink-0">
          {t("{done}/{total} 任务", { done: doneCount, total: model.missions.length })}
          {failedCount > 0 && ` · ${failedCount} ⚠`}
        </span>
      </div>

      {model.dossierMessage && (
        <p className="flex items-center gap-2 text-body-sm text-on-surface-variant px-1">
          <Icon name="folder_open" size={14} />
          {model.dossierMessage}
        </p>
      )}

      <div className="space-y-2">
        {model.missions.map((mission, index) => (
          <MissionCard
            key={mission.id}
            mission={mission}
            defaultExpanded={mission.status === "running" || (!evaluating && index === model.missions.length - 1)}
          />
        ))}
        {evaluating && model.missions.length === 0 && (
          <>
            <div className="h-16 rounded-xl border border-outline-variant bg-surface-low animate-pulse" />
            <div className="h-16 rounded-xl border border-outline-variant bg-surface-low animate-pulse w-11/12" />
          </>
        )}
        {!evaluating && model.missions.length === 0 && !model.dossierMessage && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-on-surface-variant">
            <Icon name="groups" size={36} />
            <p className="text-body-sm">{t("尚无评审团评估记录")}</p>
          </div>
        )}
      </div>

      {(model.guardMessage || model.formatterMessage) && (
        <div className="space-y-1 pt-1">
          {model.guardMessage && (
            <p className="flex items-center gap-2 text-body-sm text-on-surface px-1">
              <Icon name="rule" size={14} className="text-primary shrink-0" />
              {model.guardMessage}
            </p>
          )}
          {model.formatterMessage && (
            <p className="flex items-center gap-2 text-body-sm text-on-surface-variant px-1">
              <Icon name="description" size={14} className="shrink-0" />
              {model.formatterMessage}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
