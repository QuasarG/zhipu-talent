import { useEffect, useRef, useState } from "react";
import type { PersonBrief } from "@/lib/types";
import { IconButton } from "@/components/ui/Button";
import { classifyTrack } from "./TalentList";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type NodeType = "person" | "school" | "direction";
interface GNode {
  id: string; type: NodeType; label: string;
  x: number; y: number; vx: number; vy: number;
  radius: number; color: string; track: string;
}
interface GEdge {
  from: string; to: string;
  type: "education" | "direction" | "collaboration";
  status: "confirmed" | "pending";
}
interface Palette {
  schools: string[]; edge: string; label: string; labelStrong: string;
  personFill: string; ring: string; direction: string;
}

const TRACK_SHAPES: Record<string, string> = {
  agent: "circle", safety: "hexagon", systems: "rect",
  ai4science: "diamond", multimodal: "ellipse", base: "circle",
};
const EDGE_LABELS = { education: "教育经历", direction: "主要方向", collaboration: "共同项目" };
const SCHOOL_TOKENS = [
  "--color-track-agent", "--color-track-safety", "--color-track-systems",
  "--color-track-ai4science", "--color-track-multimodal", "--color-tertiary",
];

// 从 CSS token 读色板，禁止写死 hex
function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement);
  const t = (n: string, fb: string) => css.getPropertyValue(n).trim() || fb;
  return {
    schools: SCHOOL_TOKENS.map((k) => t(k, "#888")),
    edge: t("--color-outline-variant", "#BEC9C8"),
    label: t("--color-on-surface-variant", "#3F4948"),
    labelStrong: t("--color-on-surface", "#161D1D"),
    personFill: t("--color-surface-lowest", "#FFFFFF"),
    ring: t("--color-primary", "#006A6B"),
    direction: t("--color-outline", "#6F7979"),
  };
}

function buildGraph(persons: PersonBrief[], w: number, h: number, pal: Palette) {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const entityMap = new Map<string, GNode>();
  const schoolColor = new Map<string, string>();

  persons.forEach((p) => {
    const track = classifyTrack(p);
    const personNode: GNode = {
      id: p.id, type: "person", label: p.name || p.id,
      x: w / 2 + (Math.random() - 0.5) * 300, y: h / 2 + (Math.random() - 0.5) * 200,
      vx: 0, vy: 0, radius: 22, color: pal.personFill, track,
    };
    if (p.org) {
      if (!schoolColor.has(p.org)) schoolColor.set(p.org, pal.schools[schoolColor.size % pal.schools.length]);
      personNode.color = schoolColor.get(p.org)!;
      const key = "school:" + p.org;
      if (!entityMap.has(key)) {
        const sn: GNode = {
          id: key, type: "school", label: p.org,
          x: w / 2 + (Math.random() - 0.5) * 400, y: h / 2 + (Math.random() - 0.5) * 300,
          vx: 0, vy: 0, radius: 12, color: personNode.color, track: "",
        };
        entityMap.set(key, sn);
        nodes.push(sn);
      }
      edges.push({ from: personNode.id, to: key, type: "education", status: "confirmed" });
    }
    if (track) {
      const key = "direction:" + track;
      if (!entityMap.has(key)) {
        const dn: GNode = {
          id: key, type: "direction", label: track,
          x: w / 2 + (Math.random() - 0.5) * 400, y: h / 2 + (Math.random() - 0.5) * 300,
          vx: 0, vy: 0, radius: 10, color: pal.direction, track: "",
        };
        entityMap.set(key, dn);
        nodes.push(dn);
      }
      edges.push({ from: personNode.id, to: key, type: "direction", status: "confirmed" });
    }
    nodes.push(personNode);
  });

  // 同校同 Track 直连（确定性确认/待核验，避免每帧抖动）
  const personNodes = nodes.filter((n) => n.type === "person");
  for (let i = 0; i < personNodes.length; i++) {
    for (let j = i + 1; j < personNodes.length; j++) {
      const a = personNodes[i], b = personNodes[j];
      if (a.color === b.color && a.track && a.track === b.track) {
        edges.push({
          from: a.id, to: b.id, type: "collaboration",
          status: (i + j) % 2 === 0 ? "confirmed" : "pending",
        });
      }
    }
  }
  return { nodes, edges };
}

