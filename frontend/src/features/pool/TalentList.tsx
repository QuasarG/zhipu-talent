import { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import type { PersonBrief, TalentGroup } from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";
import { ENGAGEMENT_LABELS } from "./talentPoolModel";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void | Promise<void>;
  groups?: TalentGroup[];
  onChanged?: () => void;
  onAddPerson?: () => void;
  onManageGroups?: () => void;
  showBatchEvaluate?: boolean;
}

export function classifyTrack(p: { direction?: string; dominant_track?: string; person_type?: string }): string {
  if (p.person_type === "guest") return "";
  if (p.dominant_track) return p.dominant_track.toLowerCase();
  const d = (p.direction || "").toLowerCase();
  if (d.includes("agent")) return "agent";
  if (d.includes("safe")) return "safety";
  if (d.includes("system") || d.includes("infra")) return "ai_infra";
  if (d.includes("multimodal") || d.includes("多模态")) return "multimodal";
  if (d.includes("science") || d.includes("ai4s")) return "ai4science";
  return "";
}

export const STATUS_LABELS = ENGAGEMENT_LABELS;
export const TRACKS = ["base", "agent", "safety", "ai_infra", "multimodal", "ai4science"];

const HR_TONE: Record<string, "success" | "warning" | "info" | "primary" | "neutral"> = {
  newly_admitted: "neutral", screening: "warning", interviewing: "primary",
  offer_pending: "warning", offered: "info", hired: "success", departed: "neutral", rejected: "neutral",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const COLLAPSE_KEY = "talent-pool.collapsed-groups";
function loadCollapsed(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "{}"); } catch { return {}; }
}

/** 单行人才 */
function PersonRow({
  p, active, checked, batchMode, confirming,
  onSelect, onToggle, onConfirmDelete, onCancelDelete, onDragStart,
}: {
  p: PersonBrief;
  active: boolean;
  checked: boolean;
  batchMode: boolean;
  confirming: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onDragStart: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: p.id, disabled: batchMode });
  const { t } = useI18n();
  const track = classifyTrack(p);
  const status = p.engagement_status || "newly_admitted";
  const handleClick = () => {
    if (confirming) return;
    if (batchMode) onToggle();
    else onSelect();
  };
  return (
    <div
      id={`person-item-${p.id}`}
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      onClick={handleClick}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !confirming) {
          e.preventDefault();
          if (batchMode) onToggle();
          else onSelect();
        }
      }}
      onDragStart={onDragStart}
      role="button"
      tabIndex={0}
      className={cn(
        "group relative flex items-center gap-2.5 px-2.5 py-2 rounded-md text-left cursor-grab active:cursor-grabbing transition-colors duration-100 outline-none",
        "focus-visible:ring-2 focus-visible:ring-primary",
        isDragging && "opacity-30",
        batchMode && checked
          ? "bg-secondary-container shadow-[inset_0_0_0_2px_var(--color-primary)]"
          : confirming
            ? "bg-error-container"
            : active
              ? "bg-secondary-container"
              : "hover:bg-surface-low"
      )}
    >
      {/* 头像位：批量态替换为 checkbox（对齐 CandidateQueue） */}
      {batchMode ? (
        <span className={cn(
          "flex items-center justify-center w-9 h-9 rounded-full shrink-0 border-2 transition-colors",
          checked ? "bg-primary border-primary text-on-primary" : "border-outline text-transparent"
        )}>
          {checked && <Icon name="check" size={18} />}
        </span>
      ) : (
        <span className="flex items-center justify-center w-9 h-9 rounded-full bg-primary-container text-on-primary-container text-title shrink-0">
          {(p.name || "?").slice(0, 1)}
        </span>
      )}
      <span className="flex-1 min-w-0">
        <span className="flex items-center justify-between gap-2">
          <span className="text-body font-medium text-on-surface truncate">{p.name || t("未命名")}</span>
          <span className="text-label text-on-surface-variant shrink-0">{fmtTime(p.updated_at)}</span>
        </span>
        <span className="flex items-center gap-1.5 mt-0.5">
          <StatusChip tone={HR_TONE[status] || "neutral"} className="shrink-0">
            {t(STATUS_LABELS[status] || status)}
          </StatusChip>
          <span className="text-body-sm text-on-surface-variant truncate capitalize">
            {[track, p.org].filter(Boolean).join(" · ") || "—"}
          </span>
          {p.person_type !== "guest" && p.overall_score != null && (
            <span className="text-body-sm font-bold text-primary shrink-0 ml-auto">{p.overall_score}</span>
          )}
        </span>
      </span>

      {/* hover 删除按钮（非批量态/确认态） */}
      {!batchMode && !confirming && (
        <span className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onConfirmDelete(); }}
            className="state-layer inline-flex items-center justify-center w-7 h-7 rounded-full bg-surface-lowest text-on-surface-variant hover:text-error cursor-pointer shadow-sm"
            title={t("删除")}
          >
            <Icon name="delete" size={16} />
          </button>
        </span>
      )}

      {/* 二次确认条 */}
      {confirming && (
        <span className="absolute inset-0 flex items-center justify-center gap-2 bg-error-container rounded-md">
          <span className="text-body-sm font-semibold text-on-error-container">{t("彻底删除？")}</span>
          <button type="button" onClick={(e) => { e.stopPropagation(); onConfirmDelete(); }}
            className="state-layer w-6 h-6 rounded-full bg-error text-on-error flex items-center justify-center cursor-pointer" title={t("确认")}>
            <Icon name="check" size={14} />
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); onCancelDelete(); }}
            className="state-layer w-6 h-6 rounded-full text-on-error-container flex items-center justify-center cursor-pointer" title={t("取消")}>
            <Icon name="close" size={14} />
          </button>
        </span>
      )}
    </div>
  );
}

