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
  /** 当前选中的 JD 子项："jd:<id>"；null = 候选人根节点选中 */
  selectedChildKey: string | null;
  onSelectCandidate: (candidateId: string) => void;
  onSelectPair: (candidateId: string, jdId: string) => void;
  /** 导入运行卡（插入列表底部，运行期间不可关闭） */
  runningCard?: ReactNode;
  /** 评估队列卡（批次进度 + 配对列表），展示在人才树与导入按钮之间 */
  queueCard?: ReactNode;
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
 * 文件夹标题始终使用姓名（空时显示"未命名"），绝不展示内部 ID；
 * 子项收在浅色分组容器中，表达"文件夹包含评估对象"的层级关系。
 */
export default function CandidateFolderTree({
  folders,
  search,
  onSearch,
  openFolderIds,
  onToggleFolder,
  selectedCandidateId,
  selectedChildKey,
  onSelectCandidate,
  onSelectPair,
  runningCard,
  queueCard,
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
        {visible.length > 0 && (
          <div className="flex flex-col gap-2">
            {[
              { key: "evaluated", label: t("已评估"), icon: "check_circle", folders: visible.filter((folder) => folder.evaluated) },
              { key: "unevaluated", label: t("未评估"), icon: "radio_button_unchecked", folders: visible.filter((folder) => !folder.evaluated) },
            ].map((group) => group.folders.length > 0 && (
              <section key={group.key} aria-labelledby={`candidate-group-${group.key}`}>
                <div className="flex items-center gap-2 px-2 pb-1 pt-1">
                  <Icon name={group.icon} size={14} className="text-on-surface-variant" />
                  <h3 id={`candidate-group-${group.key}`} className="text-label font-semibold text-on-surface-variant">
                    {group.label}
                  </h3>
                  <span className="text-[11px] tabular-nums text-on-surface-variant">{group.folders.length}</span>
                </div>
                <div>
                  {group.folders.map((folder) => (
                    <CandidateFolderNode
                      key={folder.candidateId}
                      folder={folder}
                      open={openSet.has(folder.candidateId)}
                      onToggle={() => onToggleFolder(folder.candidateId)}
                      selectedCandidateId={selectedCandidateId}
                      selectedChildKey={selectedChildKey}
                      onSelectCandidate={onSelectCandidate}
                      onSelectPair={onSelectPair}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
        {!visible.length && (
          <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 px-4 text-center text-on-surface-variant">
            <Icon name="user-search" size={28} />
            <p className="text-body-sm">{search ? t("没有匹配的候选人") : t("还没有候选人文件夹")}</p>
            {!search && <p className="text-label">{t("导入简历后，每个候选人会作为一个文件夹出现在这里")}</p>}
          </div>
        )}
      </div>

      {runningCard}
      {queueCard}

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
  onSelectCandidate,
  onSelectPair,
}: {
  folder: CandidateFolder;
  open: boolean;
  onToggle: () => void;
  selectedCandidateId: string | null;
  selectedChildKey: string | null;
  onSelectCandidate: (candidateId: string) => void;
  onSelectPair: (candidateId: string, jdId: string) => void;
}) {
  const { t } = useI18n();
  const rootActive = selectedCandidateId === folder.candidateId && selectedChildKey === null;
  return (
    <div className="mb-0.5">
      {/* 父行设计语言与人才库列表同步：无边框纯色头像 + 状态胶囊副行 */}
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
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 py-2 pr-2.5 text-left"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-container text-title text-on-primary-container">
            {(folder.display_name || folder.name || "?").slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-body font-medium">{folder.display_name || folder.name || t("未命名")}</span>
              {!!folder.activeCount && (
                <Icon name="lock" size={13} className="shrink-0 text-primary" />
              )}
            </span>
            <span className="mt-0.5 block truncate text-body-sm text-on-surface-variant">
              {[folder.role, folder.stage].filter(Boolean).join(" · ") || t("尚未标注方向")}
            </span>
          </span>
        </button>
      </div>

      {/* 树形层级：竖线从头像下方引出，子项缩进到头像正下方（对齐即包含，不悬浮留白） */}
      {open && (
        <div className="ml-[32px] mt-0.5 mb-1 flex flex-col border-l border-outline-variant">
          {folder.children.map((child) => (
            <FolderChildRow
              key={child.key}
              child={child}
              candidateId={folder.candidateId}
              selected={
                selectedCandidateId === folder.candidateId && selectedChildKey === child.key
              }
              onSelectPair={onSelectPair}
            />
          ))}
          {!folder.children.length && (
            <p className="px-2.5 py-1.5 text-label text-on-surface-variant">{t("暂无岗位评估")}</p>
          )}
        </div>
      )}
    </div>
  );
}

function FolderChildRow({
  child,
  candidateId,
  selected,
  onSelectPair,
}: {
  child: FolderChild;
  candidateId: string;
  selected: boolean;
  onSelectPair: (candidateId: string, jdId: string) => void;
}) {
  const { t } = useI18n();
  const meta = CHILD_STATUS_META[child.status];
  return (
    <button
      type="button"
      onClick={() => onSelectPair(candidateId, child.jdId)}
      className={cn(
        "relative flex w-full cursor-pointer items-center gap-2 rounded-md py-1.5 pl-3.5 pr-2 text-left transition-colors",
        selected ? "bg-secondary-container" : "hover:bg-surface-low",
      )}
    >
      {/* 横向短线：从竖线引到文字，明确"挂在父文件夹下" */}
      <span
        className={cn(
          "absolute left-0 top-1/2 h-px w-2.5",
          selected ? "bg-on-secondary-container/40" : "bg-outline-variant",
        )}
      />
      <span className="min-w-0 flex-1 truncate text-body-sm">
        {child.jdTitle || t("未命名岗位")}
      </span>
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
    </button>
  );
}
