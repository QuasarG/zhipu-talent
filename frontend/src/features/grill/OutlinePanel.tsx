import type { GrillOutlineNode as OutlineNode } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { StatusChip } from "@/components/ui/Chip";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

type Status = OutlineNode["status"];
const STATUS_META: Record<Status, { label: string; tone: "neutral" | "primary" | "success" }> = {
  pending: { label: "待问", tone: "neutral" },
  active: { label: "进行中", tone: "primary" },
  covered: { label: "已覆盖", tone: "success" },
  obsolete: { label: "已废弃", tone: "neutral" },
};

function NodeRow({ node, depth }: { node: OutlineNode; depth: number }) {
  const { t } = useI18n();
  const meta = STATUS_META[node.status];
  const dead = node.status === "obsolete";
  const active = node.status === "active";
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border-l-2 px-2 py-1.5",
        active ? "border-primary bg-primary-container/50" : "border-transparent"
      )}
      style={{ marginLeft: depth * 18 }}
    >
      <StatusChip tone={meta.tone} variant={active ? "filled" : "dot"} className="mt-0.5 shrink-0">
        {t(meta.label)}
      </StatusChip>
      <div className="min-w-0 flex-1">
        <div className={cn("text-body", dead ? "text-on-surface-variant line-through" : "text-on-surface")}>
          {node.topic}
          {node.source === "dynamic" && (
            <StatusChip tone="warning" className="ml-1.5">
              {t("延伸")}
            </StatusChip>
          )}
        </div>
        {node.answer_summary && !dead && (
          <div className="mt-0.5 truncate text-label text-on-surface-variant" title={node.answer_summary}>
            {node.answer_summary}
          </div>
        )}
      </div>
    </div>
  );
}

/** 提问大纲：树形节点 + 四态徽标 + 当前提问左侧色条高亮 + 已覆盖进度 */
export default function OutlinePanel({ outline }: { outline: OutlineNode[] }) {
  const { t } = useI18n();
  const childrenOf = (id: string | null) =>
    outline.filter((n) => n.parent_id === id).sort((a, b) => a.order - b.order);
  const renderTree = (parentId: string | null, depth: number): React.ReactNode =>
    childrenOf(parentId).map((n) => (
      <div key={n.id}>
        <NodeRow node={n} depth={depth} />
        {renderTree(n.id, depth + 1)}
      </div>
    ));

  const live = outline.filter((n) => n.status !== "obsolete");
  const covered = live.filter((n) => n.status === "covered").length;
  const pct = live.length ? Math.round((covered / live.length) * 100) : 0;

  return (
    <Card variant="filled" className="flex h-full flex-col p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="checklist" size={18} className="text-primary" />
          <h2 className="text-title">{t("提问大纲")}</h2>
        </div>
        <span className="text-label text-on-surface-variant">
          {t("已覆盖 {covered}/{total}", { covered, total: live.length })}
        </span>
      </div>
      <Progress value={pct} className="mb-3" />
      {outline.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center">
          <Icon name="checklist" size={28} className="text-on-surface-variant" />
          <p className="text-label text-on-surface-variant">{t("首轮对话后自动生成大纲骨架")}</p>
        </div>
      ) : (
        <div className="flex-1 min-h-0 space-y-0.5 overflow-y-auto pr-1">{renderTree(null, 0)}</div>
      )}
    </Card>
  );
}
