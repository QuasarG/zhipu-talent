import { useEffect, useRef, useState } from "react";
import type { PersonBrief } from "@/lib/types";
import { IconButton } from "@/components/ui/Button";
import { getSchoolLogo } from "@/lib/schoolLogos";
import { useI18n } from "@/lib/i18n";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** group_id → 分组名（图谱分组节点用） */
  groupName: (groupId: string | null) => string;
}

type NodeType = "person" | "school" | "group";
interface GNode {
  id: string; type: NodeType; label: string; tag: string;
  x: number; y: number; vx: number; vy: number;
  radius: number; color: string;
}
interface GEdge {
  from: string; to: string;
}
interface Palette {
  schools: string[]; group: string; edge: string; label: string; labelStrong: string;
  avatarBg: string; avatarText: string; personFill: string; ring: string; direction: string;
}

const SCHOOL_TOKENS = [
  "--color-track-agent", "--color-track-safety", "--color-track-ai_infra",
  "--color-track-ai4science", "--color-track-multimodal", "--color-tertiary",
];
// 从 CSS token 读色板，禁止写死 hex
function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement);
  const t = (n: string, fb: string) => css.getPropertyValue(n).trim() || fb;
  return {
    schools: SCHOOL_TOKENS.map((k) => t(k, "#888")),
    group: t("--color-tertiary", "#888"),
    edge: t("--color-outline-variant", "#BEC9C8"),
    label: t("--color-on-surface-variant", "#3F4948"),
    labelStrong: t("--color-on-surface", "#161D1D"),
    avatarBg: t("--color-primary-container", "#9BF1F2"),
    avatarText: t("--color-on-primary-container", "#002021"),
    personFill: t("--color-surface-lowest", "#FFFFFF"),
    ring: t("--color-primary", "#006A6B"),
    direction: t("--color-outline", "#6F7979"),
  };
}

// 校徽图片缓存：加载完由 rAF 循环自然重绘，无需额外触发
const logoCache = new Map<string, HTMLImageElement>();
function schoolLogoImage(org: string): HTMLImageElement | null {
  const url = getSchoolLogo(org);
  if (!url) return null;
  let img = logoCache.get(url);
  if (!img) {
    img = new Image();
    img.src = url;
    logoCache.set(url, img);
  }
  return img.complete && img.naturalWidth > 0 ? img : null;
}

/** 人才的关联学校 = 最高学位层级的全部学校（联培也算，几所就绑几所） */
function personTopSchools(p: PersonBrief): string[] {
  if (p.top_schools?.length) return p.top_schools;
  return p.org ? [p.org] : [];
}

function buildGraph(persons: PersonBrief[], w: number, h: number, pal: Palette, groupName: (id: string | null) => string) {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const entityMap = new Map<string, GNode>();
  const schoolColor = new Map<string, string>();
  const colorOf = (school: string) => {
    if (!schoolColor.has(school)) schoolColor.set(school, pal.schools[schoolColor.size % pal.schools.length]);
    return schoolColor.get(school)!;
  };

  const position = (id: string, spreadX: number, spreadY: number) => {
    let hash = 2166136261;
    for (const char of id) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    const angle = ((hash >>> 0) % 360) * Math.PI / 180;
    const radius = 0.35 + (((hash >>> 8) & 255) / 255) * 0.65;
    return { x: w / 2 + Math.cos(angle) * spreadX * radius, y: h / 2 + Math.sin(angle) * spreadY * radius };
  };

  persons.forEach((p) => {
    const topSchools = personTopSchools(p);
    // 头像描边与标签色以学位授予校（org）为准，标签展示全部最高层级学校
    const primary = p.org || topSchools[0] || "";
    const personNode: GNode = {
      id: p.id, type: "person", label: p.display_name || p.name || "未命名", tag: topSchools.join(" · "),
      ...position(`person:${p.id}`, Math.min(260, w * 0.38), Math.min(180, h * 0.34)),
      vx: 0, vy: 0, radius: 20, color: primary ? colorOf(primary) : pal.direction,
    };
    nodes.push(personNode);

    topSchools.forEach((school) => {
      const key = "school:" + school;
      if (!entityMap.has(key)) {
        const sn: GNode = {
          id: key, type: "school", label: school, tag: "",
          ...position(key, Math.min(320, w * 0.44), Math.min(230, h * 0.4)),
          vx: 0, vy: 0, radius: getSchoolLogo(school) ? 16 : 14,
          color: colorOf(school),
        };
        entityMap.set(key, sn);
        nodes.push(sn);
      }
      edges.push({ from: personNode.id, to: key });
    });

    // 分组节点：人才库分组（未分组人不连组）
    const gName = groupName(p.group_id || null);
    if (gName) {
      const key = "group:" + (p.group_id || gName);
      if (!entityMap.has(key)) {
        const gn: GNode = {
          id: key, type: "group", label: gName, tag: "",
          ...position(key, Math.min(190, w * 0.3), Math.min(140, h * 0.28)),
          vx: 0, vy: 0, radius: 12,
          color: pal.group,
        };
        entityMap.set(key, gn);
        nodes.push(gn);
      }
      edges.push({ from: personNode.id, to: key });
    }
  });

  return { nodes, edges };
}

