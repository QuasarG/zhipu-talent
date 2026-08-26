import Icon from "@/components/ui/Icon";

/** 人才评估内容区的通用空态 */
export default function EmptyState({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
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