/** 分组容器（可接收拖拽） */
function GroupSection({
  dropId, title, count, collapsed, onToggle, onRename, onDelete, children,
}: {
  dropId: string;
  title: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  onRename?: () => void;
  onDelete?: () => void;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: dropId });
  const { t } = useI18n();
  return (
    <div className="flex flex-col">
      <div className={cn("flex items-center gap-1 px-1 py-1.5 rounded-t-md transition-colors", isOver && "bg-primary-container/40")}>
        <button onClick={onToggle} className="flex items-center gap-1 shrink-0">
          <Icon name={collapsed ? "chevron_right" : "expand_more"} size={18} className="text-on-surface-variant" />
          <span className="text-body font-semibold text-on-surface">{title}</span>
          <span className="text-label text-on-surface-variant">({count})</span>
        </button>
        {onRename && (
          <button onClick={onRename} className="state-layer w-6 h-6 rounded-full flex items-center justify-center text-on-surface-variant hover:text-on-surface cursor-pointer opacity-0 group-hover:opacity-100" title={t("重命名")}>
            <Icon name="edit" size={14} />
          </button>
        )}
        {onDelete && (
          <button onClick={onDelete} className="state-layer w-6 h-6 rounded-full flex items-center justify-center text-on-surface-variant hover:text-error cursor-pointer opacity-0 group-hover:opacity-100" title={t("删除分组")}>
            <Icon name="delete" size={14} />
          </button>
        )}
        {/* 拖拽落点区域 */}
        <div
          ref={setNodeRef}
          className={cn(
            "ml-auto h-6 flex-1 rounded-sm border border-dashed transition-colors",
            isOver ? "border-primary bg-primary-container/30" : "border-transparent"
          )}
        />
      </div>
      {!collapsed && <div className="flex flex-col gap-0.5 pl-1">{children}</div>}
    </div>
  );
}

