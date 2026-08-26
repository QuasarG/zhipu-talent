import type { ReactNode } from "react";
import type { CandidateFolder, FolderChild, FolderChildStatus } from "./talentEvaluationModel";
import { filterFolders } from "./talentEvaluationModel";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import SearchField from "@/components/ui/SearchField";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Props {
  folders: CandidateFolder[];
  search: string;
  onSearch: (value: string) => void;
  openFolderIds: string[];
  onToggleFolder: (candidateId: string) => void;
  selectedCandidateId: string | null;
  /** 当前选中的子项：null = 候选人根节点；"capability" = 能力评估；"jd:<id>" = 配对报告 */
  selectedChildKey: string | null;
  activeSub: "admission" | "capability";
  onSelectCandidate: (candidateId: string) => void;
  onSelectCapability: (candidateId: string) => void;
  onSelectPair: (candidateId: string, jdId: string) => void;
  /** 导入运行卡（插入列表底部，运行期间不可关闭） */
  runningCard?: ReactNode;
  onImport: () => void;
}

const CHILD_STATUS_META: Record<FolderChildStatus, { tone: "primary" | "success" | "error" | "warning" | "neutral"; label: string }> = {
  running: { tone: "primary", label: "评估中" },
  interview: { tone: "success", label: "进入面试" },
  no_interview: { tone: "error", label: "不进入面试" },
  stale: { tone: "warning", label: "需重评" },
  unevaluated: { tone: "neutral", label: "未评估" },
};

/**
 * 统一人才评估外壳的共用左侧：候选人文件夹 + JD 子项 + 导入简历动作。
 * 文件夹标题始终使用姓名（空时显示"未命名"），绝不展示内部 ID。
 */
export default function CandidateFolderTree({
  folders,
  search,
  onSearch,
  openFolderIds,
  onToggleFolder,
  selectedCandidateId,
  selectedChildKey,
  activeSub,
  onSelectCandidate,
  onSelectCapability,
  onSelectPair,
  runningCard,
  onImport,
}: Props) {
  const { t } = useI18n();
  const visible = filterFolders(folders, search);
  const openSet = new Set(openFolderIds);

  return (
    <Card variant="filled" className="min-h-0 overflow-hidden flex flex-col">
      <div className="border-b border-outline-variant px-3 py-3 shrink-0">
        <div className="mb-2.5 flex items-center gap-2">
          <p className="text-title">{t("候选人")}</p>
          <span className="text-label text-on-surface-variant">{folders.length}</span>
        </div>
        <SearchField
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={t("搜索姓名、方向或岗位")}
          className="w-full h-9"
        />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-1.5 admission-panel-scrollbar">
        {visible.map((folder) => (
          <CandidateFolderNode
            key={folder.candidateId}
            folder={folder}
            open={openSet.has(folder.candidateId)}
            onToggle={() => onToggleFolder(folder.candidateId)}
            selectedCandidateId={selectedCandidateId}
            selectedChildKey={selectedChildKey}
            activeSub={activeSub}
            onSelectCandidate={onSelectCandidate}
            onSelectCapability={onSelectCapability}
            onSelectPair={onSelectPair}
          />
        ))}
        {!visible.length && (
          <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 px-4 text-center text-on-surface-variant">
            <Icon name="user-search" size={28} />
            <p className="text-body-sm">{search ? t("没有匹配的候选人") : t("还没有候选人文件夹")}</p>
            {!search && <p className="text-label">{t("导入简历后，每个候选人会作为一个文件夹出现在这里")}</p>}
          </div>
        )}
      </div>

      {runningCard}

      <div className="border-t border-outline-variant p-2 shrink-0">
        <Button variant="outlined" icon="upload_file" className="w-full" onClick={onImport}>
          {t("导入简历")}
        </Button>
      </div>
    </Card>
  );
}

