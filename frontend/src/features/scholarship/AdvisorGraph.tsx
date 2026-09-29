import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import RelationGraph from "@/features/pool/RelationGraph";
import { getSchoolLogo } from "@/lib/schoolLogos";

interface GraphNode {
  id: string;
  type: "student" | "advisor" | "school";
  label: string;
  school?: string;
  title?: string;
  score?: number;
}
interface GraphPayload {
  nodes: GraphNode[];
  edges: { from: string; to: string; source: string; confidence: string }[];
  counts: { students: number; advisors: number; schools: number };
}

const types = ["school", "advisor", "student"] as const;
const typeName = { school: "学校", advisor: "导师", student: "学生" };

export default function AdvisorGraph() {
  const { t } = useI18n();
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | GraphNode["type"]>("all");

  const load = () => {
    setLoading(true);
    api.scholarship.advisorGraph()
      .then((data) => setPayload(data))
      .catch(() => setPayload(null))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const graph = useMemo(() => payload && ({ nodes: payload.nodes, edges: payload.edges }), [payload]);
  const relationCounts = useMemo(() => {
    const counts = new Map<string, Set<string>>();
    for (const edge of payload?.edges ?? []) {
      if (!counts.has(edge.from)) counts.set(edge.from, new Set());
      if (!counts.has(edge.to)) counts.set(edge.to, new Set());
      counts.get(edge.from)!.add(edge.to);
      counts.get(edge.to)!.add(edge.from);
    }
    return new Map([...counts].map(([id, neighbors]) => [id, neighbors.size]));
  }, [payload]);
  const groups = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    const matches = (payload?.nodes ?? []).filter((node) =>
      (typeFilter === "all" || typeFilter === node.type) &&
      (!query || node.label.toLocaleLowerCase().includes(query) || (node.school ?? "").toLocaleLowerCase().includes(query))
    );
    return types.map((type) => ({
      type,
      nodes: matches.filter((node) => node.type === type)
        .sort((a, b) => (relationCounts.get(b.id) ?? 0) - (relationCounts.get(a.id) ?? 0) || a.label.localeCompare(b.label, "zh")),
    })).filter((group) => group.nodes.length);
  }, [payload, search, typeFilter, relationCounts]);
  const selectedNode = payload?.nodes.find((node) => node.id === selected);
  const neighbors = selected ? payload?.nodes.filter((node) => payload.edges.some((edge) =>
    (edge.from === selected && edge.to === node.id) || (edge.to === selected && edge.from === node.id)
  )) ?? [] : [];

  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex items-center gap-2 border-b border-outline-variant px-4 py-2.5">
      <Icon name="account_tree" size={18} />
      <strong className="text-title">{t("师生图谱")}</strong>
      {payload && <span className="text-label text-on-surface-variant">{t("学生 {a} · 导师 {b} · 学校 {c}", {
        a: payload.counts.students, b: payload.counts.advisors, c: payload.counts.schools,
      })}</span>}
      <Button variant="tonal" icon="refresh" className="ml-auto h-8 px-3 text-label" onClick={load}>{t("刷新")}</Button>
    </div>
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="flex max-h-72 min-h-0 flex-col border-b border-outline-variant bg-surface-lowest lg:max-h-none lg:border-b-0 lg:border-r">
        <div className="shrink-0 border-b border-outline-variant p-3">
          <div className="flex items-center gap-2 rounded-md border border-outline-variant bg-surface px-3">
            <Icon name="search" size={17} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("搜索学校 / 导师 / 学生")}
              aria-label={t("搜索学校 / 导师 / 学生")} className="h-9 min-w-0 flex-1 bg-transparent text-body-sm outline-none" />
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1">
            {(["all", ...types] as const).map((kind) => <button key={kind} type="button" onClick={() => setTypeFilter(kind)}
              aria-pressed={typeFilter === kind} className={`rounded-md px-1 py-1.5 text-label ${typeFilter === kind ? "bg-primary text-on-primary" : "bg-surface-low text-on-surface-variant hover:bg-surface-high"}`}>
              {t(kind === "all" ? "全部" : typeName[kind])}
            </button>)}
          </div>
          <p className="mt-2 text-label text-on-surface-variant">{t("展示 {n} 个实体", { n: groups.reduce((count, group) => count + group.nodes.length, 0) })}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {groups.map(({ type, nodes }) => <section key={type} aria-label={t(typeName[type])}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-outline-variant bg-surface-lowest/95 px-2 py-2 backdrop-blur-sm">
              <Icon name={type === "school" ? "school" : type === "advisor" ? "supervisor_account" : "person"} size={16} className="text-primary" />
              <strong className="text-label">{t(typeName[type])}</strong>
              <span className="ml-auto text-label text-on-surface-variant">{nodes.length}</span>
            </div>
            {nodes.map((node) => {
              const logo = type === "school" ? getSchoolLogo(node.label) : null;
              return <button key={node.id} type="button" onClick={() => setSelected(node.id)} aria-pressed={selected === node.id}
                className={`flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left hover:bg-surface-low ${selected === node.id ? "bg-primary-container text-on-primary-container" : "text-on-surface"}`}>
                <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-low">
                  {logo ? <img src={logo} alt="" className="size-7 object-contain" /> : <Icon name={type === "school" ? "school" : "person"} size={17} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-body-sm font-medium leading-5">{node.label}</span>
                  {node.school && <span className="block truncate text-label text-on-surface-variant">{node.school}</span>}
                </span>
                <span className="rounded-full bg-surface-low px-1.5 text-label tabular-nums text-on-surface-variant">{relationCounts.get(node.id) ?? 0}</span>
              </button>;
            })}
          </section>)}
          {!groups.length && !loading && <p className="p-6 text-center text-body-sm text-on-surface-variant">{t("没有匹配的实体")}</p>}
        </div>
      </aside>
      <div className="relative min-h-[360px] min-w-0 lg:min-h-0">
        {graph && <RelationGraph graph={graph} selectedId={selected} onSelect={setSelected} />}
        {selectedNode && <div className="absolute right-3 top-3 w-64 rounded-lg border border-outline-variant bg-surface-lowest p-3 shadow-lg">
          <div className="flex items-center gap-2">
            <strong className="min-w-0 flex-1 truncate text-title">{selectedNode.label}</strong>
            <button type="button" aria-label={t("关闭")} onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="text-label text-on-surface-variant">{t(typeName[selectedNode.type])}{selectedNode.school ? ` · ${selectedNode.school}` : ""}</div>
          {selectedNode.title && <p className="mt-1 text-label">{selectedNode.title}</p>}
          <div className="mt-2 max-h-40 overflow-y-auto border-t border-outline-variant pt-2">
            {neighbors.map((node) => <button key={node.id} type="button" className="block w-full truncate text-left text-label hover:text-primary" onClick={() => setSelected(node.id)}>
              {t(typeName[node.type])} · {node.label}
            </button>)}
          </div>
        </div>}
        {loading && <div className="absolute inset-0 flex items-center justify-center bg-surface-lowest/60 text-body-sm">{t("加载中…")}</div>}
      </div>
    </div>
  </div>;
}
