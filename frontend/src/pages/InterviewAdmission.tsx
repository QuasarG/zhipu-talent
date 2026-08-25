import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  CandidateBrief,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
  WorkflowNodeEvent,
} from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

export default function InterviewAdmission() {
  const [candidates, setCandidates] = useState<CandidateBrief[]>([]);
  const [jds, setJds] = useState<JdEntry[]>([]);
  const [candidateIds, setCandidateIds] = useState<Set<string>>(new Set());
  const [jdIds, setJdIds] = useState<Set<string>>(new Set());
  const [batch, setBatch] = useState<InterviewAssessmentBatch | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [assessments, setAssessments] = useState<InterviewAssessment[]>([]);
  const [forceAllowed, setForceAllowed] = useState(false);
  const [force, setForce] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const { t } = useI18n();

  const loadInputs = useCallback(async () => {
    const [candidateRows, jdRows, settings] = await Promise.all([
      api.candidates.list(),
      api.jds.list(),
      api.interviewAssessments.settings(),
    ]);
    setCandidates(candidateRows);
    setJds(jdRows.filter((jd) => !jd.archived && jd.card_status === "ready"));
    setForceAllowed(settings.can_manage_force_reevaluation && settings.allow_force_reevaluation);
  }, []);

  useEffect(() => {
    loadInputs().catch((reason) => setError(reason instanceof Error ? reason.message : t("加载失败")));
  }, [loadInputs, t]);

  useEffect(() => {
    if (!batch || ["completed", "failed", "cancelled"].includes(batch.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.interviewAssessments.batch(batch.id);
        setBatch(next);
        if (!activeRunId && next.runs?.length) setActiveRunId(next.runs[0].id);
        if (["completed", "failed", "cancelled"].includes(next.status)) {
          setAssessments(await api.interviewAssessments.list(next.candidate_ids, next.jd_ids));
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : t("刷新运行状态失败"));
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [batch, activeRunId, t]);

  const start = async () => {
    if (!candidateIds.size || !jdIds.size || starting) return;
    setStarting(true);
    setError("");
    setAssessments([]);
    try {
      const next = await api.interviewAssessments.start([...candidateIds], [...jdIds], force);
      setBatch(next);
      setActiveRunId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("启动失败"));
    } finally {
      setStarting(false);
    }
  };

  const activeRun = batch?.runs?.find((run) => run.id === activeRunId) ?? batch?.runs?.[0];
  const running = !!batch && !["completed", "failed", "cancelled"].includes(batch.status);

  return (
    <div className="flex flex-col min-h-0">
      <PageToolbar
        title={t("面试准入评估")}
        subtitle={t("显式选择候选人与 JD，逐一判断是否值得投入面试资源")}
        right={
          running ? (
            <Button variant="tonal" icon="stop_circle" onClick={() => api.interviewAssessments.cancelBatch(batch.id)}>
              {t("停止整批")}
            </Button>
          ) : (
            <Button
              variant="filled"
              icon="play_arrow"
              disabled={!candidateIds.size || !jdIds.size || starting}
              onClick={start}
            >
              {starting ? t("启动中…") : t("开始 {n} 个配对", { n: candidateIds.size * jdIds.size })}
            </Button>
          )
        }
      />
      {error && <div className="mb-3 rounded-md bg-error-container px-4 py-2 text-body-sm text-on-error-container">{error}</div>}

      {!batch ? (
        <div className="grid grid-cols-2 gap-4 min-h-[560px]">
          <SelectionCard
            title={t("1. 选择候选人")}
            icon="group"
            rows={candidates.map((candidate) => ({ id: candidate.id, title: candidate.name || t("未命名"), subtitle: candidate.role || candidate.stage }))}
            selected={candidateIds}
            onChange={setCandidateIds}
          />
          <SelectionCard
            title={t("2. 选择 JD")}
            icon="work"
            rows={jds.map((jd) => ({ id: jd.id, title: jd.title, subtitle: jd.assessment_card?.role_summary || jd.team }))}
            selected={jdIds}
            onChange={setJdIds}
          />
          {forceAllowed && (
            <label className="col-span-2 flex items-center gap-3 rounded-md bg-surface-low px-4 py-3 text-body-sm cursor-pointer">
              <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
              <span>{t("允许覆盖仍然有效的当前报告（仅管理员）")}</span>
            </label>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-[300px_minmax(0,1fr)] gap-4 min-h-[600px]">
          <Card variant="filled" className="p-3 min-h-0 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <p className="text-title">{t("配对运行")}</p>
              <StatusChip tone={running ? "primary" : "success"}>
                {batch.completed_pairs}/{batch.total_pairs}
              </StatusChip>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1">
              {(batch.runs ?? []).map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  candidate={candidates.find((item) => item.id === run.candidate_id)}
                  jd={jds.find((item) => item.id === run.jd_id)}
                  active={activeRun?.id === run.id}
                  onClick={() => setActiveRunId(run.id)}
                />
              ))}
            </div>
            {!running && (
              <Button variant="tonal" icon="add" onClick={() => { setBatch(null); setActiveRunId(null); }}>
                {t("新建评估批次")}
              </Button>
            )}
          </Card>
          <Card variant="filled" className="p-5 min-h-0 overflow-y-auto">
            {activeRun && activeRun.status !== "completed" ? (
              <RunTrace run={activeRun} onCancel={() => api.interviewAssessments.cancelRun(activeRun.id)} />
            ) : assessments.length ? (
              <AssessmentResults assessments={assessments} candidates={candidates} jds={jds} />
            ) : (
              <RunTrace run={activeRun} onCancel={() => activeRun && api.interviewAssessments.cancelRun(activeRun.id)} />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function SelectionCard({ title, icon, rows, selected, onChange }: {
  title: string;
  icon: string;
  rows: Array<{ id: string; title: string; subtitle?: string }>;
  selected: Set<string>;
  onChange: (value: Set<string>) => void;
}) {
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange(next);
  };
  return (
    <Card variant="filled" className="p-4 min-h-0 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Icon name={icon} size={20} className="text-primary" />
        <p className="text-title-lg">{title}</p>
        <span className="ml-auto text-label text-on-surface-variant">已选 {selected.size}</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-2">
        {rows.map((row) => (
          <button key={row.id} onClick={() => toggle(row.id)} className={cn(
            "state-layer flex items-start gap-3 rounded-md p-3 text-left cursor-pointer border",
            selected.has(row.id) ? "bg-primary-container border-primary" : "bg-surface-lowest border-transparent",
          )}>
            <Icon name={selected.has(row.id) ? "check_box" : "check_box_outline_blank"} size={19} className="mt-0.5" />
            <span className="min-w-0"><span className="block text-title truncate">{row.title}</span><span className="block text-body-sm text-on-surface-variant line-clamp-2">{row.subtitle || "—"}</span></span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function RunRow({ run, candidate, jd, active, onClick }: {
  run: InterviewAssessmentRun;
  candidate?: CandidateBrief;
  jd?: JdEntry;
  active: boolean;
  onClick: () => void;
}) {
  const tone = run.status === "completed" ? "success" : run.status === "failed" ? "error" : run.status === "cancelled" ? "neutral" : "primary";
  return (
    <button onClick={onClick} className={cn("state-layer rounded-md p-3 text-left cursor-pointer", active ? "bg-secondary-container" : "hover:bg-surface-low")}>
      <span className="flex items-center gap-2"><span className="text-title truncate">{candidate?.name || run.candidate_id}</span><StatusChip tone={tone}>{run.status}</StatusChip></span>
      <span className="block text-label text-on-surface-variant truncate mt-1">{jd?.title || run.jd_id}</span>
    </button>
  );
}

function RunTrace({ run, onCancel }: { run?: InterviewAssessmentRun; onCancel: () => void }) {
  if (!run) return <div className="h-full flex items-center justify-center text-on-surface-variant">等待运行信息</div>;
  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div><p className="text-title-lg">运行过程</p><p className="text-body-sm text-on-surface-variant">节点会随真实工作从上到下生长</p></div>
        {run.status === "running" || run.status === "queued" ? <Button variant="text" icon="stop_circle" onClick={onCancel}>停止此配对</Button> : null}
      </div>
      <div className="relative pl-8 flex flex-col gap-3 before:absolute before:left-[13px] before:top-3 before:bottom-3 before:w-px before:bg-outline-variant">
        {run.run_trace.map((event, index) => <TraceNode key={`${event.node_id}-${index}`} event={event} />)}
        {!run.run_trace.length && <div className="flex items-center gap-2 text-body-sm text-on-surface-variant"><LoadingIndicator size={16} /> 等待调度…</div>}
      </div>
      {run.error_message && <div className="mt-4 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">{run.error_message}</div>}
    </div>
  );
}

function TraceNode({ event }: { event: WorkflowNodeEvent }) {
  const failed = event.status === "failed";
  return (
    <details className="relative rounded-md bg-surface-lowest p-3" open={failed}>
      <span className={cn("absolute -left-[27px] top-4 w-3 h-3 rounded-full ring-4 ring-surface", failed ? "bg-error" : event.status === "completed" ? "bg-success" : "bg-primary animate-pulse")} />
      <summary className="cursor-pointer list-none"><span className="text-title">{event.label || event.node_id}</span><span className="block text-body-sm text-on-surface-variant mt-0.5">{event.summary}</span></summary>
      {event.detail && Object.keys(event.detail).length > 0 && <pre className="mt-3 whitespace-pre-wrap break-words text-label text-on-surface-variant">{JSON.stringify(event.detail, null, 2)}</pre>}
    </details>
  );
}

function AssessmentResults({ assessments, candidates, jds }: { assessments: InterviewAssessment[]; candidates: CandidateBrief[]; jds: JdEntry[] }) {
  const grouped = useMemo(() => {
    const map = new Map<string, InterviewAssessment[]>();
    assessments.forEach((item) => map.set(item.jd_id, [...(map.get(item.jd_id) ?? []), item]));
    map.forEach((items) => items.sort((a, b) => (a.decision === b.decision ? b.total_score - a.total_score : a.decision === "interview" ? -1 : 1)));
    return [...map.entries()];
  }, [assessments]);
  return <div className="flex flex-col gap-5">{grouped.map(([jdId, items]) => <section key={jdId}><h2 className="text-title-lg mb-3">{jds.find((jd) => jd.id === jdId)?.title || jdId}</h2><div className="flex flex-col gap-2">{items.map((item) => <details key={item.id} className="rounded-md bg-surface-lowest p-4"><summary className="list-none cursor-pointer flex items-center gap-3"><StatusChip tone={item.decision === "interview" ? "success" : "error"}>{item.decision === "interview" ? "进入面试" : "不进入面试"}</StatusChip><span className="text-title">{candidates.find((candidate) => candidate.id === item.candidate_id)?.name || item.candidate_id}</span><span className="ml-auto text-headline-sm">{item.total_score.toFixed(1)}</span>{!item.is_valid && <StatusChip tone="warning">需重评</StatusChip>}</summary><pre className="mt-4 whitespace-pre-wrap break-words text-body-sm text-on-surface-variant">{JSON.stringify({ tasks: item.task_assessments, corrections: item.review_corrections, interview_focus: item.interview_focus }, null, 2)}</pre></details>)}</div></section>)}</div>;
}
