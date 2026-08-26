import { useMemo } from "react";
import type {
  CandidateBrief,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
} from "@/lib/types";
import AdmissionWorkflowGraph, {
  type AdmissionGraphNode,
} from "@/features/admission/AdmissionWorkflowGraph";
import AdmissionReport, {
  NodeInspector,
  RUN_STATUS_LABEL,
  RUN_STATUS_TONE,
  TERMINAL_RUN_STATUSES,
} from "./AdmissionReport";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button, { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import SearchField from "@/components/ui/SearchField";
import Progress from "@/components/ui/Progress";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

// ---- 新建准入评估（批量选择临时模式，docs/rebuild.md §3.2） ----

export function NewBatchPanel({
  candidates,
  jds,
  activeRuns,
  candidateIds,
  jdIds,
  candidateSearch,
  jdSearch,
  onCandidateSearch,
  onJdSearch,
  onCandidateIds,
  onJdIds,
  starting,
  onStart,
  onExit,
}: {
  candidates: CandidateBrief[];
  jds: JdEntry[];
  activeRuns: InterviewAssessmentRun[];
  candidateIds: Set<string>;
  jdIds: Set<string>;
  candidateSearch: string;
  jdSearch: string;
  onCandidateSearch: (value: string) => void;
  onJdSearch: (value: string) => void;
  onCandidateIds: (value: Set<string>) => void;
  onJdIds: (value: Set<string>) => void;
  starting: boolean;
  onStart: () => void;
  onExit: () => void;
}) {
  const { t } = useI18n();
  const filteredCandidates = useMemo(() => {
    const query = candidateSearch.trim().toLowerCase();
    if (!query) return candidates;
    return candidates.filter((candidate) =>
      [candidate.name, candidate.role, candidate.stage, candidate.group]
        .some((value) => value?.toLowerCase().includes(query)),
    );
  }, [candidateSearch, candidates]);
  const filteredJds = useMemo(() => {
    const query = jdSearch.trim().toLowerCase();
    if (!query) return jds;
    return jds.filter((jd) =>
      [jd.title, jd.team, jd.assessment_card?.role_summary]
        .some((value) => value?.toLowerCase().includes(query)),
    );
  }, [jdSearch, jds]);

  const pairCount = candidateIds.size * jdIds.size;
  const selectedActiveRuns = activeRuns.filter(
    (item) => candidateIds.has(item.candidate_id) && jdIds.has(item.jd_id),
  );

  const toggle = (current: Set<string>, id: string, onChange: (value: Set<string>) => void) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  };

  return (
    <Card variant="filled" className="min-h-0 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between border-b border-outline-variant px-3 py-3 shrink-0">
        <div>
          <p className="text-title">{t("新建准入评估")}</p>
          <p className="mt-0.5 text-label text-on-surface-variant">
            {t("选择一批候选人和岗位，提交前确认配对数量；这是临时选择模式，不改变左侧文件夹")}
          </p>
        </div>
        <Button variant="text" icon="close" onClick={onExit}>{t("退出选择")}</Button>
      </div>

      <div className="grid flex-1 min-h-0 grid-cols-1 gap-0 overflow-y-auto lg:grid-cols-2 lg:overflow-hidden admission-panel-scrollbar">
        <SelectionList
          title={t("候选人")}
          count={candidates.length}
          selectedCount={candidateIds.size}
          search={candidateSearch}
          searchPlaceholder={t("搜索姓名、方向或阶段")}
          onSearch={onCandidateSearch}
          onSelectVisible={() => onCandidateIds(new Set(filteredCandidates.map((candidate) => candidate.id)))}
          onClear={() => onCandidateIds(new Set())}
        >
          {filteredCandidates.map((candidate) => {
            const selected = candidateIds.has(candidate.id);
            const activeCount = activeRuns.filter((run) => run.candidate_id === candidate.id).length;
            return (
              <button
                type="button"
                key={candidate.id}
                onClick={() => toggle(candidateIds, candidate.id, onCandidateIds)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
                  selected ? "bg-secondary-container" : "hover:bg-surface-low",
                )}
              >
                <span className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                  selected ? "border-primary bg-primary text-on-primary" : "border-outline-variant bg-primary-container text-on-primary-container",
                )}>
                  {selected ? <Icon name="check" size={15} /> : (candidate.name || "?").slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body font-medium">{candidate.name || t("未命名")}</span>
                  <span className="mt-0.5 block truncate text-body-sm text-on-surface-variant">
                    {[candidate.role, candidate.stage].filter(Boolean).join(" · ") || t("尚未标注方向")}
                  </span>
                </span>
                {!!activeCount && <Icon name="lock" size={14} className="shrink-0 text-primary" />}
              </button>
            );
          })}
          {!filteredCandidates.length && <ListEmpty icon="user-search" text={t("没有匹配的候选人")} />}
        </SelectionList>

        <SelectionList
          className="border-t border-outline-variant lg:border-t-0 lg:border-l"
          title={t("岗位 JD")}
          count={jds.length}
          selectedCount={jdIds.size}
          search={jdSearch}
          searchPlaceholder={t("搜索岗位或团队")}
          onSearch={onJdSearch}
          onSelectVisible={() => onJdIds(new Set(filteredJds.map((jd) => jd.id)))}
          onClear={() => onJdIds(new Set())}
        >
          {filteredJds.map((jd) => {
            const selected = jdIds.has(jd.id);
            const activeCount = activeRuns.filter((run) => run.jd_id === jd.id).length;
            return (
              <button
                type="button"
                key={jd.id}
                onClick={() => toggle(jdIds, jd.id, onJdIds)}
                className={cn(
                  "mb-1 flex w-full cursor-pointer items-start gap-3 rounded-md border px-2.5 py-2.5 text-left transition-[background-color,border-color] last:mb-0",
                  selected
                    ? "border-outline bg-secondary-container"
                    : "border-transparent bg-surface-lowest hover:border-outline-variant hover:bg-surface-low",
                )}
              >
                <span className={cn(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                  selected ? "border-primary bg-primary text-on-primary" : "border-outline-variant bg-surface-lowest text-on-surface-variant",
                )}>
                  <Icon name={selected ? "check" : "work"} size={15} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body font-medium">{jd.title}</span>
                  <span className="mt-0.5 block line-clamp-2 text-body-sm text-on-surface-variant">
                    {jd.assessment_card?.role_summary || jd.team || t("岗位评估卡已就绪")}
                  </span>
                  <span className="mt-1 block text-label text-on-surface-variant">
                    {t("{n} 项核心任务", { n: jd.assessment_card?.core_tasks.length || 0 })}
                  </span>
                </span>
                {!!activeCount && <Icon name="lock" size={14} className="mt-1 shrink-0 text-primary" />}
              </button>
            );
          })}
          {!filteredJds.length && <ListEmpty icon="work" text={t("没有匹配且已就绪的岗位")} />}
        </SelectionList>
      </div>

      <div className="border-t border-outline-variant px-3 py-3 shrink-0">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-body-sm text-on-surface-variant tabular-nums">
            {t("{n} 位候选人", { n: candidateIds.size })}
            <span className="mx-1.5">×</span>
            {t("{m} 个岗位", { m: jdIds.size })}
            <span className="mx-1.5">=</span>
            <span className="font-medium text-on-surface">{t("{k} 个配对", { k: pairCount })}</span>
          </p>
          {!!selectedActiveRuns.length && (
            <p className="flex items-center gap-1.5 rounded-md border border-outline-variant bg-surface-low px-2.5 py-1.5 text-label text-on-surface-variant">
              <Icon name="lock" size={14} className="shrink-0" />
              {t("所选配对正在评估，完成或停止后可重新评估")}
            </p>
          )}
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="filled"
              icon={selectedActiveRuns.length ? "lock" : "play_circle"}
              disabled={!pairCount || starting || !!selectedActiveRuns.length}
              onClick={onStart}
            >
              {starting
                ? t("正在创建评估批次…")
                : pairCount
                  ? t("开始评估 {n} 个配对", { n: pairCount })
                  : t("先从两侧完成选择")}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function SelectionList({
  className,
  title,
  count,
  selectedCount,
  search,
  searchPlaceholder,
  onSearch,
  onSelectVisible,
  onClear,
  children,
}: {
  className?: string;
  title: string;
  count: number;
  selectedCount: number;
  search: string;
  searchPlaceholder: string;
  onSearch: (value: string) => void;
  onSelectVisible: () => void;
  onClear: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className={cn("flex min-h-[280px] min-w-0 flex-col overflow-hidden", className)}>
      <div className="border-b border-outline-variant px-3 py-2.5">
        <div className="mb-2 flex items-center gap-2">
          <p className="text-title">{title}</p>
          <span className="text-label text-on-surface-variant">{count}</span>
          <span className="ml-auto text-label text-on-surface-variant">{t("已选 {n}", { n: selectedCount })}</span>
        </div>
        <SearchField value={search} onChange={(event) => onSearch(event.target.value)} placeholder={searchPlaceholder} className="w-full h-9" />
        <div className="mt-2 flex items-center gap-3 text-label">
          <button type="button" onClick={onSelectVisible} className="cursor-pointer text-on-surface hover:underline underline-offset-4">{t("选择当前结果")}</button>
          {!!selectedCount && <button type="button" onClick={onClear} className="cursor-pointer text-on-surface-variant hover:text-on-surface">{t("清空")}</button>}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-1.5 admission-panel-scrollbar">{children}</div>
    </div>
  );
}

