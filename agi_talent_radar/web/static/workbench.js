/**
 * Talent Radar Workbench
 * Streaming evaluation, persistent node panel, decoupled multi-task runs.
 */

const NODE_ORDER = ["normalizer", "evidence_extractor", "scorer", "critic", "formatter"];
const NODE_LABELS = {
  normalizer: "脱敏与标准化",
  evidence_extractor: "深度证据挖掘",
  scorer: "跨领域对齐打分",
  critic: "逻辑判官与防幻觉",
  formatter: "结构化组装",
};

const els = {
  drawerToggles: document.querySelectorAll(".drawer-toggle"),
  importInput: document.getElementById("import-file-input"),
  importButton: document.getElementById("import-file-button"),
  progressBox: document.getElementById("import-progress"),
  progressText: document.getElementById("import-progress-text"),
  resumePane: document.getElementById("resume-pane"),
  agentPane: document.getElementById("agent-pane"),
  emptyResume: document.getElementById("empty-resume"),
  emptyAgent: document.getElementById("empty-agent"),
  candidateTemplate: document.getElementById("candidate-card-template"),
  drawers: {
    pending: document.getElementById("drawer-pending"),
    shortlisted: document.getElementById("drawer-shortlisted"),
    alternative: document.getElementById("drawer-alternative"),
  },
  lists: {
    pending: document.getElementById("list-pending"),
    shortlisted: document.getElementById("list-shortlisted"),
    alternative: document.getElementById("list-alternative"),
  },
  counts: {
    pending: document.getElementById("count-pending"),
    shortlisted: document.getElementById("count-shortlisted"),
    alternative: document.getElementById("count-alternative"),
  },
  toast: document.getElementById("toast"),
};

let currentCandidateId = null;
let candidates = {};
let runs = new Map();

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("is-open");
  setTimeout(() => els.toast.classList.remove("is-open"), 3000);
}

function formatScore(score) {
  return score == null ? "—" : score.toString();
}

function clampScore(score) {
  const n = Number(score);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 0;
}

function showRescoreNotice(candidateId, message) {
  const run = runs.get(candidateId);
  if (!run) return;
  run.rescoreMessage = message;

  if (currentCandidateId === candidateId) {
    const feed = document.getElementById("node-feed");
    if (!feed) return;
    const notice = document.createElement("div");
    notice.className = "node-row is-rescore";
    notice.innerHTML = `
      <div class="node-icon">↻</div>
      <div class="node-body"><strong>回炉重打</strong><small>${escapeHtml(message)}</small></div>
    `;
    feed.appendChild(notice);
    feed.scrollTop = feed.scrollHeight;
  }
}

function renderEvidencePopover(target, content, title) {
  const existing = document.querySelector(".evidence-popover");
  if (existing) existing.remove();

  const rect = target.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "evidence-popover";
  popover.innerHTML = `
    <div class="popover-header">
      <strong>${escapeHtml(title || "Evidence")}</strong>
      <button aria-label="Close">×</button>
    </div>
    <div class="popover-body">${content}</div>
  `;
  document.body.appendChild(popover);

  const popRect = popover.getBoundingClientRect();
  let top = rect.bottom + 8;
  let left = rect.left;
  if (left + popRect.width > window.innerWidth) {
    left = Math.max(8, window.innerWidth - popRect.width - 8);
  }
  if (top + popRect.height > window.innerHeight) {
    top = Math.max(8, rect.top - popRect.height - 8);
  }
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;

  popover.querySelector("button").addEventListener("click", () => popover.remove());
  requestAnimationFrame(() => {
    const close = (e) => { if (!popover.contains(e.target)) popover.remove(); };
    document.addEventListener("click", close, { once: true });
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderCandidateCard(candidate) {
  const clone = els.candidateTemplate.content.cloneNode(true);
  const card = clone.querySelector(".candidate-card");
  card.dataset.id = candidate.id;
  card.classList.add(`level-${(candidate.level || "-").toLowerCase()}`);
  card.querySelector(".card-name").textContent = candidate.name || "未命名候选人";
  card.querySelector(".card-role").textContent = candidate.role || "—";
  card.querySelector(".card-level").textContent = candidate.level || "—";
  card.querySelector(".card-category").textContent = candidate.category || "—";
  card.addEventListener("click", () => selectCandidate(candidate.id));

  const evaluateBtn = card.querySelector(".action-evaluate");
  evaluateBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    selectCandidate(candidate.id);
    handleEvaluate(candidate.id);
  });

  const deleteBtn = card.querySelector(".action-delete");
  deleteBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteCandidate(candidate.id);
  });

  return card;
}