export default function RelationGraph({ persons, selectedId, onSelect, groupName }: Props) {
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
  const [stats, setStats] = useState({ persons: 0, schools: 0, tracks: 0 });
  const { t } = useI18n();
  const tRef = useRef(t);
  // Canvas 字体绘制不会触发 webfont 下载，先显式加载斜月体
  useEffect(() => {
    void document.fonts?.load('600 16px "Smiley Moon"');
  }, []);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  // persons 变化时重建图数据
  useEffect(() => {
    if (!palRef.current) palRef.current = readPalette();
    const { w, h } = sizeRef.current;
    const { nodes, edges } = buildGraph(persons, w || 600, h || 400, palRef.current, groupName);
    nodesRef.current = nodes;
    edgesRef.current = edges;
    setStats({
      persons: nodes.filter((n) => n.type === "person").length,
      schools: nodes.filter((n) => n.type === "school").length,
      tracks: nodes.filter((n) => n.type === "group").length,
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
        const target = 80;
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

    const drawNode = (n: GNode, isSelected: boolean) => {
      const pal = palRef.current!;
      const r = n.radius;
      if (n.type === "person") {
        // 姓氏头像：与列表同款圆形首字
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = pal.avatarBg;
        ctx.fill();
        ctx.strokeStyle = n.color;
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.stroke();
        ctx.fillStyle = pal.avatarText;
        ctx.font = `600 ${Math.round(r * 0.85)}px "Smiley Moon", "MiSans", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText((tRef.current(n.label) || "?").charAt(0), n.x, n.y + 1);
      } else if (n.type === "group") {
        // 分组：始终高亮——primary 实心 + 表面色描边隔离背景，不随选中降透明度
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = pal.ring;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = pal.personFill;
        ctx.stroke();
      } else {
        const logo = schoolLogoImage(n.label);
        if (logo) {
          // 有校徽：白底圆裁剪后贴图
          ctx.save();
          ctx.beginPath();
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
          ctx.fillStyle = pal.personFill;
          ctx.fill();
          ctx.clip();
          ctx.drawImage(logo, n.x - r, n.y - r, r * 2, r * 2);
          ctx.restore();
          ctx.beginPath();
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
          ctx.strokeStyle = n.color;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        } else {
          // 无校徽：和姓氏头像同款的圆形占位，用学校首字 + 学校色
          ctx.beginPath();
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
          ctx.fillStyle = pal.personFill;
          ctx.fill();
          ctx.strokeStyle = n.color;
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.fillStyle = n.color;
          ctx.font = `600 ${Math.round(r * 0.8)}px "Smiley Moon", "MiSans", sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText((n.label || "?").charAt(0), n.x, n.y + 1);
        }
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
        const isGroupEdge = a.type === "group" || b.type === "group";
        const dimmed = sel && !isGroupEdge && a.id !== sel && b.id !== sel;
        ctx.globalAlpha = dimmed ? 0.25 : 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = pal.edge;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.globalAlpha = 1;
      });

      nodesRef.current.forEach((n) => {
        const isSelected = n.id === sel;
        const dimmed = sel && !isSelected && !isRelated(n, sel) && n.type !== "group";
        ctx.globalAlpha = dimmed ? 0.4 : 1;
        drawNode(n, isSelected);
        // 人名 + 学校标签（最高学历学校）；分组标签恒用强色
        ctx.fillStyle = n.type === "group" || isSelected ? pal.labelStrong : pal.label;
        ctx.font = n.type === "person"
          ? '600 12px "Montserrat", "MiSans", sans-serif'
          : n.type === "group"
            ? '700 12px "Montserrat", "MiSans", sans-serif'
            : '500 10px "Montserrat", "MiSans", sans-serif';
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(tRef.current(n.label), n.x, n.y + n.radius + 4);
        if (n.type === "person" && n.tag) {
          ctx.font = '400 10px "Montserrat", "MiSans", sans-serif';
          ctx.fillStyle = pal.label;
          ctx.fillText(n.tag, n.x, n.y + n.radius + 20);
        }
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
        maxY = Math.max(maxY, n.y + n.radius + 34);
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
    <div ref={wrapRef} className="md3-card relative w-full max-w-full min-w-0 min-h-0 overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full cursor-grab active:cursor-grabbing" />

      {/* 图例 */}
      <div className="absolute top-3 left-3 rounded-md border border-outline-variant bg-surface-lowest px-3 py-2 flex flex-col gap-1.5 text-label text-on-surface-variant pointer-events-none">
        <div className="flex items-center gap-1.5">
          {SCHOOL_TOKENS.slice(0, 5).map((t) => (
            <span key={t} className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: `var(${t})` }} />
          ))}
          <span className="ml-1">{t("头像描边颜色 = 学校")}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-primary" />
          <span className="ml-1">{t("实心圆点 = 分组")}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 border-t border-outline" />
          <span>{t("连线 = 教育经历 / Track")}</span>
        </div>
      </div>

      {/* 底部控制条 */}
      <div className="absolute bottom-3 inset-x-3 flex items-center justify-between pointer-events-none">
        <span className="text-label text-on-surface-variant">
          {t("当前显示 {persons} 位人才 · {schools} 所学校 · {tracks} 个 Track", { persons: stats.persons, schools: stats.schools, tracks: stats.tracks })}
        </span>
        <div className="flex items-center rounded-full border border-outline-variant bg-surface-lowest pointer-events-auto">
          <IconButton icon="remove" size={18} onClick={() => zoom(0.8)} title={t("缩小")} />
          <IconButton icon="add" size={18} onClick={() => zoom(1.2)} title={t("放大")} />
          <IconButton icon="center_focus_strong" size={18} onClick={reset} title={t("定位")} />
          <IconButton icon="fullscreen" size={18} onClick={toggleFullscreen} title={t("全屏")} />
        </div>
      </div>
    </div>
  );
}