function ListEmpty({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 text-on-surface-variant">
      <Icon name={icon} size={26} />
      <p className="text-body-sm">{text}</p>
    </div>
  );
}

// ---- 运行中的批次视图：配对状态条 + 运行图 + 报告/节点详情 ----

export function BatchRunView({
  batch,
  activeRunId,
  candidates,
  jds,
  assessments,
  selectedNode,
  selectedNodeId,
  onSelectRun,
  onSelectNode,
  onCancelRun,
  onCancelBatch,
}: {
  batch: InterviewAssessmentBatch;
  activeRunId: string | null;
  candidates: CandidateBrief[];
  jds: JdEntry[];
  assessments: InterviewAssessment[];
  selectedNode: AdmissionGraphNode | null;
  selectedNodeId: string | null;
  onSelectRun: (runId: string) => void;
  onSelectNode: (node: AdmissionGraphNode) => void;
  onCancelRun: (runId: string) => void;
  onCancelBatch: () => void;
}) {
  const { t } = useI18n();
  const runs = batch.runs || [];
  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0];
  const running = !TERMINAL_BATCH.has(batch.status);
  const completedAssessment = activeRun?.status === "completed"
    ? assessments.find((item) => item.candidate_id === activeRun.candidate_id && item.jd_id === activeRun.jd_id)
    : undefined;

  const candidateForRun = (run: InterviewAssessmentRun): CandidateBrief | undefined =>
    candidates.find((item) => item.id === run.candidate_id)
    || (run.candidate_name
      ? ({
          id: run.candidate_id,
          name: run.candidate_name,
          role: "",
          stage: "",
          group: "",
          level: "",
          category: "",
          engagement_status: "",
          admitted_at: null,
        } as CandidateBrief)
      : undefined);
  const jdForRun = (run: InterviewAssessmentRun): JdEntry | undefined =>
    jds.find((item) => item.id === run.jd_id)
    || (run.jd_title
      ? ({
          id: run.jd_id,
          title: run.jd_title,
          team: "",
          raw_text: "",
          supplements: [],
          assessment_card: null,
          card_status: "ready",
          card_error: "",
          card_run_trace: [],
          card_model_usage: [],
          archived: false,
          created_at: "",
          updated_at: "",
        } as JdEntry)
      : undefined);

  const done = batch.completed_pairs + batch.failed_pairs + batch.cancelled_pairs;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <Card variant="filled" className="shrink-0 overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <p className="shrink-0 text-title">{t("评估批次")}</p>
          <div className="hidden min-w-32 flex-1 items-center gap-2 sm:flex">
            <Progress value={batch.total_pairs ? (done / batch.total_pairs) * 100 : 0} className="flex-1" />
            <span className="text-label tabular-nums text-on-surface-variant">{done} / {batch.total_pairs}</span>
          </div>
          {running ? (
            <Button variant="tonal" icon="stop_circle" className="h-9 px-4" onClick={onCancelBatch}>
              {t("停止整批")}
            </Button>
          ) : (
            <StatusChip tone={batch.status === "completed" ? "success" : "neutral"}>
              {t(RUN_STATUS_LABEL[batch.status] || batch.status)}
            </StatusChip>
          )}
        </div>
        <div className="flex gap-1.5 overflow-x-auto border-t border-outline-variant px-3 py-2 admission-panel-scrollbar">
          {runs.map((run) => (
            <PairRunChip
              key={run.id}
              run={run}
              active={run.id === activeRun?.id}
              assessment={assessments.find(
                (item) => item.candidate_id === run.candidate_id && item.jd_id === run.jd_id,
              )}
              onClick={() => onSelectRun(run.id)}
            />
          ))}
        </div>
      </Card>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(480px,1.5fr)_minmax(320px,1fr)]">
        <Card variant="filled" className="relative min-h-[420px] overflow-hidden flex flex-col">
          <div className="flex items-center gap-3 border-b border-outline-variant px-4 py-3 shrink-0">
            <div className="min-w-0">
              <p className="truncate text-title">
                {activeRun?.candidate_name || t("候选人")} × {activeRun?.jd_title || t("岗位")}
              </p>
              <p className="mt-0.5 truncate text-label text-on-surface-variant">
                {t("节点按真实调用顺序从上到下生长")}
              </p>
            </div>
            {activeRun && !TERMINAL_RUN_STATUSES.has(activeRun.status) && (
              <IconButton
                icon="stop_circle"
                className="ml-auto"
                title={t("停止此配对")}
                onClick={() => onCancelRun(activeRun.id)}
              />
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-auto admission-panel-scrollbar">
            {activeRun ? (
              <AdmissionWorkflowGraph
                run={activeRun}
                candidate={candidateForRun(activeRun)}
                jd={jdForRun(activeRun)}
                selectedNodeId={selectedNodeId}
                onSelectNode={onSelectNode}
              />
            ) : (
              <ListEmpty icon="account_tree" text={t("等待运行信息")} />
            )}
          </div>
        </Card>

        <Card variant="filled" className="min-h-[320px] overflow-hidden flex flex-col">
          <div className="flex items-center justify-between border-b border-outline-variant px-4 py-3 shrink-0">
            <p className="text-title">{completedAssessment ? t("报告与节点") : t("节点详情")}</p>
            {activeRun && (
              <StatusChip tone={RUN_STATUS_TONE[activeRun.status] || "neutral"}>
                {t(RUN_STATUS_LABEL[activeRun.status] || activeRun.status)}
              </StatusChip>
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 admission-panel-scrollbar">
            {activeRun && completedAssessment && (
              <AdmissionReport assessment={completedAssessment} jd={jdForRun(activeRun)} run={activeRun} />
            )}
            {completedAssessment && <div className="my-4 border-t border-outline-variant" />}
            <NodeInspector node={selectedNode} />
            {activeRun?.error_message && (
              <div className="mt-4 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">
                <p className="font-medium">{t("运行失败")}</p>
                <p className="mt-1">{activeRun.error_message}</p>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

const TERMINAL_BATCH = new Set(["completed", "failed", "cancelled"]);

function PairRunChip({
  run,
  active,
  assessment,
  onClick,
}: {
  run: InterviewAssessmentRun;
  active: boolean;
  assessment?: InterviewAssessment;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const tone = assessment
    ? assessment.is_valid
      ? assessment.decision === "interview" ? "success" : "error"
      : "warning"
    : RUN_STATUS_TONE[run.status] || "neutral";
  const label = assessment
    ? assessment.is_valid
      ? assessment.decision === "interview" ? t("进入面试") : t("不进入面试")
      : t("需重评")
    : t(RUN_STATUS_LABEL[run.status] || run.status);
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex shrink-0 cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-label transition-colors",
        active ? "border-outline bg-secondary-container text-on-secondary-container" : "border-outline-variant bg-surface-lowest text-on-surface-variant hover:bg-surface-low",
      )}
    >
      <span className="max-w-56 truncate">
        {run.candidate_name || t("候选人")} × {run.jd_title || t("岗位")}
      </span>
      {run.status === "running" && <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />}
      <StatusChip tone={tone}>{label}</StatusChip>
    </button>
  );
}