export default function TalentList({ persons, selectedId, onSelect, onDelete, groups = [], onChanged, onAddPerson, onManageGroups, showBatchEvaluate }: Props) {
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(loadCollapsed);
  const [batchMode, setBatchMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const [batchNote, setBatchNote] = useState("");
  const { t } = useI18n();

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed)); } catch { /* ignore */ }
  }, [collapsed]);
  useEffect(() => { setSelected(new Set()); setBatchNote(""); }, [batchMode, persons]);

  const grouped = useMemo(() => {
    // 排序:有评分的优先,从高到低;无评分的排后面
    const sortByScore = (a: PersonBrief, b: PersonBrief) => {
      const sa = a.overall_score ?? null;
      const sb = b.overall_score ?? null;
      if (sa != null && sb != null) return sb - sa;
      if (sa != null) return -1;
      if (sb != null) return 1;
      return 0;
    };
    const byGroup: Record<string, PersonBrief[]> = {};
    const ungrouped: PersonBrief[] = [];
    for (const p of persons) {
      if (p.group_id && groups.some((g) => g.id === p.group_id)) {
        (byGroup[p.group_id] ||= []).push(p);
      } else {
        ungrouped.push(p);
      }
    }
    for (const gid of Object.keys(byGroup)) byGroup[gid].sort(sortByScore);
    ungrouped.sort(sortByScore);
    return { byGroup, ungrouped };
  }, [persons, groups]);

  const toggleGroup = (id: string) => setCollapsed((c) => ({ ...c, [id]: !c[id] }));
  const toggleSelect = useCallback((id: string) => {
    setSelected((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const visibleIds = useMemo(() => persons.map((p) => p.id), [persons]);
  const selectAll = () => setSelected(new Set(visibleIds));
  const clearAll = () => setSelected(new Set());

  const doMove = async (ids: string[], groupId: string | null) => {
    if (ids.length === 0) return;
    setBusy(true);
    try {
      if (ids.length === 1) await api.persons.move(ids[0], groupId);
      else await api.persons.batchMove(ids, groupId);
      onChanged?.();
    } catch (err) {
      console.error("移动失败", err);
    } finally {
      setBusy(false);
    }
  };



  // 选中项是否包含 guest（人物调查，不可评估）
  const evaluatableIds = useMemo(
    () => persons.filter((p) => selected.has(p.id) && p.person_type !== "guest").map((p) => p.id),
    [persons, selected],
  );

  const doBatchEvaluate = async () => {
    if (evaluatableIds.length === 0 || busy) return;
    setBusy(true);
    setBatchNote("");
    try {
      const resp = await api.persons.batchEvaluate(evaluatableIds);
      onChanged?.();
      // 评估在后端跑起来了：跳简历评估页并聚焦第一个，页面有 running 轮询
      const started = resp.results.filter((r) => r.status === "started" && r.candidate_id);
      if (started.length > 0) {
        navigate(`/resume-evaluate?focus=${started[0].candidate_id}`);
      } else {
        // 全部跳过时的原因汇总，不再静默
        const labels: Record<string, string> = {
          not_found: t("人物不存在"),
          skipped: t("人物调查类型不可评估"),
          no_candidate: t("无关联简历档案"),
          not_verified: t("论文核验未通过"),
          failed: t("启动失败"),
        };
        const counts = new Map<string, number>();
        for (const r of resp.results) {
          const key = labels[r.status] || r.status;
          counts.set(key, (counts.get(key) || 0) + 1);
        }
        setBatchNote(
          t("未能启动评估：{summary}", { summary: [...counts.entries()].map(([k, n]) => t("{n} 人{k}", { n, k })).join(t("，")) })
        );
      }
    } catch (err) {
      console.error("批量评估失败", err);
      setBatchNote(t("批量评估请求失败，请稍后重试"));
    } finally {
      setBusy(false);
      setSelected(new Set());
    }
  };

  const startRename = (g: TalentGroup) => { setRenameId(g.id); setRenameVal(g.name); };
  const commitRename = async () => {
    const name = renameVal.trim();
    const id = renameId;
    setRenameId(null);
    if (!id || !name) return;
    try { await api.talentGroups.rename(id, name); onChanged?.(); } catch (err) { console.error(err); }
  };
  const removeGroup = async (id: string) => {
    setBusy(true);
    try { await api.talentGroups.delete(id); onChanged?.(); } finally { setBusy(false); }
  };

  const renderRow = (p: PersonBrief) => {
    const confirming = confirmingId === p.id;
    return (
      <PersonRow
        key={p.id}
        p={p}
        active={p.id === selectedId}
        checked={selected.has(p.id)}
        batchMode={batchMode}
        confirming={confirming}
        onSelect={() => onSelect(p.id)}
        onToggle={() => toggleSelect(p.id)}
        onConfirmDelete={
          onDelete
            ? async () => {
                if (confirming) { await onDelete(p.id); setConfirmingId(null); }
                else setConfirmingId(p.id);
              }
            : async () => setConfirmingId(null)
        }
        onCancelDelete={() => setConfirmingId(null)}
        onDragStart={() => {}}
      />
    );
  };

  return (
    <Card variant="filled" className="w-full max-w-full flex flex-col min-h-0 min-w-0 overflow-hidden p-3 gap-2">
        <div className="flex items-center justify-between px-1 shrink-0">
          <span className="text-title">{t("共 {count} 位人才", { count: persons.length })}</span>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden flex flex-col gap-1">
          <GroupSection
            dropId="drop-ungrouped"
            title={t("未分组")}
            count={grouped.ungrouped.length}
            collapsed={collapsed["ungrouped"] || false}
            onToggle={() => toggleGroup("ungrouped")}
          >
            {grouped.ungrouped.length === 0
              ? <div className="text-center py-3 text-body-sm text-on-surface-variant">{t("无")}</div>
              : grouped.ungrouped.map(renderRow)}
          </GroupSection>

          {groups.map((g) => (
            <GroupSection
              key={g.id}
              dropId={`drop-group-${g.id}`}
              title={renameId === g.id ? "" : g.name}
              count={(grouped.byGroup[g.id] || []).length}
              collapsed={collapsed[g.id] || false}
              onToggle={() => toggleGroup(g.id)}
              onRename={() => startRename(g)}
              onDelete={() => removeGroup(g.id)}
            >
              {renameId === g.id ? (
                <input
                  autoFocus value={renameVal}
                  onChange={(e) => setRenameVal(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setRenameId(null); }}
                  className="mx-2 h-8 px-2 rounded-sm border border-outline bg-surface-lowest text-body-sm outline-none focus:border-primary"
                />
              ) : null}
              {(grouped.byGroup[g.id] || []).length === 0
                ? <div className="text-center py-3 text-body-sm text-on-surface-variant">{t("拖入人才到此处")}</div>
                : (grouped.byGroup[g.id] || []).map(renderRow)}
            </GroupSection>
          ))}

          {persons.length === 0 && (
            <div className="text-center py-8 text-body-sm text-on-surface-variant">{t("无匹配人才")}</div>
          )}
        </div>

        {/* 批量操作底栏：悬浮「移动到」按钮 + hover 弹出分组菜单 */}
        {batchMode && (
          <div className="shrink-0 border-t border-outline-variant pt-2">
            {batchNote && (
              <p className="mb-1.5 px-1 text-body-sm text-error">{batchNote}</p>
            )}
            <div className="flex flex-wrap items-center justify-center gap-1.5">
            <Button variant="text" icon="close" className="shrink-0 h-10 w-10 px-0" disabled={busy}
              onClick={() => setBatchMode(false)} title={t("退出批量")} />
            <Button variant="tonal" className="flex-1 h-10 text-body-sm" disabled={busy}
              onClick={() => (selected.size === visibleIds.length && visibleIds.length > 0 ? clearAll() : selectAll())}>
              {selected.size === visibleIds.length && visibleIds.length > 0 ? t("取消全选") : t("全选")}
            </Button>
            <MoveMenu
              disabled={selected.size === 0 || busy}
              onPick={(groupId) => doMove([...selected], groupId)}
              groups={groups}
              count={selected.size}
            />
            {showBatchEvaluate && (
              <Button
                variant="filled"
                disabled={evaluatableIds.length === 0 || busy}
                onClick={() => doBatchEvaluate()}
                className="flex-1 min-w-[92px] h-10 px-3 text-body-sm text-on-primary whitespace-nowrap"
              title={t("批量重新评估（人物调查类型自动跳过）")}
            >
              {busy ? t("处理中…") : t("评估({count})", { count: evaluatableIds.length })}
              </Button>
            )}
            </div>
          </div>
        )}

        {/* 底部固定按钮区 */}
        {!batchMode && (
          <div className="flex items-center gap-1.5 shrink-0 border-t border-outline-variant pt-2">
            {onAddPerson && (
              <Button variant="tonal" icon="person_add" className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm" onClick={onAddPerson}>
                {t("手动加入")}
              </Button>
            )}
            {onManageGroups && (
              <Button variant="outlined" icon="create_new_folder" className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm" onClick={onManageGroups}>
                {t("分组")}
              </Button>
            )}
            {persons.length > 0 && (
              <Button variant="outlined" icon="checklist" className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm" onClick={() => setBatchMode(true)}>
                {t("批量操作")}
              </Button>
            )}
          </div>
        )}
      </Card>
  );
}

/** 移动到分组：悬浮按钮 + hover 向上弹出分组菜单 */
function MoveMenu({ disabled, onPick, groups, count }: { disabled: boolean; onPick: (groupId: string | null) => void; groups: TalentGroup[]; count: number }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  return (
    <div
      className="relative flex-1 h-10"
      onMouseEnter={() => !disabled && setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <Button variant="filled" disabled={disabled} className="w-full h-10 text-body-sm text-on-primary"
        onClick={() => !disabled && setOpen((v) => !v)}>
        {t("移动到({count})", { count })}
      </Button>
      {open && (
        <div className="absolute left-0 right-0 bottom-full bg-surface rounded-t-md shadow-lg border border-outline-variant border-b-0 z-10 max-h-60 overflow-y-auto pb-1">
          {groups.length === 0 ? (
            <div className="px-3 py-2 text-body-sm text-on-surface-variant">{t("暂无分组")}</div>
          ) : (
            <>
              {groups.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => { onPick(g.id); setOpen(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left text-body-sm hover:bg-surface-low"
                >
                  <Icon name="folder" size={16} className="text-on-surface-variant" />
                  <span className="flex-1 truncate">{g.name}</span>
                  <span className="text-label text-on-surface-variant">{g.count}</span>
                </button>
              ))}
              <div className="border-t border-outline-variant" />
              <button
                type="button"
                onClick={() => { onPick(null); setOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-body-sm hover:bg-surface-low text-on-surface-variant"
              >
                <Icon name="remove" size={16} />
                <span>{t("移到未分组")}</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