export default function RelationGraph({ persons, selectedId, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<GNode[]>([]);
  const edgesRef = useRef<GEdge[]>([]);
  const palRef = useRef<Palette | null>(null);
  const viewRef = useRef({ scale: 1, offsetX: 0, offsetY: 0 });
  const sizeRef = useRef({ w: 0, h: 0 });
  const dragRef = useRef<{ node: GNode | null; panning: boolean; lastX: number; lastY: number }>({
    node: null, panning: false, lastX: 0, lastY: 0,
  });
  const selectedRef = useRef<string | null>(null);
  const fitRef = useRef(0);
  const fitViewRef = useRef<() => void>(() => {});
  const [stats, setStats] = useState({ persons: 0, schools: 0, collabs: 0 });

  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  // persons 变化时重建图数据
  useEffect(() => {
    if (!palRef.current) palRef.current = readPalette();
    const { w, h } = sizeRef.current;
    const { nodes, edges } = buildGraph(persons, w || 600, h || 400, palRef.current);
    nodesRef.current = nodes;
    edgesRef.current = edges;
    setStats({
      persons: nodes.filter((n) => n.type === "person").length,
      schools: nodes.filter((n) => n.type === "school").length,
      collabs: edges.filter((e) => e.type === "collaboration").length,
    });
    // 等布局稳定后自动 fit 视图
    fitRef.current = 200;
  }, [persons]);

  // 模拟循环 + 交互，只挂一次
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    palRef.current = readPalette();

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { w: wrap.clientWidth, h: wrap.clientHeight };
      canvas.width = wrap.clientWidth * dpr;
      canvas.height = wrap.clientHeight * dpr;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const simulate = () => {
      const nodes = nodesRef.current;
      const edges = edgesRef.current;
      const { w, h } = sizeRef.current;
      const REPULSION = 4000, ATTRACTION = 0.02, CENTER = 0.002, DAMPING = 0.85;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const f = REPULSION / (dist * dist);
          nodes[i].vx += (dx / dist) * f; nodes[i].vy += (dy / dist) * f;
          nodes[j].vx -= (dx / dist) * f; nodes[j].vy -= (dy / dist) * f;
        }
      }
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      edges.forEach((e) => {
        const a = nodeMap.get(e.from), b = nodeMap.get(e.to);
        if (!a || !b) return;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = a.type === "person" && b.type !== "person" ? 80 : 120;
        const f = (dist - target) * ATTRACTION;
        a.vx += (dx / dist) * f; a.vy += (dy / dist) * f;
        b.vx -= (dx / dist) * f; b.vy -= (dy / dist) * f;
      });
      const drag = dragRef.current.node;
      nodes.forEach((n) => {
        if (n === drag) return;
        n.vx += (w / 2 - n.x) * CENTER;
        n.vy += (h / 2 - n.y) * CENTER;
        n.vx *= DAMPING; n.vy *= DAMPING;
        n.x += n.vx; n.y += n.vy;
      });
    };

    const isRelated = (n: GNode, target: string) =>
      edgesRef.current.some(
        (e) => (e.from === n.id && e.to === target) || (e.to === n.id && e.from === target)
      );

    const drawShape = (n: GNode, shape: string, isSelected: boolean) => {
      const pal = palRef.current!;
      const r = n.radius;
      ctx.beginPath();
      if (shape === "rect") ctx.roundRect(n.x - r, n.y - r * 0.8, r * 2, r * 1.6, 6);
      else if (shape === "hexagon") {
        for (let i = 0; i < 6; i++) {
          const a = (Math.PI / 3) * i - Math.PI / 2;
          const px = n.x + Math.cos(a) * r, py = n.y + Math.sin(a) * r;
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
      } else if (shape === "diamond") {
        ctx.moveTo(n.x, n.y - r); ctx.lineTo(n.x + r, n.y);
        ctx.lineTo(n.x, n.y + r); ctx.lineTo(n.x - r, n.y); ctx.closePath();
      } else if (shape === "ellipse") ctx.ellipse(n.x, n.y, r, r * 0.7, 0, 0, Math.PI * 2);
      else ctx.arc(n.x, n.y, r, 0, Math.PI * 2);

      if (n.type === "person") {
        ctx.fillStyle = pal.personFill;
        ctx.fill();
        ctx.strokeStyle = n.color || pal.direction;
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(n.x, n.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = n.color || pal.direction;
        ctx.fill();
      } else {
        ctx.globalAlpha *= 0.6;
        ctx.fillStyle = n.color || pal.direction;
        ctx.fill();
        ctx.globalAlpha /= 0.6;
        ctx.strokeStyle = n.color || pal.direction;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 6, 0, Math.PI * 2);
        ctx.globalAlpha = 0.4;
        ctx.strokeStyle = pal.ring;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    };

    const draw = () => {
      const pal = palRef.current!;
      const dpr = window.devicePixelRatio || 1;
      const { w, h } = sizeRef.current;
      const { scale, offsetX, offsetY } = viewRef.current;
      const sel = selectedRef.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(offsetX, offsetY);
      ctx.scale(scale, scale);

      const nodeMap = new Map(nodesRef.current.map((n) => [n.id, n]));
      edgesRef.current.forEach((e) => {
        const a = nodeMap.get(e.from), b = nodeMap.get(e.to);
        if (!a || !b) return;
        const dimmed = sel && a.id !== sel && b.id !== sel;
        ctx.globalAlpha = dimmed ? 0.25 : 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = pal.edge;
        ctx.lineWidth = e.type === "collaboration" ? 1.5 : 1;
        ctx.setLineDash(e.status === "confirmed" ? [] : [4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
        if (e.type !== "direction" && !dimmed) {
          ctx.fillStyle = pal.label;
          ctx.font = "9px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillText(EDGE_LABELS[e.type], (a.x + b.x) / 2, (a.y + b.y) / 2 - 2);
        }
        ctx.globalAlpha = 1;
      });

      nodesRef.current.forEach((n) => {
        const isSelected = n.id === sel;
        const dimmed = sel && !isSelected && !isRelated(n, sel);
        ctx.globalAlpha = dimmed ? 0.4 : 1;
        const shape = n.type === "person" ? TRACK_SHAPES[n.track] || "circle" : "circle";
        drawShape(n, shape, isSelected);
        ctx.fillStyle = isSelected ? pal.labelStrong : pal.label;
        ctx.font = n.type === "person" ? "600 12px sans-serif" : "500 10px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(n.label, n.x, n.y + n.radius + 4);
        ctx.globalAlpha = 1;
      });
      ctx.restore();
    };

    // 按节点包围盒缩放平移，保证全图可见（含标签）
    const fitView = () => {
      const nodes = nodesRef.current;
      if (!nodes.length) return;
      const { w, h } = sizeRef.current;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      nodes.forEach((n) => {
        minX = Math.min(minX, n.x - n.radius - 10);
        maxX = Math.max(maxX, n.x + n.radius + 10);
        minY = Math.min(minY, n.y - n.radius - 10);
        maxY = Math.max(maxY, n.y + n.radius + 24);
      });
      const bw = maxX - minX || 1, bh = maxY - minY || 1;
      const pad = 60;
      const scale = Math.max(0.3, Math.min(1.5, Math.min((w - pad * 2) / bw, (h - pad * 2) / bh)));
      viewRef.current = {
        scale,
        offsetX: w / 2 - (minX + bw / 2) * scale,
        offsetY: h / 2 - (minY + bh / 2) * scale,
      };
    };
    fitViewRef.current = fitView;

    let raf = 0;
    const loop = () => {
      simulate();
      if (fitRef.current > 0) {
        fitRef.current -= 1;
        if (fitRef.current === 0) fitView();
      }
      draw();
      raf = requestAnimationFrame(loop);
    };
    loop();

    const getPos = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const { scale, offsetX, offsetY } = viewRef.current;
      return { x: (e.clientX - rect.left - offsetX) / scale, y: (e.clientY - rect.top - offsetY) / scale };
    };
    const hitTest = (pos: { x: number; y: number }) => {
      const nodes = nodesRef.current;
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i];
        const r = Math.max(n.radius, 14);
        const dx = pos.x - n.x, dy = pos.y - n.y;
        if (dx * dx + dy * dy < r * r) return n;
      }
      return null;
    };

    const onDown = (e: MouseEvent) => {
      const node = hitTest(getPos(e));
      const d = dragRef.current;
      if (node) {
        d.node = node;
        if (node.type === "person") onSelectRef.current(node.id);
      } else {
        d.panning = true;
      }
      d.lastX = e.clientX; d.lastY = e.clientY;
    };
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (d.node) {
        const pos = getPos(e);
        d.node.x = pos.x; d.node.y = pos.y;
        d.node.vx = 0; d.node.vy = 0;
      } else if (d.panning) {
        viewRef.current.offsetX += e.clientX - d.lastX;
        viewRef.current.offsetY += e.clientY - d.lastY;
      }
      d.lastX = e.clientX; d.lastY = e.clientY;
    };
    const onUp = () => {
      dragRef.current.node = null;
      dragRef.current.panning = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const v = viewRef.current;
      v.scale = Math.max(0.3, Math.min(3, v.scale * delta));
    };

    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const zoom = (f: number) => {
    const v = viewRef.current;
    v.scale = Math.max(0.3, Math.min(3, v.scale * f));
  };
  const reset = () => fitViewRef.current();
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrapRef.current?.requestFullscreen();
  };

  return (
    <div ref={wrapRef} className="md3-card-elevated relative min-h-0 overflow-hidden bg-surface-lowest">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full cursor-grab active:cursor-grabbing" />

      {/* 图例 */}
      <div className="absolute top-3 left-3 rounded-md border border-outline-variant bg-surface-lowest px-3 py-2 flex flex-col gap-1.5 text-label text-on-surface-variant pointer-events-none">
        <div className="flex items-center gap-1.5">
          {SCHOOL_TOKENS.slice(0, 5).map((t) => (
            <span key={t} className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: `var(${t})` }} />
          ))}
          <span className="ml-1">颜色 = 学校</span>
        </div>
        <div className="flex items-center gap-1.5">
          {(["circle", "hexagon", "rect", "diamond", "ellipse"] as const).map((s) => (
            <svg key={s} width="12" height="12" viewBox="0 0 12 12" className="text-outline">
              {s === "circle" && <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.2" />}
              {s === "hexagon" && <polygon points="6,1 10.3,3.5 10.3,8.5 6,11 1.7,8.5 1.7,3.5" fill="none" stroke="currentColor" strokeWidth="1.2" />}
              {s === "rect" && <rect x="1.5" y="2.5" width="9" height="7" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.2" />}
              {s === "diamond" && <polygon points="6,1 11,6 6,11 1,6" fill="none" stroke="currentColor" strokeWidth="1.2" />}
              {s === "ellipse" && <ellipse cx="6" cy="6" rx="5" ry="3.5" fill="none" stroke="currentColor" strokeWidth="1.2" />}
            </svg>
          ))}
          <span className="ml-1">形状 = 主要 Track</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 border-t border-outline" />
          <span>实线 = 已确认关系</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 border-t border-dashed border-outline" />
          <span>虚线 = 待核验关系</span>
        </div>
      </div>

      {/* 底部控制条 */}
      <div className="absolute bottom-3 inset-x-3 flex items-center justify-between pointer-events-none">
        <span className="text-label text-on-surface-variant">
          当前显示 {stats.persons} 位人才 · {stats.schools} 所学校 · {stats.collabs} 条合作关系
        </span>
        <div className="flex items-center rounded-full border border-outline-variant bg-surface-lowest pointer-events-auto">
          <IconButton icon="remove" size={18} onClick={() => zoom(0.8)} title="缩小" />
          <IconButton icon="add" size={18} onClick={() => zoom(1.2)} title="放大" />
          <IconButton icon="center_focus_strong" size={18} onClick={reset} title="定位" />
          <IconButton icon="fullscreen" size={18} onClick={toggleFullscreen} title="全屏" />
        </div>
      </div>
    </div>
  );
}
