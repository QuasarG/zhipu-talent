import { useState, useEffect, useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import type { PersonBrief, PersonDetail } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import Chip from "@/components/ui/Chip";
import Card from "@/components/ui/Card";
import { IconButton } from "@/components/ui/Button";
import TalentList, { classifyTrack, STATUS_LABELS, TRACKS } from "@/features/pool/TalentList";
import TalentDetail from "@/features/pool/TalentDetail";
import RelationGraph from "@/features/pool/RelationGraph";

export default function TalentPool() {
  const [persons, setPersons] = useState<PersonBrief[]>([]);
  const [selected, setSelected] = useState<PersonDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [trackFilter, setTrackFilter] = useState("");
  const [schoolFilter, setSchoolFilter] = useState("");
  const [hrFilter, setHrFilter] = useState("");
  const [view, setView] = useState<"list" | "graph">("graph");

  const load = useCallback(async () => {
    try {
      const list = await api.persons.list(search ? { name: search } : undefined);
      setPersons(list);
    } catch (err) {
      console.error(err);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [load]);

  const selectPerson = async (id: string) => {
    setSelectedId(id);
    try {
      const detail = await api.persons.get(id);
      setSelected(detail);
    } catch (err) {
      console.error(err);
    }
  };

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
  }, [selectedId, load]);

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
          (!trackFilter || classifyTrack(p) === trackFilter) &&
          (!schoolFilter || p.org === schoolFilter) &&
          (!hrFilter || (p.engagement_status || "newly_admitted") === hrFilter)
      ),
    [persons, trackFilter, schoolFilter, hrFilter]
  );

  return (
    <div>
      <PageToolbar
        title="人才库"
        subtitle="统一档案、来源追踪与关系发现"
        center={
          <SearchField
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索姓名、学校、机构、Track 或论文"
            className="max-w-[480px] w-full"
          />
        }
        right={
          <>
            <div className="flex items-center gap-1 h-9 px-1 rounded-full bg-surface-high text-label whitespace-nowrap">
              <span className="px-2.5 h-7 inline-flex items-center rounded-full bg-primary text-on-primary">
                全部 {counts.all}
              </span>
              <span className="px-2.5 text-on-surface-variant">简历评估 {counts.resume}</span>
              <span className="px-2.5 text-on-surface-variant">人物调查 {counts.invest}</span>
            </div>
            <SegmentedButtons
              options={[
                { value: "list", label: "列表详情", icon: "list" },
                { value: "graph", label: "关系图谱", icon: "account_tree" },
              ]}
              value={view}
              onChange={setView}
            />
            <IconButton icon="refresh" variant="outlined" onClick={load} title="刷新" />
          </>
        }
      />

      <div className="flex items-center gap-2 mb-4 flex-wrap px-2">
        <Chip selected={!trackFilter} onClick={() => setTrackFilter("")}>
          全部
        </Chip>
        {TRACKS.map((t) => (
          <Chip key={t} selected={trackFilter === t} onClick={() => setTrackFilter(t)}>
            <span className="capitalize">{t}</span>
          </Chip>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <select
            value={schoolFilter}
            onChange={(e) => setSchoolFilter(e.target.value)}
            className="h-8 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface cursor-pointer"
          >
            <option value="">学校：全部</option>
            {schools.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={hrFilter}
            onChange={(e) => setHrFilter(e.target.value)}
            className="h-8 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface cursor-pointer"
          >
            <option value="">HR 状态：全部</option>
            {Object.entries(STATUS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-[360px_minmax(0,1fr)_320px] gap-4 h-[calc(100vh-56px-130px)] min-h-[500px]">
        <TalentList persons={filtered} selectedId={selectedId} onSelect={selectPerson} onDelete={handleDeletePerson} />
        {view === "graph" ? (
          <RelationGraph persons={filtered} selectedId={selectedId} onSelect={selectPerson} />
        ) : (
          <Card variant="elevated" className="min-h-0 overflow-y-auto p-4">
            <table className="w-full text-body-sm">
              <thead>
                <tr className="text-label text-on-surface-variant text-left">
                  <th className="pb-2 font-medium">姓名</th>
                  <th className="pb-2 font-medium">学校</th>
                  <th className="pb-2 font-medium">Track</th>
                  <th className="pb-2 font-medium">综合分</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => selectPerson(p.id)}
                    className="cursor-pointer border-t border-outline-variant hover:bg-surface-low"
                  >
                    <td className="py-2 text-on-surface">{p.name || p.id}</td>
                    <td className="py-2 text-on-surface-variant">{p.org || "—"}</td>
                    <td className="py-2 text-on-surface-variant capitalize">{classifyTrack(p) || "—"}</td>
                    <td className="py-2 text-on-surface-variant">{p.overall_score ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
        <TalentDetail person={selected} personId={selectedId} onUpdated={selectPerson} />
      </div>
    </div>
  );
}
