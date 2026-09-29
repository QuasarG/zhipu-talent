import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { getSchoolLogo } from "@/lib/schoolLogos";

interface GNodeData { id: string; type: "student" | "advisor" | "school"; label: string; score?: number; title?: string; status?: string; school?: string }
interface GEdgeData { from: string; to: string; source: string; confidence: string }
interface GraphPayload { nodes: GNodeData[]; edges: GEdgeData[]; counts: { students: number; advisors: number; schools: number } }

interface SimNode { id: string; type: GNodeData["type"]; label: string; title: string; score: number; x: number; y: number; homeX: number; homeY: number; vx: number; vy: number }

// Canvas 不认 CSS 变量：同人才库 RelationGraph，从根元素 getComputedStyle 解析成真实色值
interface Palette {
  student: string; advisor: string; school: string;
  edge: string; label: string; labelStrong: string; focus: string;
}
let paletteCache: { at: number; pal: Palette } | null = null;
function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement);
  const t = (n: string, fb: string) => css.getPropertyValue(n).trim() || fb;
  return {
    student: t("--color-primary", "#006A6B"),
    advisor: t("--color-warning", "#B58F00"),
    school: t("--color-tertiary", "#6750A4"),
    edge: t("--color-outline-variant", "#BEC9C8"),
    label: t("--color-on-surface-variant", "#3F4948"),
    labelStrong: t("--color-on-surface", "#161D1D"),
    focus: t("--color-on-surface", "#161D1D"),
  };
}
function palette(): Palette {
  const now = performance.now();
  if (!paletteCache || now - paletteCache.at > 1000) {
    paletteCache = { at: now, pal: readPalette() };  // 1s 缓存：主题切换后自动跟上，又不用每帧强制重排
  }
  return paletteCache.pal;
}

const TYPE_META: Record<string, { token: keyof Palette; r: number; name: string }> = {
  student: { token: "student", r: 12, name: "学生" },
  advisor: { token: "advisor", r: 15, name: "导师" },
  school: { token: "school", r: 17, name: "学校" },
};

const schoolImages = new Map<string, HTMLImageElement>();
function schoolImage(name: string): HTMLImageElement | null {
  const url = getSchoolLogo(name);
  if (!url) return null;
  let image = schoolImages.get(url);
  if (!image) {
    image = new Image();
    image.src = url;
    schoolImages.set(url, image);
  }
  return image.complete && image.naturalWidth > 0 ? image : null;
}

