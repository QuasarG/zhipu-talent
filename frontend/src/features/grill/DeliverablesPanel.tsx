import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { GrillDeliverables as Deliverables } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
import { useI18n } from "@/lib/i18n";

interface Props {
  deliverables: Deliverables;
  onClose: () => void;
}

/** 需求包交付弹层：候选人画像 / JD 草稿 / 筛选标准 */
export default function DeliverablesPanel({ deliverables, onClose }: Props) {
  const { t } = useI18n();
  const criteria = deliverables.screening_criteria || {};
  // 旧会话无 persona_profile：编号顺延
  const jdNo = deliverables.persona_profile ? "②" : "①";
  const criteriaNo = deliverables.persona_profile ? "③" : "②";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-6"
      onClick={onClose}
    >
      <Card
        variant="elevated"
        className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-headline">{t("招聘需求包")}</h2>
          <IconButton icon="close" onClick={onClose} />
        </div>

        {!!deliverables.persona_profile && (
          <section className="mb-5">
            <h3 className="mb-2 text-title text-primary">{t("① 候选人画像")}</h3>
            <Card variant="filled" className="border border-primary/30 p-4">
              <div className="flex items-start gap-2.5">
                <Icon name="person" size={20} className="mt-0.5 shrink-0 text-primary" />
                <p className="text-body text-on-surface whitespace-pre-wrap">
                  {deliverables.persona_profile}
                </p>
              </div>
            </Card>
          </section>
        )}

        <section className="mb-5">
          <h3 className="mb-2 text-title text-primary">{t("{no} JD 草稿（参照真实同类 JD 文风）", { no: jdNo })}</h3>
          <Card variant="outlined" className="p-4">
            <div className="chat-markdown text-on-surface">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{deliverables.jd_draft}</ReactMarkdown>
            </div>
          </Card>
          {!!deliverables.reference_jobs?.length && (
            <p className="mt-1.5 text-label text-on-surface-variant">
              {t("参照岗位：{jobs}", { jobs: deliverables.reference_jobs.map((j) => j.title).join("；") })}
            </p>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-title text-primary">{t("{no} 结构化筛选标准", { no: criteriaNo })}</h3>
          <div className="grid grid-cols-2 gap-3">
            <Card variant="outlined" className="p-4">
              <p className="mb-1.5 text-label text-on-surface-variant">{t("硬性门槛")}</p>
              <ul className="list-inside list-disc space-y-1 text-body text-on-surface">
                {(criteria.hard_requirements || []).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </Card>
            <Card variant="outlined" className="p-4">
              <p className="mb-1.5 text-label text-on-surface-variant">{t("加分项")}</p>
              <ul className="list-inside list-disc space-y-1 text-body text-on-surface">
                {(criteria.bonus_items || []).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </Card>
          </div>
        </section>
      </Card>
    </div>
  );
}