function updateLibrary() {
  const groups = { pending: [], shortlisted: [], alternative: [] };
  Object.values(candidates).forEach((c) => {
    const g = groups[c.group || "pending"];
    if (g) g.push(c);
  });

  Object.keys(groups).forEach((group) => {
    const list = els.lists[group];
    list.innerHTML = "";
    groups[group].forEach((c) => list.appendChild(renderCandidateCard(c)));
    els.counts[group].textContent = String(groups[group].length);
  });
}

function openDrawer(group) {
  const drawer = els.drawers[group];
  if (!drawer) return;
  drawer.classList.add("is-open");
  drawer.querySelector(".drawer-toggle").classList.add("is-open");
}

async function loadCandidates() {
  try {
    const res = await fetch("/api/candidates");
    const data = await res.json();
    candidates = {};
    data.forEach((c) => { candidates[c.id] = c; });
    updateLibrary();
  } catch (err) {
    showToast("候选人加载失败：" + err.message);
  }
}

function renderResume(candidate) {
  els.emptyResume.classList.add("hidden");
  els.resumePane.querySelector(".resume-content")?.remove();

  const c = candidate;
  const section = (title, body) => `<section class="resume-section"><h3>${escapeHtml(title)}</h3>${body}</section>`;

  const basicBody = `
    <dl class="info-grid">
      <dt>姓名</dt><dd>${escapeHtml(c.name || "—")}</dd>
      <dt>目标岗位</dt><dd>${escapeHtml(c.role || "—")}</dd>
      <dt>职级</dt><dd>${escapeHtml(c.level || "—")}</dd>
      <dt>方向</dt><dd>${escapeHtml(c.category || "—")}</dd>
      <dt>阶段</dt><dd>${escapeHtml(c.stage || "—")}</dd>
      <dt>分组</dt><dd>${escapeHtml(c.group || "—")}</dd>
      <dt>分类置信度</dt><dd>${Number.isFinite(c.confidence) ? (c.confidence * 100).toFixed(0) + "%" : "—"}</dd>
    </dl>
  `;

  const list = (items) => Array.isArray(items) && items.length ? `<ul>${items.map((i) => `<li>${escapeHtml(String(i))}</li>`).join("")}</ul>` : "<p>无</p>";

  const eduBody = Array.isArray(c.education) && c.education.length
    ? `<div class="item-list">${c.education.map((e) => `
        <div class="item-block">
          <p>${escapeHtml(String(e))}</p>
        </div>
      `).join("")}</div>`
    : "<p>无</p>";

  const directionsBody = Array.isArray(c.directions) && c.directions.length
    ? `<div class="item-list">${c.directions.map((d) => `
        <div class="item-block"><p>${escapeHtml(String(d))}</p></div>
      `).join("")}</div>`
    : "<p>无</p>";

  const projectsBody = Array.isArray(c.projects) && c.projects.length
    ? `<div class="item-list">${c.projects.map((p) => `
        <div class="item-block">
          <h4>${escapeHtml(p.name || "")}</h4>
          <p>${(p.details || []).map((d) => escapeHtml(String(d))).join(" / ")}</p>
        </div>
      `).join("")}</div>`
    : "<p>无</p>";

  const tagsBody = Array.isArray(c.screening_tags) && c.screening_tags.length
    ? `<div class="signal-row">${c.screening_tags.map((t) => `<span class="signal-pill">${escapeHtml(String(t))}</span>`).join("")}</div>`
    : "<p>无</p>";

  const content = document.createElement("div");
  content.className = "resume-content";
  content.innerHTML = [
    section("基础信息", basicBody),
    section("教育背景", eduBody),
    section("研究方向", directionsBody),
    section("项目经验", projectsBody),
    section("核心技能", list(c.skills)),
    section("研究成果", list(c.publications)),
    section("筛选标签", tagsBody),
  ].join("");
  els.resumePane.appendChild(content);
}

