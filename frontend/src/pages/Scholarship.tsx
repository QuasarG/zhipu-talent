// 奖学金模块重构：单页外壳 = 左申请列表 + 右详情（对齐人才库/人才评估布局）
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
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
  STATUS_LABELS,
  STATUS_TONES,
  fmtScore,
} from "@/features/scholarship/scholarshipModel";
import { cn } from "@/lib/cn";

// 行右侧时间（人才库 fmtTime 同款）
function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 列表行/详情头共用的状态徽章
function ScholarshipStatusChip({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <StatusChip tone={STATUS_TONES[status] ?? "neutral"}>
      {t(STATUS_LABELS[status] ?? status)}
    </StatusChip>
  );
}
// 列表筛选：三态语义（待评估含未跑资格核验/材料暂缺的中间态）
const FILTERS = [
  { key: "all", label: "全部" },
  { key: "pending", label: "待评估" },
  { key: "ineligible", label: "不符合申报条件" },
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
  useEffect(() => {
    if ((view as string) === "graph") setView("overview");
  }, [view, setView]);

  // 图谱页深链：/scholarship?applicant=<id> 直接选中该申请人（选中即自动拉详情）
  const location = useLocation();
  const navigate = useNavigate();
  const applicantParam = new URLSearchParams(location.search).get("applicant");
  useEffect(() => {
    if (!applicantParam) return;
    setSelectedId(applicantParam);
    navigate("/scholarship", { replace: true }); // 消费掉参数，避免刷新反复选中
  }, [applicantParam, setSelectedId, navigate]);

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

  // 评估进行中自动轮询：别的入口（批量/其他会话）触发的评估在本页没有 SSE 连接，
  // 而 trace 边跑边落库，轮询 detail 即可让过程页实时生长；结束时刷一次列表（状态/分数已变）
  const hasRunningEval = (detail?.evaluations ?? []).some((e) => e.status === "running");
  const wasRunningRef = useRef(false);
  useEffect(() => {
    if (!hasRunningEval) {
      if (wasRunningRef.current) {
        wasRunningRef.current = false;
        refreshAll();
      }
      return;
    }
    wasRunningRef.current = true;
    const timer = window.setInterval(refreshDetail, 2500);
    return () => window.clearInterval(timer);
  }, [hasRunningEval, refreshDetail, refreshAll]);

  // 选择失效清理（申请人被删除）
  useEffect(() => {
    if (selectedId && !loading && apps.length && !apps.some((a) => a.id === selectedId)) {
      setSelectedId(null);
    }
  }, [apps, loading, selectedId, setSelectedId]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const PENDING = new Set(["imported", "eligible", "material_incomplete"]);
    return apps.filter((a) => {
      if (filter === "pending" && !PENDING.has(a.status)) return false;
      if (!["all", "pending"].includes(filter) && a.status !== filter) return false;
      if (!q) return true;
      return [a.name, a.name_en, a.school, a.direction, a.email]
        .some((v) => (v || "").toLowerCase().includes(q));
    });
  }, [apps, filter, search]);

  const counts = useMemo(() => {
    const PENDING = new Set(["imported", "eligible", "material_incomplete"]);
    const map: Record<string, number> = { all: apps.length, pending: 0 };
    for (const a of apps) {
      if (PENDING.has(a.status)) map.pending += 1;
      else map[a.status] = (map[a.status] || 0) + 1;
    }
    return map;
  }, [apps]);

  return (
    <div className="w-full max-w-full min-w-0">
      <PageToolbar
        title={t("奖学金初筛")}
        subtitle={t("申请资料工作台 · 飞书问卷同步")}
        right={
          <>
            <span data-tour="scholarship-views" className="inline-flex">
              <SegmentedButtons
                value={view}
                onChange={setView}
                options={[
                  { value: "overview", label: t("申请资料"), icon: "badge" },
                  { value: "materials", label: t("材料预览"), icon: "description" },
                  { value: "assessment", label: t("评估与核验"), icon: "fact_check" },
                ]}
              />
            </span>
            <IconButton icon="refresh" variant="outlined" onClick={refreshAll} title={t("刷新")} />
            <Button icon="person_add" onClick={() => setShowAdd(true)}>{t("添加申请人")}</Button>
          </>
        }
      />

      {/* 评分系统升级公告：v3 重评完成前提示暂无评估数据 */}
      <div className="mx-2 mb-3 flex items-center gap-2 rounded-md border border-primary/40 bg-primary-container/40 px-4 py-2.5 text-body-sm text-on-surface">
        <Icon name="campaign" size={18} className="shrink-0 text-primary" />
        <span>
          {t("评分系统正在改进升级（v3 五维权重制），历史评估数据已清空，当前暂无评估数据。新材料接入不受影响，升级完成后将统一重新评估。")}
        </span>
      </div>

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
        <Card variant="filled" data-tour="scholarship-list" className="min-h-0 min-w-0 flex flex-col overflow-hidden">
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

          <div className="flex-1 min-h-0 overflow-y-auto p-1 space-y-0.5">
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
                <div
                  key={a.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedId(a.id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(a.id); } }}
                  className={cn(
                    "group flex items-center gap-2.5 px-2.5 py-2 rounded-md text-left cursor-pointer transition-colors duration-100 outline-none",
                    "focus-visible:ring-2 focus-visible:ring-primary",
                    selectedId === a.id ? "bg-secondary-container" : "hover:bg-surface-low",
                  )}
                >
                  <span className="flex items-center justify-center w-9 h-9 rounded-full bg-primary-container text-on-primary-container text-title shrink-0">
                    {(a.name || "?").slice(0, 1)}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-body font-medium text-on-surface truncate">{a.name || t("未命名")}</span>
                      <span className="text-label text-on-surface-variant shrink-0">{fmtTime(a.updated_at)}</span>
                    </span>
                    <span className="flex items-center gap-1.5 mt-0.5 min-w-0">
                      {a.evaluating ? (
                        <StatusChip tone="primary" className="shrink-0">{t("评估中")}</StatusChip>
                      ) : (
                        <ScholarshipStatusChip status={a.status} />
                      )}
                      <span className="text-body-sm text-on-surface-variant truncate">
                        {[a.school, a.direction?.split("；")[0]].filter(Boolean).join(" · ") || "—"}
                      </span>
                      {a.total_score != null && (
                        <span className="ml-auto shrink-0 text-label font-medium tabular-nums text-primary">
                          {fmtScore(a.total_score)}
                        </span>
                      )}
                    </span>
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* 右：详情 + 评估链路 / 师生图谱 */}
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
