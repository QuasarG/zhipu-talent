import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { PersonDetail } from "@/lib/types";
import { api } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import Progress from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import { getSchoolLogo } from "@/lib/schoolLogos";
import EngagementStatusControl from "./EngagementStatusControl";
import ResumeVersionModal from "./ResumeVersionCompare";

interface Props {
  person: PersonDetail | null;
  personId: string | null;
  onUpdated: (id: string) => void;
}

const TRACK_TOKENS: Record<string, string> = {
  agent: "var(--color-track-agent)", safety: "var(--color-track-safety)",
  ai_infra: "var(--color-track-ai_infra)", ai4science: "var(--color-track-ai4science)",
  multimodal: "var(--color-track-multimodal)",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TalentDetail({ person, personId, onUpdated }: Props) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [showVersionDiff, setShowVersionDiff] = useState(false);
  const navigate = useNavigate();

  if (!person) {
    return (
      <Card variant="filled" className="min-h-0 overflow-y-auto p-4">
        <div className="flex flex-col items-center justify-center h-full text-center gap-2">
          <Icon name="person_search" size={32} className="text-on-surface-variant" />
          <p className="text-body text-on-surface">从左侧选择一位人才</p>
          <p className="text-body-sm text-on-surface-variant">查看统一人才档案</p>
        </div>
      </Card>
    );
  }

  const evaluations = person.evaluations || [];
  const latest = evaluations[0];
  const reputation = person.reputation_reports || [];
  const initials = (person.name || "?").charAt(0);
  const candidateId = person.candidate_id || "";

  const saveEngagement = async (engagement: string) => {
    if (!candidateId) return;
    setSaving(true);
    setSaveError("");
    try {
      await api.candidates.updateEngagement(candidateId, engagement, "hr-web", "网页修改");
      await onUpdated(person.id);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "状态更新失败");
    } finally {
      setSaving(false);
    }
  };

  const tracks = [...(latest?.recommended_tracks || [])].sort((a, b) => b.weight - a.weight).slice(0, 3);

  return (
    <Card variant="filled" className="w-full max-w-full min-h-0 min-w-0 overflow-hidden flex flex-col">
      <div className="px-4 py-3 border-b border-outline-variant shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-title shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-title-lg text-on-surface truncate">{person.name}</span>
              <StatusChip tone={person.person_type === "guest" ? "info" : "primary"} className="shrink-0 ml-auto">
                {person.person_type === "guest" ? "人物调查" : "简历评估"}
              </StatusChip>
            </div>
            <p className="text-body-sm text-on-surface-variant truncate mt-0.5">
              {person.org || "—"} · {person.direction || "—"}
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-2 flex flex-col gap-3 justify-between">
        {/* HR 跟进状态 */}
        <section>
          <h3 className="text-title mb-1.5">HR 跟进状态</h3>
          {candidateId ? (
            <EngagementStatusControl
              compact
              value={person.engagement_status || "newly_admitted"}
              saving={saving}
              onChange={saveEngagement}
            />
          ) : (
            <p className="text-body-sm text-on-surface-variant">该人物没有关联简历，暂不能跟进</p>
          )}
          {saveError && <p className="mt-2 text-label text-error">{saveError}</p>}
        </section>

        {/* 能力概览：大分 + 全部维度带进度条，清晰度优先 */}
        {latest && (
          <section>
            <h3 className="text-title mb-1.5 flex items-baseline justify-between gap-2">
              能力概览
              <span className="text-label font-normal text-on-surface-variant">能力描述，不代表录取结论</span>
            </h3>
            <div className="flex items-baseline gap-1">
              <span className="text-headline text-on-surface">{latest.overall_score ?? "—"}</span>
              <span className="text-body-sm text-on-surface-variant">/100 综合</span>
            </div>
            {(latest.publication_score || latest.safety_net_score) ? (
              <p className="text-label text-on-surface-variant mt-0.5 tabular-nums">
                {Math.round(latest.common_score ?? 0)} 通用
                {" "}+ {Math.round((latest.overall_score ?? 0) - (latest.common_score ?? 0) - (latest.publication_score ?? 0) - (latest.safety_net_score ?? 0))} 专业
                {(latest.publication_score ?? 0) > 0 && ` + ${Math.round(latest.publication_score ?? 0)} 论文`}
                {(latest.safety_net_score ?? 0) > 0 && ` + ${Math.round(latest.safety_net_score ?? 0)} 加分`}
              </p>
            ) : null}
            {latest.dimension_scores?.length > 0 && (
              <div className="grid grid-cols-3 gap-x-3 gap-y-2.5 mt-2">
                {latest.dimension_scores.map((d) => (
                  <div key={d.key} className="min-w-0" title={d.label}>
                    <p className="text-label text-on-surface-variant truncate">{d.label}</p>
                    <Progress
                      value={d.max_points ? Math.min(100, (d.weighted_score / d.max_points) * 100) : 0}
                      className="my-1"
                    />
                    <p className="text-label font-medium text-on-surface tabular-nums">
                      {d.weighted_score}<span className="text-on-surface-variant font-normal"> / {d.max_points}</span>
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 推荐 Track */}
        {tracks.length > 0 && (
          <section>
            <h3 className="text-title mb-1.5">推荐 Track</h3>
            <div className="flex flex-col gap-1.5">
              {tracks.map((t, i) => {
                const name = t.track || t.name || "";
                return (
                  <div key={i} className="grid grid-cols-[16px_88px_minmax(0,1fr)_36px] items-center gap-2">
                    <span className="text-label text-on-surface-variant">{i + 1}</span>
                    <span className="text-body-sm text-on-surface capitalize truncate">{name}</span>
                    <Progress value={t.weight * 100} color={TRACK_TOKENS[name.toLowerCase()]} />
                    <span className="text-label text-on-surface-variant text-right">{t.weight.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 关系证据 */}
        <section>
          <h3 className="text-title mb-1.5">关系证据</h3>
          <div className="flex flex-col gap-1.5">
            {person.org && (
              <div className="flex items-center gap-2">
                {getSchoolLogo(person.org) ? (
                  <img
                    src={getSchoolLogo(person.org)!}
                    alt=""
                    className="w-5 h-5 rounded-full object-contain shrink-0 bg-surface-lowest"
                  />
                ) : (
                  <Icon name="school" size={18} className="text-on-surface-variant shrink-0" />
                )}
                <span className="text-body-sm text-on-surface flex-1 truncate">{person.org}</span>
                <span className="text-label text-on-surface-variant">教育经历</span>
                <StatusChip tone="success">已确认</StatusChip>
              </div>
            )}
            {reputation.map((r) => {
              const confirmed = ["approved", "confirmed", "已确认"].includes(r.review_status || "");
              return (
                <div key={r.id} className="flex items-center gap-2">
                  <Icon name="campaign" size={18} className="text-on-surface-variant shrink-0" />
                  <span className="text-body-sm text-on-surface flex-1 truncate">舆情核查 · {r.level || "—"}</span>
                  <StatusChip tone={confirmed ? "success" : "warning"}>
                    {confirmed ? "已确认" : "待核验"}
                  </StatusChip>
                </div>
              );
            })}
            {!person.org && reputation.length === 0 && (
              <p className="text-body-sm text-on-surface-variant">暂无关系证据</p>
            )}
          </div>
        </section>

        {/* 最近更新：三项压成一行 */}
        <section>
          <h3 className="text-title mb-1.5">最近更新</h3>
          <div className="flex flex-nowrap items-center gap-x-3 text-label overflow-hidden whitespace-nowrap">
            <span className="flex items-center gap-1">
              <Icon name="description" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">简历评估</span>
              <span className="text-on-surface-variant">{evaluations.length ? `v${evaluations.length}` : "—"}</span>
            </span>
            <span className="flex items-center gap-1">
              <Icon name="fact_check" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">舆情核查</span>
              <span className="text-on-surface-variant">{reputation.length ? `${reputation.length} 条` : "—"}</span>
            </span>
            <span className="flex items-center gap-1">
              <Icon name="schedule" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">档案</span>
              <span className="text-on-surface-variant">{fmtTime(person.updated_at)}</span>
            </span>
          </div>
        </section>
      </div>

      {person.person_type !== "guest" && personId && (
        <div className="px-4 py-2 border-t border-outline-variant shrink-0">
          <Button variant="text" icon="compare" className="w-full" onClick={() => setShowVersionDiff(true)}>
            简历版本对比
          </Button>
        </div>
      )}

      {showVersionDiff && personId && (
        <ResumeVersionModal personId={personId} onClose={() => setShowVersionDiff(false)} />
      )}

      <div className="px-4 py-2 border-t border-outline-variant shrink-0">
        <Button
          variant="filled"
          className="w-full"
          onClick={() => navigate(`/talent-pool/${personId || person.id}`)}
        >
          查看完整档案
        </Button>
      </div>
    </Card>
  );
}
