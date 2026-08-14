import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";
import { ENGAGEMENT_LABELS, ENGAGEMENT_LIFECYCLE, transitionEngagementSelection } from "./talentPoolModel";

interface Props {
  value: string;
  saving?: boolean;
  onChange: (value: string) => void | Promise<void>;
  compact?: boolean;
}

export default function EngagementStatusControl({ value, saving, onChange, compact }: Props) {
  const [pending, setPending] = useState<string | null>(null);
  const { t } = useI18n();

  useEffect(() => setPending(null), [value]);

  const select = async (clicked: string) => {
    if (saving) return;
    const next = transitionEngagementSelection(value, pending, clicked);
    setPending(next.pending);
    if (next.commit) await onChange(next.commit);
  };

  return (
    <div>
      {!ENGAGEMENT_LIFECYCLE.some(([status]) => status === value) && (
        <p className="mb-2 text-label font-semibold text-on-surface-variant">{t("当前：{label}", { label: t(ENGAGEMENT_LABELS[value] || value) })}</p>
      )}
      <div className={cn("grid gap-1.5", compact ? "grid-cols-2" : "grid-cols-4")} role="group" aria-label={t("招聘生命周期状态")}>
        {ENGAGEMENT_LIFECYCLE.map(([status, label, icon]) => {
          const active = value === status;
          const confirming = pending === status;
          return (
            <button
              key={status}
              type="button"
              disabled={saving}
              aria-pressed={active}
              onClick={() => select(status)}
              className={cn(
                "state-layer min-w-0 rounded-full border text-center font-semibold transition-colors disabled:opacity-50",
                compact ? "h-8 px-2 text-[11px]" : "h-9 px-2.5 text-label",
                active && "border-primary bg-primary text-on-primary",
                confirming && "border-primary bg-primary-container text-on-primary-container",
                !active && !confirming && "border-outline-variant bg-surface-lowest text-on-surface-variant hover:bg-surface-low",
              )}
              title={confirming ? t("再次点击确认切换为{label}", { label: t(label) }) : t(label)}
            >
              <span className="flex items-center justify-center gap-1 whitespace-nowrap">
                <Icon name={confirming ? "check" : icon} size={15} className="shrink-0" />
                <span>{confirming ? t("确认{label}", { label: t(label) }) : t(label)}</span>
              </span>
            </button>
          );
        })}
      </div>
      {pending && <p className="mt-1.5 text-label text-primary">{t("再次点击带勾按钮以确认")}</p>}
    </div>
  );
}
