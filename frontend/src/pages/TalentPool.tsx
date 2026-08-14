import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { PersonBrief, PersonDetail, TalentGroup } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import Chip from "@/components/ui/Chip";
import Card from "@/components/ui/Card";
import { IconButton } from "@/components/ui/Button";
import TalentList, { classifyTrack, STATUS_LABELS, TRACKS } from "@/features/pool/TalentList";
import TalentDetail from "@/features/pool/TalentDetail";
import RelationGraph from "@/features/pool/RelationGraph";
import AddPersonDialog from "@/features/pool/AddPersonDialog";
import GroupDrawer from "@/features/pool/GroupDrawer";
import { useSessionState } from "@/lib/sessionState";
import { useI18n } from "@/lib/i18n";

export default function TalentPool() {
  const [persons, setPersons] = useState<PersonBrief[]>([]);
  const [selected, setSelected] = useState<PersonDetail | null>(null);
  const [selectedId, setSelectedId] = useSessionState<string | null>("talent-pool.selected-id", null);
  const [search, setSearch] = useSessionState("talent-pool.search", "");
  const [typeFilter, setTypeFilter] = useSessionState<"all" | "resume" | "guest">("talent-pool.type-filter", "all");
  const [trackFilter, setTrackFilter] = useSessionState("talent-pool.track-filter", "");
  const [schoolFilter, setSchoolFilter] = useSessionState("talent-pool.school-filter", "");
  const [hrFilter, setHrFilter] = useSessionState("talent-pool.hr-filter", "");
  const [view, setView] = useSessionState<"list" | "graph">("talent-pool.view", "graph");
  const [showAddPerson, setShowAddPerson] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
  const [groups, setGroups] = useState<TalentGroup[]>([]);
  const { t } = useI18n();

  const load = useCallback(async () => {
    try {
      const [list, gs] = await Promise.all([
        api.persons.list(search ? { q: search } : undefined),
        api.talentGroups.list(),
      ]);
      setPersons(list);
      setGroups(gs);
    } catch (err) {
      console.error(err);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [load]);

  const selectPerson = useCallback(async (id: string) => {
    setSelectedId(id);
    try {
      const detail = await api.persons.get(id);
      setSelected(detail);
    } catch (err) {
      console.error(err);
    }
  }, [setSelectedId]);

  useEffect(() => {
    if (!selectedId || selected || !persons.some((person) => person.id === selectedId)) return;
    selectPerson(selectedId);
  }, [persons, selected, selectedId, selectPerson]);

  // 问答页"人才库定位"跳转：?focus=<person_id> → 清空筛选 → 选中并滚动定位
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus) return;
    setSearchParams({}, { replace: true });
    setTypeFilter("all");
    setTrackFilter("");
    setSchoolFilter("");
    setHrFilter("");
    setSearch("");
    selectPerson(focus);
    const timer = setTimeout(() => {
      document
        .getElementById(`person-item-${focus}`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 600);
    return () => clearTimeout(timer);
  }, [searchParams, setSearchParams, selectPerson, setTypeFilter, setTrackFilter, setSchoolFilter, setHrFilter, setSearch]);

  // 删除人才档案：调 API → 刷新列表 → 清空选中详情
  const handleDeletePerson = useCallback(async (id: string) => {
    try {
      await api.persons.delete(id);
      if (selectedId === id) {
        setSelected(null);
        setSelectedId(null);
      }
      await load();
    } catch (err) {
      console.error("删除人才失败", err);
    }
  }, [selectedId, load, setSelectedId]);

  const handlePersonUpdated = useCallback(async (id: string) => {
    await Promise.all([selectPerson(id), load()]);
  }, [load, selectPerson]);

  const counts = {
    all: persons.length,
    resume: persons.filter((p) => p.person_type !== "guest").length,
    invest: persons.filter((p) => p.person_type === "guest").length,
  };

  const schools = useMemo(
    () => Array.from(new Set(persons.map((p) => p.org).filter(Boolean))),
    [persons]
  );

  const filtered = useMemo(
    () =>
      persons.filter(
        (p) =>
          (typeFilter === "all" ||
            (typeFilter === "guest" ? p.person_type === "guest" : p.person_type !== "guest")) &&
          (typeFilter !== "resume" || !trackFilter || classifyTrack(p) === trackFilter) &&
          (!schoolFilter || p.org === schoolFilter) &&
          (!hrFilter || (p.engagement_status || "newly_admitted") === hrFilter)
      ),
    [persons, typeFilter, trackFilter, schoolFilter, hrFilter]
  );

  return (
    <div className="w-full max-w-full h-[calc(100vh-48px)] min-h-0 min-w-0 overflow-hidden flex flex-col">
      <PageToolbar
        title={t("人才库")}
        subtitle={t("统一档案、来源追踪与关系发现")}
        center={
          <SearchField
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("搜索姓名、学校、机构、Track 或论文")}
            className="max-w-[480px] w-full"
          />
        }
        right={
          <>
            <SegmentedButtons
              options={[
                { value: "list", label: t("列表详情"), icon: "list" },
                { value: "graph", label: t("关系图谱"), icon: "account_tree" },
              ]}
              value={view}
              onChange={setView}
            />
            <IconButton icon="refresh" variant="outlined" onClick={load} title={t("刷新")} />
          </>
        }
      />

      <div className="flex items-center gap-2 mb-4 flex-wrap px-2">
        <SegmentedButtons
          options={[
            { value: "all" as const, label: t("全部 {count}", { count: counts.all }) },
            { value: "resume" as const, label: t("简历评估 {count}", { count: counts.resume }) },
            { value: "guest" as const, label: t("人物调查 {count}", { count: counts.invest }) },
          ]}
          value={typeFilter}
          onChange={(v) => {
            setTypeFilter(v);
            setTrackFilter("");
          }}
        />
        {typeFilter === "resume" && (
          <>
            <Chip selected={!trackFilter} onClick={() => setTrackFilter("")}>
              {t("全部")}
            </Chip>
            {TRACKS.map((t) => (
              <Chip key={t} selected={trackFilter === t} onClick={() => setTrackFilter(t)}>
                <span className="capitalize">{t}</span>
              </Chip>
            ))}
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <select
            value={schoolFilter}
            onChange={(e) => setSchoolFilter(e.target.value)}
            className="h-8 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface cursor-pointer"
          >
            <option value="">{t("学校：全部")}</option>
            {schools.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={hrFilter}
            onChange={(e) => setHrFilter(e.target.value)}
            className="h-8 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface cursor-pointer"
          >
            <option value="">{t("HR 状态：全部")}</option>
            {Object.entries(STATUS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{t(l)}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid w-full max-w-full grid-cols-[minmax(0,1.05fr)_minmax(0,2.15fr)_minmax(0,0.95fr)] gap-4 flex-1 min-h-0 min-w-0 overflow-hidden pb-1">
        <TalentList persons={filtered} selectedId={selectedId} onSelect={selectPerson} onDelete={handleDeletePerson} groups={groups} onChanged={load} onAddPerson={() => setShowAddPerson(true)} onManageGroups={() => setShowGroups(true)} showBatchEvaluate />
        {view === "graph" ? (
          <RelationGraph persons={filtered} selectedId={selectedId} onSelect={selectPerson} />
        ) : (
          <Card variant="filled" className="min-h-0 min-w-0 overflow-y-auto overflow-x-hidden p-5">
            <table className="w-full text-body-sm">
              <thead>
                <tr className="text-label text-on-surface-variant text-left">
                  <th className="pb-2 font-medium">{t("姓名")}</th>
                  <th className="pb-2 font-medium">{t("学校")}</th>
                  <th className="pb-2 font-medium">Track</th>
                  <th className="pb-2 font-medium">{t("综合分")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => selectPerson(p.id)}
                    className="cursor-pointer border-t border-outline-variant hover:bg-surface-low"
                  >
                    <td className="py-2 text-on-surface">{p.name || t("未命名")}</td>
                    <td className="py-2 text-on-surface-variant">{p.org || "—"}</td>
                    <td className="py-2 text-on-surface-variant capitalize">{classifyTrack(p) || "—"}</td>
                    <td className="py-2 text-on-surface-variant">{p.overall_score ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
        <TalentDetail person={selected} personId={selectedId} onUpdated={handlePersonUpdated} />
      </div>

      {showAddPerson && (
        <AddPersonDialog onClose={() => setShowAddPerson(false)} onAdded={load} />
      )}
      {showGroups && (
        <GroupDrawer groups={groups} onChanged={load} onClose={() => setShowGroups(false)} />
      )}
    </div>
  );
}
