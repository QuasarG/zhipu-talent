import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { CandidateDetail, PersonAdmissionAssessment, PersonDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import ResumeContent from "@/features/resume/ResumeContent";
import EvaluationWorkspace from "@/features/resume/EvaluationWorkspace";
import EngagementStatusControl from "@/features/pool/EngagementStatusControl";
import { useI18n } from "@/lib/i18n";

export default function TalentProfile() {
  const { personId = "" } = useParams();
  const navigate = useNavigate();
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const personDetail = await api.persons.get(personId);
      setPerson(personDetail);
      setCandidate(personDetail.candidate_id ? await api.candidates.get(personDetail.candidate_id) : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("档案加载失败"));
    } finally {
      setLoading(false);
    }
  }, [personId, t]);

  useEffect(() => { load(); }, [load]);

  const updateEngagement = async (status: string) => {
    if (!person?.candidate_id) return;
    setSaving(true);
    setError("");
    try {
      await api.candidates.updateEngagement(person.candidate_id, status, "hr-web", "完整档案页修改");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("状态更新失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="h-[70vh] flex items-center justify-center"><LoadingIndicator size={34} label={t("加载人才档案")} /></div>;
  if (!person) return (
    <div className="h-[70vh] flex flex-col items-center justify-center gap-3 text-on-surface-variant">
      <p>{error || t("人才档案不存在")}</p>
      <Button variant="outlined" icon="arrow_back" onClick={() => navigate("/talent-pool")}>{t("返回人才库")}</Button>
    </div>
  );

  const evaluation = candidate?.evaluation || candidate?.latest_evaluation;

  return (
    <div className="min-w-0 h-[calc(100vh-48px)] min-h-0 overflow-hidden flex flex-col">
      <header className="flex items-center gap-3 h-[88px] py-2 shrink-0">
        <IconButton icon="arrow_back" variant="outlined" title={t("返回人才库")} onClick={() => navigate("/talent-pool")} />
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-headline font-bold text-on-surface flex items-baseline gap-2">
              {person.display_name || person.name}
              {person.name_note && person.name && (
                <span className="text-body-sm font-normal text-on-surface-variant">（{person.name}）</span>
              )}
            </h1>
            {person.dominant_track && <StatusChip tone="primary">{person.dominant_track}</StatusChip>}
            <StatusChip tone="neutral">{person.person_type === "guest" ? t("人物调查") : t("简历评估")}</StatusChip>
          </div>
          <p className="mt-1 text-body-sm text-on-surface-variant">{person.org || t("机构未记录")} · {person.direction || t("方向未记录")}</p>
        </div>
        <div className="ml-auto w-[500px] max-w-[48vw]">
          {person.candidate_id ? (
            <EngagementStatusControl value={person.engagement_status} saving={saving} onChange={updateEngagement} />
          ) : <p className="text-body-sm text-on-surface-variant text-right">{t("该人物没有关联简历")}</p>}
        </div>
      </header>

      {error && <div className="mb-3 px-4 py-2 bg-error-container text-on-error-container text-body-sm">{error}</div>}

      <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-4 flex-1 min-h-0">
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {candidate ? <ResumeContent key={candidate.id} detail={candidate} onReviewed={() => void load()} /> : <EmptyPanel title={t("没有可展示的简历")} />}
        </Card>
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {candidate && person.assessment_view?.admissions.length ? (
            <AdmissionAssessmentWorkspace admissions={person.assessment_view.admissions} />
          ) : candidate ? (
            <EvaluationWorkspace
              candidateId={candidate.id}
              evaluation={evaluation}
              evaluationRun={candidate.evaluation_run}
              academicReport={candidate.academic_report}
              graph={candidate.evaluation_graph}
              liveNodeRuns={[]}
              evaluating={candidate.evaluation_status === "running"}
            />
          ) : <EmptyPanel title={t("没有关联的评估记录")} />}
        </Card>
      </div>
    </div>
  );
}

function EmptyPanel({ title }: { title: string }) {
  return <div className="h-full flex items-center justify-center text-body text-on-surface-variant">{title}</div>;
}

function AdmissionAssessmentWorkspace({ admissions }: { admissions: PersonAdmissionAssessment[] }) {
  const [selectedId, setSelectedId] = useState(admissions[0]?.id || "");
  const selected = admissions.find((item) => item.id === selectedId) || admissions[0];
  const { t } = useI18n();

  useEffect(() => {
    if (!admissions.some((item) => item.id === selectedId)) {
      setSelectedId(admissions[0]?.id || "");
    }
  }, [admissions, selectedId]);

  if (!selected) return <EmptyPanel title={t("没有关联的评估记录")} />;

  return (
    <div className="h-full min-h-0 flex flex-col">
      <div className="shrink-0 border-b border-outline-variant pb-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-title text-on-surface">{t("岗位准入评估")}</p>
            <p className="mt-1 text-label text-on-surface-variant">
              {t("按岗位分别判断是否值得进入面试，不代表录用")}
            </p>
          </div>
          <StatusChip tone={selected.decision === "interview" ? "success" : "error"}>
            {selected.decision === "interview" ? t("进入面试") : t("不进入面试")}
          </StatusChip>
        </div>
        <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
          {admissions.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelectedId(item.id)}
              className={`shrink-0 rounded-md border px-3 py-2 text-left transition-colors ${
                item.id === selected.id
                  ? "border-primary bg-secondary-container text-on-secondary-container"
                  : "border-outline-variant bg-surface-lowest text-on-surface hover:border-outline"
              }`}
            >
              <span className="block max-w-[220px] truncate text-body-sm font-medium">{item.jd_title || t("岗位未命名")}</span>
              <span className="mt-0.5 block text-label opacity-75">{item.total_score.toFixed(1)} / 100</span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-4 pr-1">
        <div className="rounded-lg border border-outline-variant bg-surface-lowest p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-title text-on-surface">{selected.jd_title || t("岗位未命名")}</p>
              <p className="mt-1 text-label text-on-surface-variant">
                {selected.updated_at ? new Date(selected.updated_at).toLocaleString() : t("时间未记录")}
              </p>
            </div>
            <div className="text-right">
              <p className="text-display-sm font-bold text-on-surface">{selected.total_score.toFixed(1)}</p>
              <p className="text-label text-on-surface-variant">/100 {t("加权总分")}</p>
            </div>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          <p className="text-title text-on-surface">{t("核心任务评分")}</p>
          {selected.task_assessments.length ? selected.task_assessments.map((raw, index) => {
            const task = raw as { task_id?: string; title?: string; level?: number; confidence?: string; reasoning_summary?: string };
            return (
              <div key={`${task.task_id || "task"}-${index}`} className="rounded-md border border-outline-variant px-3 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-body-sm font-medium text-on-surface">{task.title || task.task_id || t("核心任务")}</p>
                  <StatusChip tone="neutral">L{task.level ?? "—"}/4</StatusChip>
                </div>
                {task.reasoning_summary && <p className="mt-1 text-label text-on-surface-variant">{task.reasoning_summary}</p>}
              </div>
            );
          }) : <p className="text-body-sm text-on-surface-variant">{t("该报告没有任务评分明细")}</p>}
        </div>
      </div>
    </div>
  );
}
