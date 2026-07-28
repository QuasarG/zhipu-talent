import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { PersonBrief, PersonDetail } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import TalentList from "@/features/pool/TalentList";
import TalentDetail from "@/features/pool/TalentDetail";
import GlassPanel from "@/components/glass/GlassPanel";
import { Search } from "lucide-react";

export default function TalentPool() {
  const [persons, setPersons] = useState<PersonBrief[]>([]);
  const [selected, setSelected] = useState<PersonDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [trackFilter, setTrackFilter] = useState("");

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

  const counts = {
    all: persons.length,
    resume: persons.filter((p) => p.person_type !== "guest").length,
    invest: persons.filter((p) => p.person_type === "guest").length,
  };

  return (
    <div>
      <PageToolbar
        title="人才库"
        subtitle="统一档案、来源追踪与关系发现"
        center={
          <GlassPanel className="flex items-center gap-2 px-3 py-1.5 rounded-[10px] max-w-[480px] w-full">
            <Search size={16} className="text-ink-secondary shrink-0" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索姓名、学校、机构、Track 或论文"
              className="flex-1 border-none bg-transparent text-sm outline-none placeholder:text-ink-muted"
            />
          </GlassPanel>
        }
        right={
          <div className="flex gap-1 p-1 rounded-[10px] bg-white/35">
            <span className="text-xs px-2 py-1 rounded-full bg-teal-soft text-teal">全部 {counts.all}</span>
            <span className="text-xs px-2 py-1 text-ink-secondary">简历 {counts.resume}</span>
            <span className="text-xs px-2 py-1 text-ink-secondary">调查 {counts.invest}</span>
          </div>
        }
      />

      <div className="grid grid-cols-[360px_1fr_300px] gap-4 h-[calc(100vh-56px-60px)] min-h-[500px]">
        <TalentList
          persons={persons}
          selectedId={selectedId}
          onSelect={selectPerson}
          trackFilter={trackFilter}
          setTrackFilter={setTrackFilter}
        />
        <div className="rounded-[14px] bg-surface-paper border border-ink/10 overflow-hidden p-6 flex items-center justify-center">
          <p className="text-sm text-ink-secondary">关系图谱（Canvas 力导向）— 开发中</p>
        </div>
        <TalentDetail person={selected} personId={selectedId} onUpdated={selectPerson} />
      </div>
    </div>
  );
}