function CandidateFolderNode({
  folder,
  open,
  onToggle,
  selectedCandidateId,
  selectedChildKey,
  activeSub,
  onSelectCandidate,
  onSelectCapability,
  onSelectPair,
}: {
  folder: CandidateFolder;
  open: boolean;
  onToggle: () => void;
  selectedCandidateId: string | null;
  selectedChildKey: string | null;
  activeSub: "admission" | "capability";
  onSelectCandidate: (candidateId: string) => void;
  onSelectCapability: (candidateId: string) => void;
  onSelectPair: (candidateId: string, jdId: string) => void;
}) {
  const { t } = useI18n();
  const rootActive = selectedCandidateId === folder.candidateId && selectedChildKey === null;
  return (
    <div className="mb-1">
      <div
        className={cn(
          "flex items-center gap-1 rounded-md transition-colors",
          rootActive ? "bg-secondary-container" : "hover:bg-surface-low",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label={open ? t("折叠") : t("展开")}
          className="state-layer flex h-9 w-7 shrink-0 cursor-pointer items-center justify-center rounded-full text-on-surface-variant"
        >
          <Icon name={open ? "chevron-down" : "chevron-right"} size={15} />
        </button>
        <button
          type="button"
          onClick={() => onSelectCandidate(folder.candidateId)}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 py-1.5 pr-2.5 text-left"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-outline bg-primary-container text-title text-on-primary-container">
            {(folder.name || "?").slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-body font-medium">{folder.name || t("未命名")}</span>
              {!folder.inQueue && (
                <span className="shrink-0 text-[10px] text-on-surface-variant">{t("已移出队列")}</span>
              )}
              {!!folder.activeCount && (
                <Icon name="lock" size={13} className="shrink-0 text-primary" />
              )}
            </span>
            <span className="mt-0.5 block truncate text-label text-on-surface-variant">
              {[folder.role, folder.stage].filter(Boolean).join(" · ") || t("尚未标注方向")}
            </span>
          </span>
        </button>
      </div>

      {open && (
        <div className="ml-[26px] mt-0.5 flex flex-col border-l border-outline-variant pl-2">
          {folder.children.map((child) => (
            <FolderChildRow
              key={child.key}
              child={child}
              candidateId={folder.candidateId}
              selected={
                selectedCandidateId === folder.candidateId
                && selectedChildKey === child.key
                && (child.kind === "capability" ? activeSub === "capability" : activeSub === "admission")
              }
              onSelectCapability={onSelectCapability}
              onSelectPair={onSelectPair}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FolderChildRow({
  child,
  candidateId,
  selected,
  onSelectCapability,
  onSelectPair,
}: {
  child: FolderChild;
  candidateId: string;
  selected: boolean;
  onSelectCapability: (candidateId: string) => void;
  onSelectPair: (candidateId: string, jdId: string) => void;
}) {
  const { t } = useI18n();
  const meta = CHILD_STATUS_META[child.status];
  const isCapability = child.kind === "capability";
  return (
    <button
      type="button"
      onClick={() => {
        if (isCapability) onSelectCapability(candidateId);
        else if (child.jdId) onSelectPair(candidateId, child.jdId);
      }}
      className={cn(
        "flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
        selected ? "bg-secondary-container" : "hover:bg-surface-low",
      )}
    >
      <Icon
        name={isCapability ? "psychology" : "work"}
        size={15}
        className={cn("shrink-0", selected ? "text-on-secondary-container" : "text-on-surface-variant")}
      />
      <span className="min-w-0 flex-1 truncate text-body-sm">
        {isCapability ? t("能力评估") : child.jdTitle || t("未命名岗位")}
      </span>
      {isCapability ? (
        <span className="shrink-0 text-[10px] text-warning">{t("重构中")}</span>
      ) : (
        <StatusChip tone={meta.tone} className="shrink-0">
          {child.status === "running" ? (
            <span className="inline-flex items-center gap-0.5">
              <Icon name="lock" size={11} />
              {t(meta.label)}
            </span>
          ) : (
            t(meta.label)
          )}
        </StatusChip>
      )}
    </button>
  );
}
