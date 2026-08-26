import type { CandidateDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import { useI18n } from "@/lib/i18n";
import { useNavigate } from "react-router-dom";

/**
 * 面试准入子界面选中候选人根节点时的基本档案摘要（docs/rebuild.md §3.1）。
 * 只呈现已确认事实，不产生任何候选人级总分。
 */
export default function CandidateSummary({
  detail,
  loading,
}: {
  detail: CandidateDetail | null;
  loading: boolean;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();

  if (loading && !detail) {
    return (
      <div className="flex h-full min-h-64 items-center justify-center">
        <LoadingIndicator size={28} label={t("加载中…")} />
      </div>
    );
  }
  if (!detail) {
    return (
      <EmptyState
        icon="folder"
        title={t("从左侧选择一个候选人")}
        hint={t("选中候选人根节点查看档案摘要；选择岗位子项查看该配对的准入报告")}
      />
    );
  }

  const education = (detail.education || []) as Array<Record<string, string>>;
  const verification =
    detail.verification_result === "verified" ? { tone: "success" as const, label: t("核验通过") }
    : detail.verification_result === "rejected" ? { tone: "error" as const, label: t("核验不通过") }
    : detail.verification_result === "needs_review" ? { tone: "warning" as const, label: t("待人工核验") }
    : detail.verification_result === "running" ? { tone: "primary" as const, label: t("论文核验中") }
    : { tone: "neutral" as const, label: t("未核验") };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto admission-panel-scrollbar">
      <Card variant="filled" className="p-5">
        <div className="flex items-start gap-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-outline bg-primary-container text-title-lg text-on-primary-container">
            {(detail.name || "?").slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-title-lg font-medium">{detail.name || t("未命名")}</p>
              <StatusChip tone={verification.tone}>{verification.label}</StatusChip>
            </div>
            <p className="mt-1 text-body-sm text-on-surface-variant">
              {[detail.role, detail.stage].filter(Boolean).join(" · ") || t("尚未标注方向")}
            </p>
            {!!detail.directions?.length && (
              <p className="mt-2 text-body-sm text-on-surface-variant">
                <span className="font-medium text-on-surface">{t("方向")}</span>
                {"　"}{detail.directions.join(" · ")}
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {detail.person_id && (
                <button
                  type="button"
                  onClick={() => navigate(`/talent-pool/${detail.person_id}`)}
                  className="state-layer inline-flex cursor-pointer items-center gap-1 rounded-full border border-outline-variant px-3 py-1.5 text-label text-on-surface-variant hover:text-on-surface"
                >
                  <Icon name="external-link" size={13} />
                  {t("查看人才档案")}
                </button>
              )}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card variant="filled" className="p-4">
          <p className="text-label font-semibold">{t("教育经历")}</p>
          <div className="mt-2 flex flex-col gap-2">
            {education.length ? education.slice(0, 5).map((item, index) => (
              <p key={index} className="text-body-sm text-on-surface-variant">
                <span className="font-medium text-on-surface">
                  {[item.school, item.degree, item.major].filter(Boolean).join(" · ")}
                </span>
                {item.period ? `（${item.period}）` : ""}
              </p>
            )) : <p className="text-label text-on-surface-variant">{t("暂无教育信息")}</p>}
          </div>
        </Card>

        <Card variant="filled" className="p-4">
          <p className="text-label font-semibold">{t("技能关键词")}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {detail.skills?.length
              ? detail.skills.slice(0, 16).map((skill) => (
                <span key={skill} className="rounded-full bg-surface-high px-2.5 py-1 text-label text-on-surface-variant">{skill}</span>
              ))
              : <p className="text-label text-on-surface-variant">{t("暂无技能信息")}</p>}
          </div>
        </Card>
      </div>

      {!!(detail.publications as unknown[])?.length && (
        <Card variant="filled" className="p-4">
          <p className="text-label font-semibold">{t("论文（候选人自述）")}</p>
          <div className="mt-2 flex flex-col gap-1.5">
            {(detail.publications as Array<Record<string, string>>).slice(0, 6).map((item, index) => (
              <p key={index} className="truncate text-body-sm text-on-surface-variant">
                {item.title || item.name}
                {item.venue || item.journal ? ` — ${item.venue || item.journal}` : ""}
                {item.year ? ` (${item.year})` : ""}
              </p>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-on-surface-variant">{t("论文状态为候选人陈述，以核验结果为准")}</p>
        </Card>
      )}

      {detail.supplementary_info?.trim() && (
        <Card variant="filled" className="p-4">
          <p className="text-label font-semibold">{t("HR 补充信息")}</p>
          <p className="mt-1.5 whitespace-pre-wrap text-body-sm text-on-surface-variant">{detail.supplementary_info}</p>
        </Card>
      )}
    </div>
  );
}

export function EmptyState({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-lowest text-on-surface-variant">
        <Icon name={icon} size={24} />
      </span>
      <p className="mt-2 text-body font-medium text-on-surface">{title}</p>
      {hint && <p className="max-w-72 text-body-sm text-on-surface-variant">{hint}</p>}
    </div>
  );
}
