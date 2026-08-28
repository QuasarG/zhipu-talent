import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { PersonDetail } from "@/lib/types";
import { api } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import Progress from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import { getSchoolLogo } from "@/lib/schoolLogos";
import { useI18n } from "@/lib/i18n";
import EngagementStatusControl from "./EngagementStatusControl";
import EngagementHistory from "./EngagementHistory";
import ResumeVersionModal from "./ResumeVersionCompare";

interface Props {
  person: PersonDetail | null;
  personId: string | null;
  onUpdated: (id: string) => void;
  /** 只读模式（分享页）：隐藏一切编辑/操作入口 */
  readOnly?: boolean;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TalentDetail({ person, personId, onUpdated, readOnly }: Props) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [shareState, setShareState] = useState<"idle" | "copying" | "copied" | "error">("idle");
  const [historyKey, setHistoryKey] = useState(0);
  const [showVersionDiff, setShowVersionDiff] = useState(false);
  const navigate = useNavigate();
  const { t } = useI18n();

  if (!person) {
    return (
      <Card variant="filled" className="min-h-0 overflow-y-auto p-4">
        <div className="flex flex-col items-center justify-center h-full text-center gap-2">
          <Icon name="person_search" size={32} className="text-on-surface-variant" />
          <p className="text-body text-on-surface">{t("从左侧选择一位人才")}</p>
          <p className="text-body-sm text-on-surface-variant">{t("查看统一人才档案")}</p>
        </div>
      </Card>
    );
  }

  const evaluations = person.evaluations || [];
  const latest = evaluations[0];
  // 新准入评估兜底：旧评估表为空但有岗位准入记录时仍算已评估
  const jdEvaluated = !!person.jd_evaluated;
  const reputation = person.reputation_reports || [];
  const initials = (person.display_name || person.name || "?").charAt(0);
  const candidateId = person.candidate_id || "";

  const shareProfile = async () => {
    if (!person) return;
    setShareState("copying");
    try {
      const { share_path } = await api.share.create(person.id);
      const url = `${window.location.origin}${share_path}`;
      const ok = await copyText(url);
      if (!ok) throw new Error("copy failed");
      setShareState("copied");
      setTimeout(() => setShareState("idle"), 2500);
    } catch {
      setShareState("error");
      setTimeout(() => setShareState("idle"), 2500);
    }
  };

