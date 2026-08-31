// 奖学金模块重构：单页外壳 = 左申请列表 + 右详情（对齐人才库/人才评估布局）
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ScholarshipApplication } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { StatusChip } from "@/components/ui/Chip";
import { useSessionState } from "@/lib/sessionState";
import ScholarshipPane, { type ScholarshipView } from "@/features/scholarship/ScholarshipPane";
import {
  DEGREE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
  fmtScore,
} from "@/features/scholarship/scholarshipModel";
import { cn } from "@/lib/cn";

// 列表行/详情头共用的状态徽章
function ScholarshipStatusChip({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <StatusChip tone={STATUS_TONES[status] ?? "neutral"}>
      {t(STATUS_LABELS[status] ?? status)}
    </StatusChip>
  );
}
// 列表筛选：全部 + 状态机各档
const FILTERS = [
  { key: "all", label: "全部" },
  { key: "imported", label: "待筛选" },
  { key: "material_incomplete", label: "材料不全" },
  { key: "ineligible", label: "资格不符" },
  { key: "eligible", label: "待评估" },
  { key: "scored", label: "已评分" },
  { key: "finalized", label: "已定稿" },
] as const;

export default function Scholarship() {
  const { t } = useI18n();
  const [apps, setApps] = useState<ScholarshipApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [detail, setDetail] = useState<ScholarshipApplication | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [selectedId, setSelectedId] = useSessionState<string | null>("scholarship.selected-id", null);
  const [search, setSearch] = useSessionState("scholarship.list-search", "");
  const [filter, setFilter] = useSessionState<string>("scholarship.list-filter", "all");
  const [view, setView] = useSessionState<ScholarshipView>("scholarship.view", "overview");

  const load = useCallback(async () => {
    try {
      setApps(await api.scholarship.list());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  // 选中项详情（列表行只带摘要，评分明细/材料/舆情都要 detail）
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const id = selectedId;
    setDetailLoading(true);
    api.scholarship.get(id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  // 刷新当前详情（右栏操作后调用，不重置左侧列表选中）
  const refreshDetail = useCallback(() => {
    if (!selectedId) return;
    api.scholarship.get(selectedId)
      .then(setDetail)
      .catch(() => { /* 静默，下轮操作再拉 */ });
  }, [selectedId]);

  const refreshAll = useCallback(() => {
    void load();
    refreshDetail();
  }, [load, refreshDetail]);

  // 选择失效清理（申请人被删除）
  useEffect(() => {
    if (selectedId && !loading && apps.length && !apps.some((a) => a.id === selectedId)) {
      setSelectedId(null);
    }
  }, [apps, loading, selectedId, setSelectedId]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return apps.filter((a) => {
      if (filter !== "all" && a.status !== filter) return false;
      if (!q) return true;
      return [a.name, a.name_en, a.school, a.direction, a.email]
        .some((v) => (v || "").toLowerCase().includes(q));
    });
  }, [apps, filter, search]);

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: apps.length };
    for (const a of apps) map[a.status] = (map[a.status] || 0) + 1;
    return map;
  }, [apps]);

  return (
    <div className="w-full max-w-full min-w-0">
      <PageToolbar
        title={t("奖学金初筛")}
        subtitle={t("申请资料工作台 · 飞书问卷同步")}
        right={
          <>
            <SegmentedButtons
              value={view}
              onChange={setView}
              options={[
                { value: "overview", label: t("申请资料"), icon: "badge" },
                { value: "materials", label: t("材料预览"), icon: "description" },
                { value: "assessment", label: t("评估与核验"), icon: "fact_check" },
              ]}
            />
            <IconButton icon="refresh" variant="outlined" onClick={refreshAll} title={t("刷新")} />
            <Button icon="person_add" onClick={() => setShowAdd(true)}>{t("添加申请人")}</Button>
          </>
        }
      />

      {error && (
        <div className="mx-2 mb-3 flex items-center gap-2 rounded-md bg-error-container px-4 py-2 text-body-sm text-on-error-container">
          <Icon name="error" size={17} />
          <span>{error}</span>
          <button type="button" className="ml-auto cursor-pointer" onClick={() => setError("")} aria-label={t("关闭错误提示")}>
            <Icon name="close" size={16} />
          </button>
        </div>
      )}

      <div className="app-workspace-frame grid w-full max-w-full grid-cols-1 gap-3 min-w-0 min-h-0 overflow-y-auto xl:grid-cols-[288px_minmax(0,1fr)] xl:overflow-hidden">
        {/* 左：申请列表 */}
        <Card variant="filled" className="min-h-0 min-w-0 flex flex-col overflow-hidden">
          <div className="p-3 pb-2 flex flex-col gap-2.5 border-b border-outline-variant">
            <SearchField value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("搜索姓名 / 学校 / 方向")} />
            <div className="flex flex-wrap gap-1">
              {FILTERS.map((f) => {
                const count = counts[f.key] ?? 0;
                if (f.key !== "all" && count === 0 && filter !== f.key) return null;
                return (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => setFilter(f.key)}
                    className={cn(
                      "h-7 px-2.5 rounded-full text-label cursor-pointer transition-colors",
                      filter === f.key
                        ? "bg-primary text-on-primary"
                        : "text-on-surface-variant hover:bg-surface-low",
                    )}
                  >
                    {t(f.label)} {count > 0 && <span className="tabular-nums opacity-70">{count}</span>}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center py-10"><LoadingIndicator size={24} /></div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-12 px-4 text-center">
                <Icon name="inbox" size={28} className="text-on-surface-variant" />
                <p className="text-body-sm text-on-surface-variant">
                  {apps.length === 0
                    ? t("还没有申请人；飞书问卷提交后会自动出现在这里")
                    : t("没有符合条件的申请人")}
                </p>
              </div>
            ) : (
              filtered.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelectedId(a.id)}
                  className={cn(
                    "w-full text-left px-3 py-2.5 flex flex-col gap-1 border-b border-outline-variant/60 cursor-pointer transition-colors",
                    selectedId === a.id ? "bg-secondary-container/60" : "hover:bg-surface-low",
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-body-sm font-medium text-on-surface truncate">{a.name || t("未命名")}</span>
                    {a.degree_type && (
                      <span className="text-label text-on-surface-variant shrink-0">{t(DEGREE_LABELS[a.degree_type] ?? a.degree_type)}</span>
                    )}
                    {a.feishu_record_id && (
                      <Icon name="cloud_done" size={13} className="text-on-surface-variant shrink-0" />
                    )}
                    <span className="ml-auto shrink-0"><ScholarshipStatusChip status={a.status} /></span>
                  </div>
                  <div className="flex items-center gap-2 min-w-0 text-label text-on-surface-variant">
                    <span className="truncate">{a.school || "—"}</span>
                    <span className="truncate flex-1">{a.direction || ""}</span>
                    <span className={cn("shrink-0 tabular-nums font-medium", a.total_score != null ? "text-primary" : "")}>
                      {fmtScore(a.total_score)}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* 右：详情 + 评估链路 */}
        <div className="min-w-0 min-h-0 flex flex-col">
          <ScholarshipPane
            app={detail}
            loading={detailLoading}
            missingSelection={!selectedId}
            view={view}
            onViewChange={setView}
            onRefresh={refreshAll}
            onDeleted={() => { setSelectedId(null); void load(); }}
            addDialog={showAdd ? { onClose: () => setShowAdd(false), onDone: refreshAll } : null}
          />
        </div>
      </div>
    </div>
  );
}
