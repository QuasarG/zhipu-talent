/* ============================================================================
   关系图谱 Canvas 引擎（模块 15-16）
   原生 Canvas + 简化力导向布局。四类节点 + 共同实体聚类 + 直连边。
   ========================================================================== */

(function () {
  "use strict";

  const canvas = document.getElementById("pool-graph-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const statusEl = document.getElementById("pool-graph-status");

  let nodes = [];
  let edges = [];
  let selectedId = null;
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let isDragging = false;
  let dragNode = null;
  let isPanning = false;
  let lastMouse = { x: 0, y: 0 };

  const SCHOOL_COLORS = ["#2F7D73", "#3B82F6", "#D45D54", "#B7791F", "#8B5CF6", "#0891B2"];
  const TRACK_SHAPES = {
    agent: "circle",
    safety: "hexagon",
    systems: "rect",
    ai4science: "diamond",
    multimodal: "ellipse",
    base: "circle",
  };

  // ---- 数据构建 ----
  function buildGraph(persons) {
    nodes = [];
    edges = [];
    const entityMap = {}; // key → node
    const schoolColorMap = {};
    let schoolIdx = 0;

    persons.forEach((p) => {
      // Person 节点
      const personNode = {
        id: p.id,
        type: "person",
        label: p.name || p.id,
        x: canvas.width / 2 + (Math.random() - 0.5) * 300,
        y: canvas.height / 2 + (Math.random() - 0.5) * 200,
        vx: 0, vy: 0,
        radius: 22,
        color: "#FFFFFF",
        track: window.TalentPool?.classifyTrack(p) || "",
      };

      // School 节点（按 org 聚类）
      const org = p.org || "";
      if (org) {
        const schoolKey = "school:" + org;
        if (!entityMap[schoolKey]) {
          if (!(org in schoolColorMap)) {
            schoolColorMap[org] = SCHOOL_COLORS[schoolIdx % SCHOOL_COLORS.length];
            schoolIdx++;
          }
          entityMap[schoolKey] = {
            id: schoolKey,
            type: "school",
            label: org,
            x: canvas.width / 2 + (Math.random() - 0.5) * 400,
            y: canvas.height / 2 + (Math.random() - 0.5) * 300,
            vx: 0, vy: 0,
            radius: 12,
            color: schoolColorMap[org],
          };
          nodes.push(entityMap[schoolKey]);
        }
        personNode.color = schoolColorMap[org];
        edges.push({
          from: personNode.id,
          to: schoolKey,
          type: "education",
          status: "confirmed",
        });
      }

      // Track 节点（按方向聚类）
      const track = personNode.track;
      if (track) {
        const trackKey = "direction:" + track;
        if (!entityMap[trackKey]) {
          entityMap[trackKey] = {
            id: trackKey,
            type: "direction",
            label: track,
            x: canvas.width / 2 + (Math.random() - 0.5) * 400,
            y: canvas.height / 2 + (Math.random() - 0.5) * 300,
            vx: 0, vy: 0,
            radius: 10,
            color: "#A8B4B8",
          };
          nodes.push(entityMap[trackKey]);
        }
        edges.push({
          from: personNode.id,
          to: trackKey,
          type: "direction",
          status: "confirmed",
        });
      }

      nodes.push(personNode);
    });

    // 简单 Person-Person 直连：同 school + 同 track
    const personNodes = nodes.filter((n) => n.type === "person");
    for (let i = 0; i < personNodes.length; i++) {
      for (let j = i + 1; j < personNodes.length; j++) {
        if (personNodes[i].color === personNodes[j].color &&
            personNodes[i].track === personNodes[j].track &&
            personNodes[i].track) {
          edges.push({
            from: personNodes[i].id,
            to: personNodes[j].id,
            type: "collaboration",
            status: Math.random() > 0.5 ? "confirmed" : "pending",
          });
        }
      }
    }

    if (statusEl) {
      const schools = nodes.filter((n) => n.type === "school").length;
      const dirs = nodes.filter((n) => n.type === "direction").length;
      const collabs = edges.filter((e) => e.type === "collaboration").length;
      statusEl.textContent = `当前显示 ${personNodes.length} 位人才 · ${schools} 所学校 · ${dirs} 个方向 · ${collabs} 条合作关系`;
    }
  }

  // ---- 力导向（简化版）----
  function simulate() {
    const REPULSION = 4000;
    const ATTRACTION = 0.02;
    const CENTER = 0.001;
    const DAMPING = 0.85;

    // 排斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = REPULSION / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        nodes[i].vx += fx; nodes[i].vy += fy;
        nodes[j].vx -= fx; nodes[j].vy -= fy;
      }
    }

    // 边吸引力
    const nodeMap = {};
    nodes.forEach((n) => { nodeMap[n.id] = n; });
    edges.forEach((e) => {
      const a = nodeMap[e.from];
      const b = nodeMap[e.to];
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const targetDist = (a.type === "person" && b.type !== "person") ? 80 : 120;
      const force = (dist - targetDist) * ATTRACTION;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });

    // 向中心收敛 + 阻尼 + 更新位置
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    nodes.forEach((n) => {
      if (n === dragNode) return;
      n.vx += (cx - n.x) * CENTER;
      n.vy += (cy - n.y) * CENTER;
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x += n.vx;
      n.y += n.vy;
    });
  }

  // ---- 渲染 ----
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);

    // 边
    const nodeMap = {};
    nodes.forEach((n) => { nodeMap[n.id] = n; });
    edges.forEach((e) => {
      const a = nodeMap[e.from];
      const b = nodeMap[e.to];
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = e.status === "confirmed" ? "rgba(47,125,115,0.35)" : "rgba(183,121,31,0.35)";
      ctx.lineWidth = e.type === "collaboration" ? 1.5 : 1;
      if (e.status !== "confirmed") ctx.setLineDash([4, 4]);
      else ctx.setLineDash([]);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    // 节点
    nodes.forEach((n) => {
      const isSelected = n.id === selectedId;
      const isDimmed = selectedId && !isSelected && !isRelated(n, selectedId);
      ctx.globalAlpha = isDimmed ? 0.4 : 1;

      const shape = n.type === "person" ? (TRACK_SHAPES[n.track] || "circle") : "circle";
      drawNodeShape(n, shape, isSelected);

      // 标签
      ctx.fillStyle = isSelected ? "#152126" : "#708086";
      ctx.font = n.type === "person" ? "600 12px sans-serif" : "500 10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(n.label, n.x, n.y + n.radius + 4);

      ctx.globalAlpha = 1;
    });

    ctx.restore();
  }

  function isRelated(node, targetId) {
    return edges.some((e) =>
      (e.from === node.id && e.to === targetId) ||
      (e.to === node.id && e.from === targetId)
    );
  }

  function drawNodeShape(n, shape, isSelected) {
    const r = n.radius;
    ctx.beginPath();
    if (shape === "rect") {
      ctx.roundRect(n.x - r, n.y - r * 0.8, r * 2, r * 1.6, 6);
    } else if (shape === "hexagon") {
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 2;
        const px = n.x + Math.cos(angle) * r;
        const py = n.y + Math.sin(angle) * r;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath();
    } else if (shape === "diamond") {
      ctx.moveTo(n.x, n.y - r);
      ctx.lineTo(n.x + r, n.y);
      ctx.lineTo(n.x, n.y + r);
      ctx.lineTo(n.x - r, n.y);
      ctx.closePath();
    } else if (shape === "ellipse") {
      ctx.ellipse(n.x, n.y, r, r * 0.7, 0, 0, Math.PI * 2);
    } else {
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    }

    // 填充
    if (n.type === "person") {
      ctx.fillStyle = "#FFFFFF";
      ctx.fill();
      ctx.strokeStyle = n.color || "#A8B4B8";
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.stroke();
      // 学校色点
      ctx.beginPath();
      ctx.arc(n.x, n.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = n.color || "#A8B4B8";
      ctx.fill();
    } else {
      ctx.fillStyle = n.color || "#A8B4B8";
      ctx.globalAlpha *= 0.6;
      ctx.fill();
      ctx.globalAlpha /= 0.6;
      ctx.strokeStyle = n.color || "#A8B4B8";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    if (isSelected) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, r + 6, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(47,125,115,0.4)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  // ---- 交互 ----
  function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left - offsetX) / scale,
      y: (e.clientY - rect.top - offsetY) / scale,
    };
  }

  function hitTest(pos) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = pos.x - n.x;
      const dy = pos.y - n.y;
      if (dx * dx + dy * dy < n.radius * n.radius) return n;
    }
    return null;
  }

  canvas.addEventListener("mousedown", (e) => {
    const pos = getMousePos(e);
    const node = hitTest(pos);
    if (node) {
      isDragging = true;
      dragNode = node;
      selectedId = node.id;
      window.dispatchEvent(new CustomEvent("graph-node-selected", { detail: node.id }));
    } else {
      isPanning = true;
    }
    lastMouse = { x: e.clientX, y: e.clientY };
  });

  canvas.addEventListener("mousemove", (e) => {
    if (isDragging && dragNode) {
      const pos = getMousePos(e);
      dragNode.x = pos.x;
      dragNode.y = pos.y;
      dragNode.vx = 0;
      dragNode.vy = 0;
    } else if (isPanning) {
      offsetX += e.clientX - lastMouse.x;
      offsetY += e.clientY - lastMouse.y;
    }
    lastMouse = { x: e.clientX, y: e.clientY };
  });

  canvas.addEventListener("mouseup", () => {
    isDragging = false;
    dragNode = null;
    isPanning = false;
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    scale = Math.max(0.3, Math.min(3, scale * delta));
  }, { passive: false });

  // 缩放按钮
  document.getElementById("graph-zoom-in")?.addEventListener("click", () => { scale = Math.min(3, scale * 1.2); });
  document.getElementById("graph-zoom-out")?.addEventListener("click", () => { scale = Math.max(0.3, scale * 0.8); });
  document.getElementById("graph-fit")?.addEventListener("click", () => { scale = 1; offsetX = 0; offsetY = 0; });
  document.getElementById("graph-expand")?.addEventListener("click", () => { scale = 1; offsetX = 0; offsetY = 0; });

  // ---- 监听数据更新 ----
  window.addEventListener("pool-data-updated", (e) => {
    resizeCanvas();
    buildGraph(e.detail || []);
  });

  window.addEventListener("pool-node-selected", (e) => {
    selectedId = e.detail;
  });

  function resizeCanvas() {
    const wrap = canvas.parentElement;
    canvas.width = wrap.clientWidth;
    canvas.height = wrap.clientHeight;
  }

  window.addEventListener("resize", resizeCanvas);

  // ---- 动画循环 ----
  function loop() {
    simulate();
    draw();
    requestAnimationFrame(loop);
  }

  resizeCanvas();
  loop();
})();