  const saveEngagement = async (engagement: string) => {
    if (!candidateId) return;
    setSaving(true);
    setSaveError("");
    try {
      await api.candidates.updateEngagement(candidateId, engagement, "hr-web", "网页修改");
      setHistoryKey((k) => k + 1);
      await onUpdated(person.id);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t("状态更新失败"));
    } finally {
      setSaving(false);
    }
  };

  const isJobFit = latest?.evaluation_mode === "jd_fit_v2";

  return (
    <Card variant="filled" className="w-full max-w-full min-h-0 min-w-0 overflow-hidden flex flex-col">
      <div className="px-4 py-3 border-b border-outline-variant shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-title shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-title-lg text-on-surface truncate">{person.display_name || person.name}</span>
              {person.name_note && person.name && (
                <span className="text-label text-on-surface-variant truncate">（{person.name}）</span>
              )}
              <StatusChip tone={person.person_type === "guest" ? "info" : "primary"} className="shrink-0">
                {person.person_type === "guest" ? t("人物调查") : t("简历评估")}
              </StatusChip>
              {!readOnly && (
                <button
                  onClick={shareProfile}
                  className="state-layer shrink-0 inline-flex items-center gap-1 h-7 px-2.5 rounded-full text-label font-medium text-primary border border-outline-variant cursor-pointer"
                  title={t("复制只读分享链接（30 天有效）")}
                >
                  <Icon name={shareState === "copied" ? "check" : "share"} size={13} />
                  {shareState === "copied" ? t("已复制链接") : shareState === "copying" ? t("生成中…") : shareState === "error" ? t("分享失败") : t("分享")}
                </button>
              )}
              {!readOnly && (
                <button
                  onClick={() => navigate(`/chat?new=1&ask=${encodeURIComponent(t("帮我全面分析一下{name}的背景、评估结果和潜在风险", { name: person.display_name || person.name || "" }))}`)}
                  className="state-layer shrink-0 ml-auto inline-flex items-center gap-1 h-7 px-2.5 rounded-full text-label font-medium text-primary border border-outline-variant cursor-pointer"
                >
                  <Icon name="forum" size={13} />
                  {t("问问 AI")}
                </button>
              )}
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
          <h3 className="text-title mb-1.5">{t("HR 跟进状态")}</h3>
          {candidateId ? (
            <EngagementStatusControl
              compact
              value={person.engagement_status || "newly_admitted"}
              saving={saving}
              readOnly={readOnly}
              onChange={saveEngagement}
            />
          ) : (
            <p className="text-body-sm text-on-surface-variant">{t("该人物没有关联简历，暂不能跟进")}</p>
          )}
          {saveError && <p className="mt-2 text-label text-error">{saveError}</p>}
          {candidateId && <EngagementHistory candidateId={candidateId} refreshKey={historyKey} />}
        </section>

        {/* 评估概览 */}
        {!latest && !jdEvaluated && (
          <section className="rounded-md border border-dashed border-outline-variant px-3 py-3 flex items-center gap-2.5">
            <Icon name="fact_check" size={18} className="text-on-surface-variant shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-body-sm text-on-surface">{t("尚未评估")}</p>
              <p className="text-label text-on-surface-variant mt-0.5">{t("前往人才评估选择候选人与岗位发起准入评估")}</p>
            </div>
            <Button variant="tonal" icon="arrow_forward" className="h-8 shrink-0" onClick={() => navigate("/talent-evaluation/admission")}>
              {t("去评估")}
            </Button>
          </section>
        )}
        {!latest && jdEvaluated && (
          <section>
            <h3 className="text-title mb-1.5 flex items-baseline justify-between gap-2">
              {t("面试准入")}
              <span className="text-label font-normal text-on-surface-variant">{t("针对最匹配 JD，不代表录用")}</span>
            </h3>
            <div className="flex items-center gap-3">
              <StatusChip
                tone={person.latest_jd_decision === "interview" ? "success" : person.latest_jd_decision === "hold" ? "warning" : "error"}
                variant="filled"
              >
                {person.latest_jd_decision === "interview" ? t("进入面试") : person.latest_jd_decision === "hold" ? t("待补信息") : t("不进入面试")}
              </StatusChip>
              <span className="text-headline text-on-surface">{person.latest_jd_score != null ? Math.round(person.latest_jd_score) : "—"}</span>
              <span className="text-body-sm text-on-surface-variant">{t("/100 加权总分（各岗位详情见评估页）")}</span>
            </div>
          </section>
        )}
        {latest && (
          <section>
            <h3 className="text-title mb-1.5 flex items-baseline justify-between gap-2">
              {isJobFit ? t("面试准入") : t("能力概览")}
              <span className="text-label font-normal text-on-surface-variant">
                {isJobFit ? t("针对最匹配 JD，不代表录用") : t("能力描述，不代表录取结论")}
              </span>
            </h3>
            {isJobFit && latest.interview_decision && (
              <StatusChip
                tone={latest.interview_decision === "interview" ? "success" : latest.interview_decision === "hold" ? "warning" : "error"}
                variant="filled"
              >
                {latest.interview_decision === "interview" ? t("进入面试") : latest.interview_decision === "hold" ? t("待补信息") : t("不进入面试")}
              </StatusChip>
            )}
            <div className="flex items-baseline gap-1">
              <span className="text-headline text-on-surface">{latest.overall_score ?? "—"}</span>
              <span className="text-body-sm text-on-surface-variant">{isJobFit ? t("/100 岗位匹配") : t("/100 综合")}</span>
            </div>
            {isJobFit && <p className="mt-0.5 text-body-sm text-on-surface-variant">{latest.best_fit_jd_title}</p>}
            {(latest.publication_score || latest.safety_net_score) ? (
              <p className="text-label text-on-surface-variant mt-0.5 tabular-nums">
                {t("{n} 通用", { n: Math.round(latest.common_score ?? 0) })}
                {" "}+ {t("{n} 专业", { n: Math.round((latest.overall_score ?? 0) - (latest.common_score ?? 0) - (latest.publication_score ?? 0) - (latest.safety_net_score ?? 0)) })}
                {(latest.publication_score ?? 0) > 0 && ` + ${t("{n} 论文", { n: Math.round(latest.publication_score ?? 0) })}`}
                {(latest.safety_net_score ?? 0) > 0 && ` + ${t("{n} 加分", { n: Math.round(latest.safety_net_score ?? 0) })}`}
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

        {/* 各岗位准入结论（新评估形式：一岗一评，取代旧 Track 推荐） */}
        {(latest?.job_fit_assessments?.length ?? 0) > 0 && (
          <section>
            <h3 className="text-title mb-1.5">{t("各岗位准入结论")}</h3>
            <div className="flex flex-col gap-1.5">
              {(latest.job_fit_assessments ?? []).map((a) => (
                <button
                  key={a.jd_id}
                  type="button"
                  onClick={() => navigate(`/talent-evaluation/admission`)}
                  className="group flex items-center gap-2 rounded-md border border-outline-variant px-2.5 py-1.5 text-left cursor-pointer transition-colors hover:bg-surface-low"
                >
                  <StatusChip
                    tone={a.decision === "interview" ? "success" : a.decision === "hold" ? "warning" : "error"}
                    variant={a.decision === "interview" ? "filled" : "dot"}
                  >
                    {a.decision === "interview" ? t("进入面试") : a.decision === "hold" ? t("待补信息") : t("不进入")}
                  </StatusChip>
                  <span className="min-w-0 flex-1 truncate text-body-sm text-on-surface">{a.jd_title}</span>
                  <span className="text-label text-on-surface-variant tabular-nums shrink-0">{Math.round(a.fit_score)}</span>
                </button>
              ))}
            </div>
            <p className="mt-1 text-label text-on-surface-variant">{t("点击前往人才评估查看完整报告")}</p>
          </section>
        )}

        {/* 关系证据 */}
        <section>
          <h3 className="text-title mb-1.5">{t("关系证据")}</h3>
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
                <span className="text-label text-on-surface-variant">{t("教育经历")}</span>
                <StatusChip tone="success">{t("已确认")}</StatusChip>
              </div>
            )}
            {reputation.map((r) => {
              const confirmed = ["approved", "confirmed", "已确认"].includes(r.review_status || "");
              return (
                <div key={r.id} className="flex items-center gap-2">
                  <Icon name="campaign" size={18} className="text-on-surface-variant shrink-0" />
                <span className="text-body-sm text-on-surface flex-1 truncate">{t("舆情核查 · {level}", { level: r.level || "—" })}</span>
                <StatusChip tone={confirmed ? "success" : "warning"}>
                    {confirmed ? t("已确认") : t("待核验")}
                  </StatusChip>
                </div>
              );
            })}
            {!person.org && reputation.length === 0 && (
              <p className="text-body-sm text-on-surface-variant">{t("暂无关系证据")}</p>
            )}
          </div>
        </section>

        {/* 最近更新：三项压成一行 */}
        <section>
          <h3 className="text-title mb-1.5">{t("最近更新")}</h3>
          <div className="flex flex-nowrap items-center gap-x-3 text-label overflow-hidden whitespace-nowrap">
            <span className="flex items-center gap-1">
              <Icon name="description" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">{t("简历评估")}</span>
              <span className="text-on-surface-variant">{evaluations.length ? `v${evaluations.length}` : t("暂未评估")}</span>
            </span>
            <span className="flex items-center gap-1">
              <Icon name="fact_check" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">{t("舆情核查")}</span>
              <span className="text-on-surface-variant">{reputation.length ? t("{count} 条", { count: reputation.length }) : t("未发起")}</span>
            </span>
            <span className="flex items-center gap-1">
              <Icon name="schedule" size={15} className="text-on-surface-variant" />
              <span className="text-on-surface">{t("档案")}</span>
              <span className="text-on-surface-variant">{fmtTime(person.updated_at)}</span>
            </span>
          </div>
        </section>
      </div>

      {person.person_type !== "guest" && personId && (
        <div className="px-4 py-2 border-t border-outline-variant shrink-0">
          <Button variant="text" icon="compare" className="w-full" onClick={() => setShowVersionDiff(true)}>
            {t("简历版本对比")}
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
          {t("查看完整档案")}
        </Button>
      </div>
    </Card>
  );
}
