import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { CandidateDetail, PersonDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import ResumeContent from "@/features/resume/ResumeContent";
import EvaluationWorkspace from "@/features/resume/EvaluationWorkspace";
import EngagementStatusControl from "@/features/pool/EngagementStatusControl";

export default function TalentProfile() {
  const { personId = "" } = useParams();
  const navigate = useNavigate();
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const personDetail = await api.persons.get(personId);
      setPerson(personDetail);
      setCandidate(personDetail.candidate_id ? await api.candidates.get(personDetail.candidate_id) : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "档案加载失败");
    } finally {
      setLoading(false);
    }
  }, [personId]);

  useEffect(() => { load(); }, [load]);

  const updateEngagement = async (status: string) => {
    if (!person?.candidate_id) return;
    setSaving(true);
    setError("");
    try {
      await api.candidates.updateEngagement(person.candidate_id, status, "hr-web", "完整档案页修改");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态更新失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="h-[70vh] flex items-center justify-center"><LoadingIndicator size={34} label="加载人才档案" /></div>;
  if (!person) return (
    <div className="h-[70vh] flex flex-col items-center justify-center gap-3 text-on-surface-variant">
      <p>{error || "人才档案不存在"}</p>
      <Button variant="outlined" icon="arrow_back" onClick={() => navigate("/talent-pool")}>返回人才库</Button>
    </div>
  );

  const evaluation = candidate?.evaluation || candidate?.latest_evaluation;

  return (
    <div className="min-w-0 h-[calc(100vh-48px)] min-h-0 overflow-hidden flex flex-col">
      <header className="flex items-center gap-3 h-[88px] py-2 shrink-0">
        <IconButton icon="arrow_back" variant="outlined" title="返回人才库" onClick={() => navigate("/talent-pool")} />
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-headline font-bold text-on-surface">{person.name}</h1>
            {person.dominant_track && <StatusChip tone="primary">{person.dominant_track}</StatusChip>}
            <StatusChip tone="neutral">{person.person_type === "guest" ? "人物调查" : "简历评估"}</StatusChip>
          </div>
          <p className="mt-1 text-body-sm text-on-surface-variant">{person.org || "机构未记录"} · {person.direction || "方向未记录"}</p>
        </div>
        <div className="ml-auto w-[500px] max-w-[48vw]">
          {person.candidate_id ? (
            <EngagementStatusControl value={person.engagement_status} saving={saving} onChange={updateEngagement} />
          ) : <p className="text-body-sm text-on-surface-variant text-right">该人物没有关联简历</p>}
        </div>
      </header>

      {error && <div className="mb-3 px-4 py-2 bg-error-container text-on-error-container text-body-sm">{error}</div>}

      <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-4 flex-1 min-h-0">
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {candidate ? <ResumeContent key={candidate.id} detail={candidate} /> : <EmptyPanel title="没有可展示的简历" />}
        </Card>
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {candidate ? (
            <EvaluationWorkspace
              candidateId={candidate.id}
              evaluation={evaluation}
              evaluationRun={candidate.evaluation_run}
              academicReport={candidate.academic_report}
              graph={candidate.evaluation_graph}
              liveNodeRuns={[]}
              evaluating={candidate.evaluation_status === "running"}
            />
          ) : <EmptyPanel title="没有关联的评估记录" />}
        </Card>
      </div>
    </div>
  );
}

function EmptyPanel({ title }: { title: string }) {
  return <div className="h-full flex items-center justify-center text-body text-on-surface-variant">{title}</div>;
}