/** 全量三级图谱：布局与圆形头像沿用人才库图谱，选择只改变高亮。 */
export default function AdvisorGraph() {
  const { t } = useI18n();
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "school" | "advisor" | "student">("all");
  const [showLabels, setShowLabels] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<{ nodes: SimNode[]; edges: { a: number; b: number }[]; neighbor: Map<string, Set<number>> }>({ nodes: [], edges: [], neighbor: new Map() });
  const viewRef = useRef({ scale: 1, ox: 0, oy: 0 });
  const fitRef = useRef<() => void>(() => {});
  const rafRef = useRef(0);
  const dragRef = useRef<{ node: number | null; panning: boolean; moved: boolean; startX: number; startY: number; lastX: number; lastY: number }>({ node: null, panning: false, moved: false, startX: 0, startY: 0, lastX: 0, lastY: 0 });

  const load = () => {
    setLoading(true);
    api.scholarship.advisorGraph().then((d) => { setPayload(d); setLoading(false); }).catch(() => setLoading(false));
  };
  useEffect(load, []);
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
  const searchResults = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return (payload?.nodes ?? [])
      .filter((node) => typeFilter === "all" || node.type === typeFilter)
      .filter((node) => !query || node.label.toLocaleLowerCase().includes(query) || (node.school ?? "").toLocaleLowerCase().includes(query))
      .sort((a, b) => (relationCounts.get(b.id) ?? 0) - (relationCounts.get(a.id) ?? 0) || a.label.localeCompare(b.label, "zh"));
  }, [payload, search, typeFilter, relationCounts]);
  const groupedResults = useMemo(() => (
    (["school", "advisor", "student"] as const).map((type) => ({
      type,
      nodes: searchResults.filter((node) => node.type === type),
    })).filter((group) => group.nodes.length > 0)
  ), [searchResults]);

  // 构建模拟
  useEffect(() => {
    if (!payload) return;
    const related = new Map<string, string[]>();
    for (const edge of payload.edges) {
      related.set(edge.from, [...(related.get(edge.from) ?? []), edge.to]);
      related.set(edge.to, [...(related.get(edge.to) ?? []), edge.from]);
    }
    const schools = payload.nodes.filter((n) => n.type === "school").sort((a, b) => a.label.localeCompare(b.label, "zh"));
    const schoolOrder = new Map(schools.map((n, i) => [n.id, i]));
    const advisorOrder = new Map<string, number>();
    for (const n of payload.nodes.filter((item) => item.type === "advisor")) {
      const ranks = (related.get(n.id) ?? []).map((id) => schoolOrder.get(id)).filter((v): v is number => v !== undefined);
      advisorOrder.set(n.id, ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : schools.length);
    }
    const rank = (n: GNodeData) => n.type === "school" ? schoolOrder.get(n.id) ?? 0
      : n.type === "advisor" ? advisorOrder.get(n.id) ?? schools.length
        : Math.min(...(related.get(n.id) ?? []).map((id) => advisorOrder.get(id) ?? schools.length));
    const lanes: GNodeData["type"][] = ["school", "advisor", "student"];
    const ordered = lanes.flatMap((type) => payload.nodes.filter((n) => n.type === type)
      .sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label, "zh")));
    const seen = new Map<GNodeData["type"], number>();
    const nodes: SimNode[] = ordered.map((n) => {
      const i = seen.get(n.type) ?? 0;
      seen.set(n.type, i + 1);
      const columns = n.type === "school" ? 3 : n.type === "advisor" ? 6 : 7;
      const x = (n.type === "school" ? 90 : n.type === "advisor" ? 390 : 770) + (i % columns) * (n.type === "school" ? 75 : 50);
      const y = 75 + Math.floor(i / columns) * (n.type === "school" ? 42 : 30);
      return {
        id: n.id, type: n.type, label: n.label, title: n.title ?? "", score: n.score ?? 0,
        x, y, homeX: x, homeY: y,
        vx: 0, vy: 0,
      };
    });
    const idx = new Map(nodes.map((n, i) => [n.id, i]));
    const edges = payload.edges
      .map((e) => ({ a: idx.get(e.from) ?? -1, b: idx.get(e.to) ?? -1 }))
      .filter((e) => e.a >= 0 && e.b >= 0);
    const neighbor = new Map<string, Set<number>>();
    const add = (k: string, v: number) => { (neighbor.get(k) ?? neighbor.set(k, new Set()).get(k)!).add(v); };
    edges.forEach((e) => { add(nodes[e.a].id, e.b); add(nodes[e.b].id, e.a); });
    simRef.current = { nodes, edges, neighbor };
    for (let i = 0; i < 18; i++) step(0.8);
    requestAnimationFrame(() => fitRef.current());
  }, [payload]);

  const step = (damping: number) => {
    const { nodes, edges } = simRef.current;
    if (!nodes.length) return;
    // 每列只处理相邻节点，避免全量图谱每帧做 N² 次排斥计算。
    for (const type of ["school", "advisor", "student"] as const) {
      const lane = nodes.filter((n) => n.type === type).sort((a, b) => a.y - b.y);
      for (let i = 1; i < lane.length; i++) {
        const a = lane[i - 1], b = lane[i];
        const gap = b.y - a.y;
        const minimum = type === "school" ? 48 : 22;
        if (Math.abs(a.x - b.x) < 25 && gap < minimum) {
          const push = (minimum - gap) * 0.03;
          a.vy -= push; b.vy += push;
        }
      }
    }
    for (const e of edges) {
      const a = nodes[e.a], b = nodes[e.b];
      const delta = Math.max(-220, Math.min(220, b.y - a.y));
      a.vy += delta * 0.0006; b.vy -= delta * 0.0006;
    }
    for (const n of nodes) {
      n.vx += (n.homeX - n.x) * 0.03;
      n.vy += (n.homeY - n.y) * 0.015;
      n.vx *= damping; n.vy *= damping;
      n.x += n.vx; n.y += n.vy;
    }
  };

  const fitView = () => {
    const canvas = canvasRef.current;
    const nodes = simRef.current.nodes;
    if (!canvas || !nodes.length) return;
    const minY = Math.min(...nodes.map((n) => n.y)) - 50;
    const maxY = Math.max(...nodes.map((n) => n.y)) + 55;
    const scale = Math.max(0.08, Math.min(1.5, (canvas.clientWidth - 80) / 1100, (canvas.clientHeight - 80) / (maxY - minY)));
    viewRef.current = { scale, ox: canvas.clientWidth / 2 - 580 * scale, oy: canvas.clientHeight / 2 - (minY + maxY) / 2 * scale };
  };
  fitRef.current = fitView;

  // 渲染循环
  useEffect(() => {
    const render = () => {
      const canvas = canvasRef.current;
      if (canvas) {
        step(0.86);
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
          canvas.width = w * dpr; canvas.height = h * dpr;
        }
        const ctx = canvas.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        const { scale, ox, oy } = viewRef.current;
        const sim = simRef.current;
        const focus = hover ?? selected;
        const searchHit = search.trim()
          ? new Set(sim.nodes.filter((n) => n.label.toLowerCase().includes(search.trim().toLowerCase())).map((n) => n.id))
          : null;
        const highlightedIds = new Set<string>(focus ? [focus] : []);
        if (focus) {
          for (const index of sim.neighbor.get(focus) ?? []) {
            const neighbor = sim.nodes[index];
            highlightedIds.add(neighbor.id);
            if (neighbor.type === "advisor") {
              for (const next of sim.neighbor.get(neighbor.id) ?? []) highlightedIds.add(sim.nodes[next].id);
            }
          }
        }
        // 边
        const pal = palette();
        ctx.lineWidth = 1;
        for (const e of sim.edges) {
          const a = sim.nodes[e.a], b = sim.nodes[e.b];
          const active = !focus || (highlightedIds.has(a.id) && highlightedIds.has(b.id));
          const hit = searchHit && (searchHit.has(a.id) || searchHit.has(b.id));
          ctx.strokeStyle = pal.edge;
          ctx.globalAlpha = active ? (hit ? 0.85 : a.type === "school" ? 0.4 : 0.16) : 0.025;
          ctx.beginPath();
          ctx.moveTo(ox + a.x * scale, oy + a.y * scale);
          ctx.lineTo(ox + b.x * scale, oy + b.y * scale);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        // 节点
        for (const n of sim.nodes) {
          const meta = TYPE_META[n.type] ?? TYPE_META.student;
          const px = ox + n.x * scale, py = oy + n.y * scale;
          if (px < -40 || py < -40 || px > w + 40 || py > h + 40) continue;
          const dimmed = (focus ? !highlightedIds.has(n.id) : n.type === "student") && !(searchHit && searchHit.has(n.id));
          const highlighted = n.id === selected || n.id === hover || !!searchHit?.has(n.id);
          ctx.globalAlpha = dimmed ? (focus ? 0.09 : 0.28) : 1;
          const radius = Math.max(2.5, meta.r * scale);
          ctx.beginPath();
          ctx.arc(px, py, radius, 0, Math.PI * 2);
          ctx.fillStyle = n.type === "school" ? "#fff" : n.type === "advisor" ? pal.advisor : pal.student;
          ctx.fill();
          const logo = n.type === "school" ? schoolImage(n.label) : null;
          if (logo) {
            ctx.save();
            ctx.clip();
            ctx.drawImage(logo, px - radius, py - radius, radius * 2, radius * 2);
            ctx.restore();
          } else {
            ctx.fillStyle = "#fff";
            ctx.font = `600 ${Math.max(4, 12 * scale)}px "Smiley Moon", "MiSans", sans-serif`;
            ctx.textAlign = "center"; ctx.textBaseline = "middle";
            if (radius >= 7) ctx.fillText(n.label.slice(0, 1), px, py);
            ctx.textBaseline = "alphabetic";
          }
          ctx.beginPath(); ctx.arc(px, py, radius, 0, Math.PI * 2);
          ctx.lineWidth = highlighted ? 2.5 : Math.max(0.8, scale);
          ctx.strokeStyle = pal[meta.token];
          ctx.stroke();
          if (highlighted) {
            ctx.beginPath(); ctx.arc(px, py, radius + 4, 0, Math.PI * 2);
            ctx.lineWidth = 2; ctx.strokeStyle = pal.focus;
            ctx.stroke();
          }
          if (showLabels && !dimmed && (highlighted || (n.type === "school" && scale > 0.75) || (n.type === "advisor" && scale > 1) || scale > 1.25)) {
            ctx.font = `${Math.max(9, 11 * scale)}px system-ui`;
            ctx.fillStyle = highlighted ? pal.labelStrong : pal.label;
            ctx.textAlign = "center";
            const text = n.label.length > 14 ? n.label.slice(0, 13) + "…" : n.label;
            ctx.fillText(`${t(meta.name)} · ${text}`, px, py + radius + 14);
          }
          ctx.globalAlpha = 1;
        }
      }
      rafRef.current = requestAnimationFrame(render);
    };
    rafRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafRef.current);
  }, [selected, hover, search, showLabels, payload]);

  const pick = (mx: number, my: number): number | null => {
    const { nodes } = simRef.current;
    const { scale, ox, oy } = viewRef.current;
    let best: number | null = null, bestD = 20 * 20;
    nodes.forEach((n, i) => {
      const dx = ox + n.x * scale - mx, dy = oy + n.y * scale - my;
      const d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  };

  const zoomAtCenter = (factor: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const v = viewRef.current;
    const x = canvas.clientWidth / 2, y = canvas.clientHeight / 2;
    const scale = Math.max(0.08, Math.min(3, v.scale * factor));
    v.ox = x - ((x - v.ox) / v.scale) * scale;
    v.oy = y - ((y - v.oy) / v.scale) * scale;
    v.scale = scale;
  };

  const detail = useMemo(() => {
    if (!selected || !payload) return null;
    const src = payload.nodes.find((node) => node.id === selected);
    if (!src) return null;
    const ids = new Set<string>();
    for (const edge of payload.edges) {
      if (edge.from === selected) ids.add(edge.to);
      if (edge.to === selected) ids.add(edge.from);
    }
    const neighbors = payload.nodes.filter((node) => ids.has(node.id));
    return { node: { ...src, title: src.title ?? "", score: src.score ?? 0 }, neighbors, src };
  }, [selected, payload]);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-outline-variant px-4 py-2.5">
        <Icon name="account_tree" size={17} className="text-on-surface-variant" />
        <span className="text-title">{t("师生图谱")}</span>
        {payload && (
          <span className="text-label text-on-surface-variant">
            {t("学生 {a} · 导师 {b} · 学校 {c}", { a: payload.counts.students, b: payload.counts.advisors, c: payload.counts.schools })}
          </span>
        )}
        <Button variant="text" className="ml-auto h-8 px-2 text-label" onClick={() => setShowLabels(!showLabels)}>
          {showLabels ? t("隐藏标签") : t("显示标签")}
        </Button>
        <Button variant="tonal" icon="refresh" className="h-8 px-3 text-label" onClick={load}>{t("刷新")}</Button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="flex max-h-72 min-h-0 flex-col border-b border-outline-variant bg-surface-lowest lg:max-h-none lg:border-b-0 lg:border-r">
          <div className="shrink-0 border-b border-outline-variant p-3">
            <div className="flex items-center gap-2 rounded-md border border-outline-variant bg-surface px-3">
              <Icon name="search" size={17} className="shrink-0 text-on-surface-variant" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} aria-label={t("搜索学校 / 导师 / 学生")} placeholder={t("搜索学校 / 导师 / 学生")}
                className="h-9 min-w-0 flex-1 bg-transparent text-body-sm outline-none" />
              {search && <button type="button" onClick={() => setSearch("")} aria-label={t("清空搜索")} className="text-on-surface-variant hover:text-on-surface"><Icon name="close" size={15} /></button>}
            </div>
          <div className="mt-3 grid grid-cols-4 gap-1">
            {(["all", "school", "advisor", "student"] as const).map((kind) => (
              <button key={kind} type="button" onClick={() => setTypeFilter(kind)} aria-pressed={typeFilter === kind}
                className={`rounded-md px-1 py-1.5 text-label ${typeFilter === kind ? "bg-primary text-on-primary" : "bg-surface-low text-on-surface-variant hover:bg-surface-high"}`}>
                {t(kind === "all" ? "全部" : TYPE_META[kind].name)}
              </button>
            ))}
          </div>
            <p className="mt-2 text-label tabular-nums text-on-surface-variant">{t("展示 {n} 个实体", { n: searchResults.length })}</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {groupedResults.map(({ type, nodes }) => (
              <section key={type} aria-label={t(TYPE_META[type].name)}>
                <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-outline-variant bg-surface-lowest/95 px-2 py-2 backdrop-blur-sm">
                  <Icon name={type === "school" ? "school" : type === "advisor" ? "supervisor_account" : "person"} size={16} className="text-primary" />
                  <h2 className="text-label font-semibold">{t(TYPE_META[type].name)}</h2>
                  <span className="ml-auto text-label tabular-nums text-on-surface-variant">{nodes.length}</span>
                </div>
                <div className="space-y-0.5 py-1">
                  {nodes.map((node) => {
                    const logo = type === "school" ? getSchoolLogo(node.label) : null;
                    return <button key={node.id} type="button" onClick={() => setSelected(node.id)} aria-pressed={selected === node.id}
                      className={`flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors hover:bg-surface-low ${selected === node.id ? "bg-primary-container text-on-primary-container" : "text-on-surface"}`}>
                      <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-surface-low text-label font-semibold">
                        {logo ? <img src={logo} alt="" className="size-7 object-contain" /> : <Icon name={type === "school" ? "school" : type === "advisor" ? "person" : "badge"} size={17} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block break-words text-body-sm font-medium leading-5">{node.label}</span>
                        {node.title && type === "advisor" && <span className="block truncate text-label text-on-surface-variant">{node.title}</span>}
                        {node.school && type === "student" && <span className="block truncate text-label text-on-surface-variant">{node.school}</span>}
                      </span>
                      <span className="shrink-0 rounded-full bg-surface-low px-1.5 py-0.5 text-label tabular-nums text-on-surface-variant">{relationCounts.get(node.id) ?? 0}</span>
                    </button>;
                  })}
                </div>
              </section>
            ))}
            {!searchResults.length && !loading && <p className="px-2 py-8 text-center text-body-sm text-on-surface-variant">{t("没有匹配的实体")}</p>}
          </div>
        </aside>
        <div className="relative min-h-[360px] lg:min-h-0">
        <canvas
          ref={canvasRef}
          className="h-full w-full cursor-pointer"
          onMouseDown={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
            dragRef.current = hit !== null ? { node: hit, panning: false, moved: false, startX: e.clientX, startY: e.clientY, lastX: e.clientX, lastY: e.clientY }
                                           : { node: null, panning: true, moved: false, startX: e.clientX, startY: e.clientY, lastX: e.clientX, lastY: e.clientY };
          }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const drag = dragRef.current;
            if ((drag.node !== null || drag.panning) && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 4) drag.moved = true;
            if (drag.node !== null) {
              if (drag.moved) {
                const n = simRef.current.nodes[drag.node];
                n.x = (e.clientX - rect.left - viewRef.current.ox) / viewRef.current.scale;
                n.y = (e.clientY - rect.top - viewRef.current.oy) / viewRef.current.scale;
                n.vx = n.vy = 0;
              }
            } else if (drag.panning) {
              if (drag.moved) {
                viewRef.current.ox += e.clientX - drag.lastX;
                viewRef.current.oy += e.clientY - drag.lastY;
              }
            } else {
              const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
              setHover(hit !== null ? simRef.current.nodes[hit].id : null);
            }
            drag.lastX = e.clientX; drag.lastY = e.clientY;
          }}
          onMouseUp={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
            if (!dragRef.current.moved && hit !== null && dragRef.current.node === hit) {
              setSelected((cur) => (cur === simRef.current.nodes[hit].id ? null : simRef.current.nodes[hit].id));
            }
            if (!dragRef.current.moved && hit === null) setSelected(null);
            dragRef.current = { node: null, panning: false, moved: false, startX: 0, startY: 0, lastX: 0, lastY: 0 };
          }}
          onMouseLeave={() => { setHover(null); dragRef.current = { node: null, panning: false, moved: false, startX: 0, startY: 0, lastX: 0, lastY: 0 }; }}
          onWheel={(e) => {
            e.preventDefault();
            const rect = e.currentTarget.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            const v = viewRef.current;
            const factor = e.deltaY < 0 ? 1.12 : 0.89;
            const ns = Math.max(0.08, Math.min(3, v.scale * factor));
            v.ox = mx - ((mx - v.ox) / v.scale) * ns;
            v.oy = my - ((my - v.oy) / v.scale) * ns;
            v.scale = ns;
          }}
        />
        <div className="pointer-events-none absolute left-3 top-3 flex gap-2 text-label font-medium text-on-surface-variant">
          {(["school", "advisor", "student"] as const).map((type, i) => <span key={type} className="rounded-full border border-outline-variant bg-surface-lowest/90 px-2.5 py-1 shadow-sm">{i + 1} · {t(TYPE_META[type].name)}</span>)}
        </div>
        {/* 图例 */}
        <div className="absolute bottom-3 left-3 flex gap-3 rounded-full bg-surface-lowest/90 px-3 py-1.5 text-label text-on-surface-variant shadow-sm">
          {Object.entries(TYPE_META).map(([k, m]) => (
          <span key={k} className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full" style={{ background: palette()[m.token] }} />
              {t(m.name)}
            </span>
          ))}
        </div>
        <div className="absolute bottom-3 right-3 flex gap-1 rounded-full border border-outline-variant bg-surface-lowest p-1 shadow-sm">
          <Button variant="text" icon="remove" className="h-7 min-w-7 px-1" onClick={() => zoomAtCenter(0.8)} />
          <Button variant="text" icon="add" className="h-7 min-w-7 px-1" onClick={() => zoomAtCenter(1.2)} />
          <Button variant="text" icon="center_focus_strong" className="h-7 min-w-7 px-1" onClick={() => fitRef.current()} />
        </div>
        {/* 选中详情 */}
        {detail && (
          <div className="absolute top-3 right-3 w-64 rounded-lg border border-outline-variant bg-surface-lowest p-3 shadow-lg">
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: palette()[(TYPE_META[detail.node.type] ?? TYPE_META.student).token] }} />
              <span className="min-w-0 flex-1 truncate text-title font-bold">{detail.node.label}</span>
              <button className="cursor-pointer text-on-surface-variant hover:text-on-surface" onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="mt-0.5 text-label text-on-surface-variant">{t(TYPE_META[detail.node.type]?.name ?? detail.node.type)}</div>
            {detail.node.title && <p className="mt-1.5 text-label leading-4 text-on-surface-variant">{detail.node.title}</p>}
            {detail.node.school && <p className="mt-1.5 text-label leading-4 text-on-surface-variant">{detail.node.school}</p>}
            {detail.node.type === "student" && detail.node.score > 0 && (
              <p className="mt-1.5 text-label">{t("盲评分：{v}", { v: detail.node.score })}</p>
            )}
            {detail.neighbors.length > 0 && (
              <div className="mt-2 border-t border-outline-variant pt-2">
                <p className="text-label font-medium text-on-surface-variant">{t("关联（{n}）", { n: detail.neighbors.length })}</p>
                <div className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
                  {detail.neighbors.map((nb) => (
                    <button key={nb.id} className="block w-full cursor-pointer truncate text-left text-label text-on-surface hover:text-primary"
                      onClick={() => setSelected(nb.id)}>
                      · {t(TYPE_META[nb.type]?.name ?? nb.type)}：{nb.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {loading && <div className="absolute inset-0 flex items-center justify-center bg-surface-lowest/60 text-body-sm text-on-surface-variant">{t("加载中…")}</div>}
        </div>
      </div>
    </div>
  );
}