function getAgentPaneHTML(candidate) {
  const run = runs.get(candidate.id);
  const hasRun = !!run;
  const isRunning = hasRun && run.controller;
  const result = hasRun ? run.result : candidate.evaluation;
  const state = isRunning ? "running" : (result ? "done" : "ready");

  let nodeRowsHTML = hasRun ? "" : "<small>点击开始评估以查看节点流转</small>";

  let resultHTML = "";
  if (result) {
    const overall = clampScore(result.overall_score);

    const dimensions = Array.isArray(result.dimension_scores) ? result.dimension_scores : [];
    const dimRows = dimensions.map((dim) => {
      const rawScore = typeof dim.score === "number" ? dim.score : 0;
      const score = clampScore((rawScore / 5) * 100);
      const label = dim.label || dim.key || "维度";
      return `
        <div class="score-row">
          <span class="score-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
          <div class="score-bar"><span style="width: ${score}%"></span></div>
          <span class="score-value">${rawScore.toFixed ? rawScore.toFixed(1) : rawScore}</span>
        </div>
      `;
    }).join("");

    const evidenceList = Array.isArray(result.evidence) && result.evidence.length
      ? `<div class="evidence-list">${result.evidence.map((item, index) => {
          const text = item.dimension || item.source || `证据${index + 1}`;
          return `<span class="evidence-link" data-evidence-index="${index}">${escapeHtml(text)}</span>`;
        }).join("")}</div>`
      : "<p>无详细证据</p>";

    const strengths = Array.isArray(result.core_strengths) && result.core_strengths.length
      ? `<ol>${result.core_strengths.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>`
      : "<p>未生成</p>";

    const risks = Array.isArray(result.potential_risks) && result.potential_risks.length
      ? `<ul class="risk-list">${result.potential_risks.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
      : "<p>未生成</p>";

    const questions = Array.isArray(result.interview_questions) && result.interview_questions.length
      ? `<ol>${result.interview_questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ol>`
      : "<p>未生成</p>";

    const cultivation = Array.isArray(result.cultivation_direction) && result.cultivation_direction.length
      ? `<ul>${result.cultivation_direction.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>`
      : "<p>未生成</p>";

    resultHTML = `
      <div class="evaluation-view">
        <div class="score-band"><span>${overall}</span><span>综合匹配分</span></div>
        <div class="result-section"><h3>人才画像</h3><p>${escapeHtml(result.one_liner || "—")}</p></div>
        <div class="result-section"><h3>维度评分</h3><div class="score-list">${dimRows}</div></div>
        <div class="result-section"><h3>核心优势</h3>${strengths}</div>
        <div class="result-section"><h3>风险与待验证</h3>${risks}</div>
        <div class="result-section"><h3>面谈追问</h3>${questions}</div>
        <div class="result-section"><h3>培养方向</h3>${cultivation}</div>
        <div class="result-section"><h3>证据链</h3>${evidenceList}</div>
      </div>
    `;
  }

  const panelOpen = hasRun ? run.panelOpen : true;

  return `
    <div class="agent-content" data-candidate-id="${escapeHtml(candidate.id)}">
      <div class="agent-header">
        <div>
          <h2>${escapeHtml(candidate.name || "候选人")}</h2>
          <p>${escapeHtml(candidate.role || "—")} · ${escapeHtml(candidate.category || "—")}</p>
        </div>
        <div class="agent-header-actions">
          <button class="evaluate-button" id="evaluate-button" data-id="${escapeHtml(candidate.id)}">
            ${isRunning ? "评估中…" : (result ? "重新评估" : "开始评估")}
          </button>
          <button class="collapse-button" id="agent-collapse" type="button" aria-expanded="true">收起</button>
        </div>
      </div>
      <div class="agent-body" id="agent-body">
        <div class="agent-status-bar">
          <span class="state-chip ${state === "running" ? "is-running" : state === "done" ? "is-ready" : "is-ready"}" id="agent-state-chip">
            ${state === "running" ? "RUNNING" : state === "done" ? "DONE" : "READY"}
          </span>
          <button class="node-toggle ${panelOpen ? "is-open" : ""}" id="node-toggle">节点状态</button>
        </div>
        <div class="node-panel ${panelOpen ? "" : "hidden"}" id="node-panel">
          <div class="node-panel-head"><strong>Agent 节点</strong><span id="node-panel-sub">${isRunning ? "流式运行中" : (hasRun ? "已完成" : "未开始")}</span></div>
          <div class="node-feed" id="node-feed">${nodeRowsHTML || "<small>点击开始评估以查看节点流转</small>"}</div>
        </div>
        ${resultHTML}
      </div>
    </div>
  `;
}

function renderAgent(candidate) {
  els.emptyAgent.classList.add("hidden");
  els.agentPane.querySelector(".agent-content")?.remove();

  const temp = document.createElement("div");
  temp.innerHTML = getAgentPaneHTML(candidate);
  while (temp.firstChild) {
    els.agentPane.appendChild(temp.firstChild);
  }

  const evaluateBtn = document.getElementById("evaluate-button");
  evaluateBtn.addEventListener("click", () => handleEvaluate(candidate.id));

  const collapseBtn = document.getElementById("agent-collapse");
  const agentBody = document.getElementById("agent-body");
  collapseBtn.addEventListener("click", () => {
    const expanded = agentBody.classList.toggle("hidden");
    collapseBtn.textContent = expanded ? "展开" : "收起";
    collapseBtn.setAttribute("aria-expanded", String(!expanded));
  });

  const nodeToggle = document.getElementById("node-toggle");
  nodeToggle.addEventListener("click", () => {
    const run = runs.get(candidate.id);
    const panel = document.getElementById("node-panel");
    const open = panel.classList.toggle("hidden");
    nodeToggle.classList.toggle("is-open", !open);
    if (run) run.panelOpen = !open;
  });

  document.querySelectorAll(".evidence-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      const result = candidate.evaluation || runs.get(candidate.id)?.result;
      if (!result) return;
      const index = Number(e.target.dataset.evidenceIndex);
      const item = result.evidence[index];
      if (!item) return;
      const content = `
        <p><strong>维度：</strong>${escapeHtml(item.dimension || "—")}</p>
        <p><strong>来源：</strong>${escapeHtml(item.source || "—")}</p>
        ${item.signals?.length ? `<p><strong>信号：</strong>${item.signals.map((s) => escapeHtml(s)).join(" · ")}</p>` : ""}
        ${typeof item.strength === "number" ? `<p><strong>强度：</strong>${item.strength}/5</p>` : ""}
        <blockquote>${escapeHtml(item.quote || "无引用")}</blockquote>
      `;
      renderEvidencePopover(e.target, content, item.dimension || "证据详情");
    });
  });

  renderNodeFeed(candidate.id);
}

function selectCandidate(candidateId) {
  currentCandidateId = candidateId;
  const candidate = candidates[candidateId];
  if (!candidate) return;

  document.querySelectorAll(".candidate-card").forEach((card) => card.classList.toggle("is-active", card.dataset.id === candidateId));
  renderResume(candidate);
  renderAgent(candidate);
}

async function deleteCandidate(candidateId) {
  const run = runs.get(candidateId);
  if (run && run.controller) {
    run.controller.abort();
    runs.delete(candidateId);
  }
  try {
    const res = await fetch(`/api/candidates/${candidateId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Delete failed");
    delete candidates[candidateId];
    if (currentCandidateId === candidateId) {
      currentCandidateId = null;
      els.resumePane.querySelector(".resume-content")?.remove();
      els.emptyResume.classList.remove("hidden");
      els.agentPane.querySelector(".agent-content")?.remove();
      els.emptyAgent.classList.remove("hidden");
    }
    updateLibrary();
    showToast("候选人已删除");
  } catch (err) {
    showToast("删除失败：" + err.message);
  }
}

function upsertAgentNodeEvent(candidateId, nodeKey, label, message, done) {
  const run = runs.get(candidateId);
  if (!run) return;

  const existing = run.nodeRows.get(nodeKey);
  if (existing) {
    existing.label = label || existing.label;
    existing.message = message || existing.message;
    existing.done = done;
    existing.running = false;
  } else {
    run.nodeRows.set(nodeKey, { label, message, done, running: false });
  }

  // 推进下一个预期节点为 running
  if (done) {
    const index = NODE_ORDER.indexOf(nodeKey);
    if (index >= 0 && index + 1 < NODE_ORDER.length) {
      const nextKey = NODE_ORDER[index + 1];
      if (!run.nodeRows.has(nextKey)) {
        run.nodeRows.set(nextKey, { label: NODE_LABELS[nextKey] || nextKey, message: "正在执行…", done: false, running: true });
      }
    }
  }

  renderNodeFeed(candidateId);
}

function renderNodeFeed(candidateId) {
  if (currentCandidateId !== candidateId) return;
  const run = runs.get(candidateId);
  if (!run) return;

  const feed = document.getElementById("node-feed");
  if (!feed) return;

  feed.innerHTML = "";
  NODE_ORDER.forEach((nodeKey) => {
    const row = run.nodeRows.get(nodeKey);
    if (!row) return;

    const rowEl = document.createElement("div");
    rowEl.className = `node-row ${row.done ? "is-done" : ""} ${row.running ? "is-running" : ""}`;
    rowEl.dataset.node = nodeKey;
    rowEl.innerHTML = `
      <div class="node-icon">${row.done ? "✓" : (row.running ? "" : "·")}</div>
      <div class="node-body">
        <strong>${escapeHtml(row.label)}</strong>
        <small>${escapeHtml(row.message || "等待中…")}</small>
      </div>
    `;
    feed.appendChild(rowEl);
  });

  feed.scrollTop = feed.scrollHeight;

  const sub = document.getElementById("node-panel-sub");
  if (sub) sub.textContent = run.nodeRows.size ? "流式运行中" : "未开始";
}

function finishAgentRun(candidateId, result) {
  const run = runs.get(candidateId);
  if (!run) return;

  run.controller = null;
  run.result = result;
  run.nodeRows.forEach((row) => { row.done = true; row.running = false; });
  candidates[candidateId].evaluation = result;
  candidates[candidateId].group = result && result.overall_score >= 60 ? "shortlisted" : "alternative";

  updateLibrary();
  openDrawer(candidates[candidateId].group);

  if (currentCandidateId === candidateId) {
    renderAgent(candidates[candidateId]);
    showToast("评估完成");
  }
}

function failAgentRun(candidateId, error) {
  const run = runs.get(candidateId);
  if (!run) return;

  run.controller = null;
  run.error = error;

  if (currentCandidateId === candidateId) {
    const chip = document.getElementById("agent-state-chip");
    const btn = document.getElementById("evaluate-button");
    if (chip) {
      chip.className = "state-chip is-error";
      chip.textContent = "ERROR";
    }
    if (btn) btn.disabled = false;
    showToast("评估失败：" + error.message);
  }
}

async function handleEvaluate(candidateId) {
  const candidate = candidates[candidateId];
  if (!candidate) return;

  const existing = runs.get(candidateId);
  if (existing && existing.controller) {
    existing.controller.abort();
    runs.delete(candidateId);
  }

  const run = {
    candidateId,
    controller: new AbortController(),
    nodeRows: new Map(),
    result: null,
    error: null,
    panelOpen: true,
  };
  run.nodeRows.set(NODE_ORDER[0], { label: NODE_LABELS[NODE_ORDER[0]], message: "正在执行…", done: false, running: true });
  runs.set(candidateId, run);

  selectCandidate(candidateId);

  try {
    const res = await fetch(`/api/candidates/${candidateId}/evaluate`, {
      method: "POST",
      signal: run.controller.signal,
      cache: "no-store",
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.length ? lines.pop() : "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const payload = trimmed.slice(6);

        let event;
        try {
          event = JSON.parse(payload);
        } catch (e) {
          continue;
        }

        if (event.type === "node") {
          upsertAgentNodeEvent(candidateId, event.node, event.label, event.message, event.status === "done");
        } else if (event.type === "rescore") {
          showRescoreNotice(candidateId, event.message);
        } else if (event.type === "result") {
          finishAgentRun(candidateId, event.result);
        } else if (event.type === "error") {
          throw new Error(event.message || "评估失败");
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      runs.delete(candidateId);
      if (currentCandidateId === candidateId) renderAgent(candidate);
      return;
    }
    failAgentRun(candidateId, err);
  }
}

function handleImportFile(file) {
  if (!file) return;
  els.importButton.classList.add("is-busy");
  els.progressBox.classList.remove("hidden");
  els.progressText.textContent = "上传简历文件中…";

  const formData = new FormData();
  formData.append("file", file);

  fetch("/api/import-file", { method: "POST", body: formData, cache: "no-store" })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Import failed: ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.length ? lines.pop() : "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          const payload = trimmed.slice(6);
          try {
            const event = JSON.parse(payload);
            if (event.type === "candidate") {
              candidates[event.candidate.id] = event.candidate;
              updateLibrary();
              openDrawer("pending");
              els.progressText.textContent = `已导入 ${event.index} / ${event.total}：${event.candidate.name}`;
            } else if (event.type === "done") {
              els.progressText.textContent = `导入完成：共 ${event.total} 份简历`;
              setTimeout(() => {
                els.progressBox.classList.add("hidden");
                els.importButton.classList.remove("is-busy");
              }, 2000);
              showToast("导入完成");
            } else if (event.type === "error") {
              throw new Error(event.message);
            }
          } catch (e) {
            // skip malformed lines
          }
        }
      }
    })
    .catch((err) => {
      els.progressText.textContent = "导入失败：" + err.message;
      els.importButton.classList.remove("is-busy");
      showToast("导入失败：" + err.message);
    });
}

els.drawerToggles.forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const drawer = toggle.closest(".drawer");
    const open = drawer.classList.toggle("is-open");
    toggle.classList.toggle("is-open", open);
  });
});

els.importInput.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (file) handleImportFile(file);
  els.importInput.value = "";
});

openDrawer("pending");
loadCandidates();
