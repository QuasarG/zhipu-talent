import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { getSchoolLogo } from "@/lib/schoolLogos";

interface GNodeData { id: string; type: "student" | "advisor" | "school"; label: string; score?: number; title?: string; status?: string }
interface GEdgeData { from: string; to: string; source: string; confidence: string }
interface GraphPayload { nodes: GNodeData[]; edges: GEdgeData[]; counts: { students: number; advisors: number; schools: number } }

interface SimNode { id: string; type: string; label: string; title: string; score: number; x: number; y: number; vx: number; vy: number }

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
  student: { token: "student", r: 13, name: "学生" },
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

/** 师生知识图谱：简单力导向（斥力+边弹簧+中心引力），Canvas 渲染，点选高亮邻域 */
export default function AdvisorGraph() {
  const { t } = useI18n();
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showLabels, setShowLabels] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<{ nodes: SimNode[]; edges: { a: number; b: number }[]; neighbor: Map<string, Set<number>> }>({ nodes: [], edges: [], neighbor: new Map() });
  const viewRef = useRef({ scale: 1, ox: 0, oy: 0 });
  const rafRef = useRef(0);
  const dragRef = useRef<{ node: number | null; panning: boolean; lastX: number; lastY: number }>({ node: null, panning: false, lastX: 0, lastY: 0 });

  const load = () => {
    setLoading(true);
    api.scholarship.advisorGraph().then((d) => { setPayload(d); setLoading(false); }).catch(() => setLoading(false));
  };
  useEffect(load, []);
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  // 构建模拟
  useEffect(() => {
    if (!payload) return;
    const typeCounts = { school: 0, advisor: 0, student: 0 };
    const nodes: SimNode[] = payload.nodes.map((n) => ({
      id: n.id, type: n.type, label: n.label, title: n.title ?? "", score: n.score ?? 0,
      x: n.type === "school" ? 140 : n.type === "advisor" ? 400 : 660,
      y: 100 + (typeCounts[n.type]++) * 72,
      vx: 0, vy: 0,
    }));
    const idx = new Map(nodes.map((n, i) => [n.id, i]));
    const edges = payload.edges
      .map((e) => ({ a: idx.get(e.from) ?? -1, b: idx.get(e.to) ?? -1 }))
      .filter((e) => e.a >= 0 && e.b >= 0);
    const neighbor = new Map<string, Set<number>>();
    const add = (k: string, v: number) => { (neighbor.get(k) ?? neighbor.set(k, new Set()).get(k)!).add(v); };
    edges.forEach((e) => { add(nodes[e.a].id, e.b); add(nodes[e.b].id, e.a); });
    simRef.current = { nodes, edges, neighbor };
    // 预热迭代让初始布局稳定
    for (let i = 0; i < 120; i++) step(0.9);
  }, [payload]);

  const step = (damping: number) => {
    const { nodes, edges } = simRef.current;
    const N = nodes.length;
    if (!N) return;
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = Math.random(); dy = Math.random(); }
        if (d2 > 160000) continue; // 距离截断（性能）
        const f = 2200 / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
      }
    }
    for (const e of edges) {
      const a = nodes[e.a], b = nodes[e.b];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (d - 110) * 0.012;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const n of nodes) {
      const laneX = n.type === "school" ? 140 : n.type === "advisor" ? 400 : 660;
      n.vx += (laneX - n.x) * 0.006;
      n.vy += (300 - n.y) * 0.0008;
      n.vx *= damping; n.vy *= damping;
      n.x += n.vx; n.y += n.vy;
    }
  };

  // 渲染循环
  useEffect(() => {
    const render = () => {
      const canvas = canvasRef.current;
      if (canvas) {
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
          ? sim.nodes.filter((n) => n.label.toLowerCase().includes(search.trim().toLowerCase())).map((n) => n.id)
          : null;
        const inFocus = (id: string) => {
          if (!focus) return true;
          if (id === focus) return true;
          const ns = sim.neighbor.get(focus);
          return !!ns && sim.nodes.some((n) => n.id === id && ns.has(sim.nodes.indexOf(n)));
        };
        // 边
        const pal = palette();
        ctx.lineWidth = 1;
        for (const e of sim.edges) {
          const a = sim.nodes[e.a], b = sim.nodes[e.b];
          const active = !focus || a.id === focus || b.id === focus;
          const hit = searchHit && (searchHit.includes(a.id) || searchHit.includes(b.id));
          ctx.strokeStyle = pal.edge;
          ctx.globalAlpha = active ? (hit ? 0.95 : 0.5) : 0.07;
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
          const dimmed = (focus && !inFocus(n.id)) && !(searchHit && searchHit.includes(n.id));
          const highlighted = n.id === selected || n.id === hover || (searchHit && searchHit.includes(n.id));
          ctx.globalAlpha = dimmed ? 0.15 : 1;
          const radius = meta.r * Math.max(0.8, scale);
          ctx.beginPath();
          if (n.type === "school") ctx.roundRect(px - radius, py - radius, radius * 2, radius * 2, 5);
          else if (n.type === "advisor") {
            ctx.moveTo(px, py - radius); ctx.lineTo(px + radius, py);
            ctx.lineTo(px, py + radius); ctx.lineTo(px - radius, py); ctx.closePath();
          } else ctx.arc(px, py, radius, 0, Math.PI * 2);
          ctx.fillStyle = pal[meta.token];
          ctx.fill();
          const logo = n.type === "school" ? schoolImage(n.label) : null;
          if (logo) {
            ctx.save();
            ctx.clip();
            ctx.fillStyle = "#fff";
            ctx.fillRect(px - radius + 2, py - radius + 2, radius * 2 - 4, radius * 2 - 4);
            ctx.drawImage(logo, px - radius + 3, py - radius + 3, radius * 2 - 6, radius * 2 - 6);
            ctx.restore();
          } else {
            ctx.fillStyle = "#fff";
            ctx.font = `bold ${Math.max(10, 12 * scale)}px system-ui`;
            ctx.textAlign = "center"; ctx.textBaseline = "middle";
            ctx.fillText(n.label.slice(0, 1), px, py);
            ctx.textBaseline = "alphabetic";
          }
          if (highlighted) {
            ctx.lineWidth = 2.5;
            ctx.strokeStyle = pal.focus;
            ctx.stroke();
          }
          if (showLabels && (scale > 0.75 || n.type !== "student")) {
            ctx.font = `${Math.max(9, 11 * scale)}px system-ui`;
            ctx.fillStyle = highlighted ? pal.labelStrong : pal.label;
            ctx.textAlign = "center";
            const text = n.label.length > 14 ? n.label.slice(0, 13) + "…" : n.label;
            ctx.fillText(`${t(meta.name)} · ${text}`, px, py + radius + 14);
          }
          ctx.globalAlpha = 1;
        }
      }
      step(0.86);
      rafRef.current = requestAnimationFrame(render);
    };
    rafRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafRef.current);
  }, [selected, hover, search, showLabels]);

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

  const detail = useMemo(() => {
    if (!selected) return null;
    const node = simRef.current.nodes.find((n) => n.id === selected);
    if (!node) return null;
    const ns = simRef.current.neighbor.get(selected) ?? new Set<number>();
    const neighbors = simRef.current.nodes.filter((_, i) => ns.has(i)).map((n) => ({ label: n.label, type: n.type }));
    const src = payload?.nodes.find((n) => n.id === selected);
    return { node, neighbors, src };
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
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder={t("搜索姓名…")}
          className="ml-auto h-8 w-44 rounded-full border border-outline bg-surface-lowest px-3 text-body-sm outline-none focus:border-primary"
        />
        <Button variant="text" className="h-8 px-2 text-label" onClick={() => setShowLabels(!showLabels)}>
          {showLabels ? t("隐藏标签") : t("显示标签")}
        </Button>
        <Button variant="tonal" icon="refresh" className="h-8 px-3 text-label" onClick={load}>{t("刷新")}</Button>
      </div>
      <div className="relative min-h-0 flex-1">
        <canvas
          ref={canvasRef}
          className="h-full w-full cursor-pointer"
          onMouseDown={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
            dragRef.current = hit !== null ? { node: hit, panning: false, lastX: e.clientX, lastY: e.clientY }
                                           : { node: null, panning: true, lastX: e.clientX, lastY: e.clientY };
          }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const drag = dragRef.current;
            if (drag.node !== null) {
              const n = simRef.current.nodes[drag.node];
              n.x = (e.clientX - rect.left - viewRef.current.ox) / viewRef.current.scale;
              n.y = (e.clientY - rect.top - viewRef.current.oy) / viewRef.current.scale;
              n.vx = n.vy = 0;
            } else if (drag.panning) {
              viewRef.current.ox += e.clientX - drag.lastX;
              viewRef.current.oy += e.clientY - drag.lastY;
              drag.lastX = e.clientX; drag.lastY = e.clientY;
            } else {
              const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
              setHover(hit !== null ? simRef.current.nodes[hit].id : null);
            }
          }}
          onMouseUp={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
            if (hit !== null && dragRef.current.node === hit) {
              setSelected((cur) => (cur === simRef.current.nodes[hit].id ? null : simRef.current.nodes[hit].id));
            }
            if (dragRef.current.node === null && !dragRef.current.panning) setSelected(null);
            dragRef.current = { node: null, panning: false, lastX: 0, lastY: 0 };
          }}
          onMouseLeave={() => { setHover(null); dragRef.current = { node: null, panning: false, lastX: 0, lastY: 0 }; }}
          onWheel={(e) => {
            e.preventDefault();
            const rect = e.currentTarget.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            const v = viewRef.current;
            const factor = e.deltaY < 0 ? 1.12 : 0.89;
            const ns = Math.max(0.35, Math.min(3, v.scale * factor));
            v.ox = mx - ((mx - v.ox) / v.scale) * ns;
            v.oy = my - ((my - v.oy) / v.scale) * ns;
            v.scale = ns;
          }}
        />
        {/* 图例 */}
        <div className="absolute bottom-3 left-3 flex gap-3 rounded-full bg-surface-lowest/90 px-3 py-1.5 text-label text-on-surface-variant shadow-sm">
          {Object.entries(TYPE_META).map(([k, m]) => (
          <span key={k} className="flex items-center gap-1.5">
              <span className={`inline-block h-3 w-3 ${k === "school" ? "rounded-sm" : k === "advisor" ? "rotate-45 rounded-[2px]" : "rounded-full"}`} style={{ background: palette()[m.token] }} />
              {t(m.name)}
            </span>
          ))}
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
            {detail.node.type === "student" && detail.node.score > 0 && (
              <p className="mt-1.5 text-label">{t("盲评分：{v}", { v: detail.node.score })}</p>
            )}
            {detail.neighbors.length > 0 && (
              <div className="mt-2 border-t border-outline-variant pt-2">
                <p className="text-label font-medium text-on-surface-variant">{t("关联（{n}）", { n: detail.neighbors.length })}</p>
                <div className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
                  {detail.neighbors.map((nb) => (
                    <button key={nb.label + nb.type} className="block w-full cursor-pointer truncate text-left text-label text-on-surface hover:text-primary"
                      onClick={() => {
                        const target = simRef.current.nodes.find((n) => n.label === nb.label && n.type === nb.type);
                        if (target) setSelected(target.id);
                      }}>
                      · {nb.label}
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
  );
}
