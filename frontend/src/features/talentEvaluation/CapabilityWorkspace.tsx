import type { CandidateDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import ResumeContent from "@/features/resume/ResumeContent";
import { EmptyState } from "./CandidateSummary";
import { useI18n } from "@/lib/i18n";

/**
 * 能力评估子界面（过渡期形态，docs/rebuild.md §4）。
 *
 * 能力评估的维度、证据契约与评分规则确认前：
 * - 展示明确的"正在重构"状态，不冒充新能力评估；
 * - 只展示候选人结构化简历与已确认事实，不生成无新规则支撑的总分；
 * - 旧通用维度评分与 Track 推荐不在此出现。
 */
export default function CapabilityWorkspace({
  detail,
  loading,
  onReviewed,
}: {
  detail: CandidateDetail | null;
  loading: boolean;
  onReviewed?: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex items-start gap-3 rounded-md border border-warning/40 bg-warning/5 px-4 py-3">
        <Icon name="construction" size={19} className="mt-0.5 shrink-0 text-warning" />
        <div className="min-w-0">
          <p className="text-body font-medium">{t("能力评估正在重构")}</p>
          <p className="mt-1 text-body-sm text-on-surface-variant">
            {t("能力维度、证据契约与评分规则确认前，这里只展示候选人的结构化简历和已确认事实，不提供能力总分；旧简历评估结果已退出主线，不会在此展示。")}
          </p>
        </div>
      </div>

      <Card variant="filled" className="min-h-0 flex-1 overflow-hidden p-5">
        {loading && !detail ? (
          <div className="flex h-full items-center justify-center">
            <LoadingIndicator size={32} label={t("加载中…")} />
          </div>
        ) : detail ? (
          <ResumeContent key={detail.id} detail={detail} onReviewed={onReviewed} />
        ) : (
          <EmptyState
            icon="psychology"
            title={t("从左侧选择一位候选人")}
            hint={t("能力评估重构完成后，这里将呈现候选人的能力结构、边界与证据")}
          />
        )}
      </Card>
    </div>
  );
}
