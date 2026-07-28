/**
 * Talent Radar Workbench
 * Streaming evaluation, persistent node panel, decoupled multi-task runs.
 */

const { NODE_LABELS, NODE_ORDER, STAGES } = window.AgentGraph;
const BULK_EVALUATION_CONCURRENCY = 3;
const scoringConfig = window.TALENT_SCORING_CONFIG;

const els = {
  drawerToggles: document.querySelectorAll(".drawer-toggle"),
  importInput: document.getElementById("import-file-input"),
  importButton: document.getElementById("import-file-button"),
  bulkEvaluateButton: document.getElementById("bulk-evaluate-pending"),
  bulkConfirmDialog: document.getElementById("bulk-confirm-dialog"),
  bulkConfirmTitle: document.getElementById("bulk-confirm-title"),
  bulkConfirmMessage: document.getElementById("bulk-confirm-message"),
  bulkConfirmCancel: document.getElementById("bulk-confirm-cancel"),
  bulkConfirmSubmit: document.getElementById("bulk-confirm-submit"),
  progressBox: document.getElementById("import-progress"),
  progressText: document.getElementById("import-progress-text"),
  importFileName: document.getElementById("import-file-name"),
  importState: document.getElementById("import-state"),
  importStageList: document.getElementById("import-stage-list"),
  importCancel: document.getElementById("import-cancel"),
  importRetry: document.getElementById("import-retry"),
  resumePane: document.getElementById("resume-pane"),
  agentPane: document.getElementById("agent-pane"),
  emptyResume: document.getElementById("empty-resume"),
  emptyAgent: document.getElementById("empty-agent"),
  candidateTemplate: document.getElementById("candidate-card-template"),
  drawers: {
    pending: document.getElementById("drawer-pending"),
    shortlisted: document.getElementById("drawer-shortlisted"),
    alternative: document.getElementById("drawer-alternative"),
    rejected: document.getElementById("drawer-rejected"),
  },
  lists: {
    pending: document.getElementById("list-pending"),
    shortlisted: document.getElementById("list-shortlisted"),
    alternative: document.getElementById("list-alternative"),
    rejected: document.getElementById("list-rejected"),
  },
  counts: {
    pending: document.getElementById("count-pending"),
    shortlisted: document.getElementById("count-shortlisted"),
    alternative: document.getElementById("count-alternative"),
    rejected: document.getElementById("count-rejected"),
  },
  toast: document.getElementById("toast"),
};

let currentCandidateId = null;
let candidates = {};
let runs = new Map();
let bulkEvaluating = false;
let bulkEvaluationProgress = null;
let importController = null;
let importState = null;
let lastImportFiles = [];

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("is-open");
  setTimeout(() => els.toast.classList.remove("is-open"), 3000);
}

function formatScore(score) {
  return score == null ? "—" : score.toString();
}

function formatPotentialLevel(level) {
  return level ? `初筛 ${level}` : "初筛 —";
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

function evidenceContent(item) {
  return `
    <p><strong>维度：</strong>${escapeHtml(item.dimension || "—")}</p>
    <p><strong>来源：</strong>${escapeHtml(item.source || "—")}</p>
    ${item.signals?.length ? `<p><strong>信号：</strong>${item.signals.map((s) => escapeHtml(s)).join(" · ")}</p>` : ""}
    ${typeof item.strength === "number" ? `<p><strong>强度：</strong>${item.strength}/5</p>` : ""}
    <blockquote>${escapeHtml(item.quote || "无引用")}</blockquote>
  `;
}

function renderEvidenceText(text, evidence) {
  const raw = String(text || "");
  if (!raw) return "";
  const items = Array.isArray(evidence) ? evidence : [];
  const byId = new Map(items.map((item, index) => [String(item.id || `e${index + 1}`), index]));
  let html = escapeHtml(raw);

  items.forEach((item, index) => {
    const quote = String(item.quote || "").trim();
    if (quote && quote.length >= 8 && raw.includes(quote)) {
      const escapedQuote = escapeHtml(quote);
      html = html.replace(
        escapedQuote,
        `<button class="evidence-link evidence-inline evidence-quote" type="button" data-evidence-index="${index}">${escapedQuote}</button>`,
      );
    }
  });

  byId.forEach((index, id) => {
    if (!id) return;
    const pattern = new RegExp(`(${escapeRegExp(id)})`, "g");
    html = html.replace(pattern, `<button class="evidence-link evidence-inline" type="button" data-evidence-index="${index}">$1</button>`);
  });
  return html;
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function evidenceLabel(item, fallback) {
  return item?.id || item?.source || item?.dimension || fallback;
}

function renderCandidateCard(candidate) {
  const clone = els.candidateTemplate.content.cloneNode(true);
  const card = clone.querySelector(".candidate-card");
  card.dataset.id = candidate.id;
  card.classList.add(`level-${(candidate.level || "-").toLowerCase()}`);
  card.classList.toggle("is-active", candidate.id === currentCandidateId);
  card.querySelector(".card-name").textContent = candidate.name || "未命名候选人";
  card.querySelector(".card-role").textContent = candidate.role || "—";
  card.querySelector(".card-level").textContent = formatPotentialLevel(candidate.level);
  card.querySelector(".card-category").textContent = candidate.category || "—";
  card.addEventListener("click", () => selectCandidate(candidate.id));

  const evaluateBtn = card.querySelector(".action-evaluate");
  const run = runs.get(candidate.id);
  const evaluationLocked = !!(run?.queued || run?.controller);
  evaluateBtn.disabled = evaluationLocked;
  evaluateBtn.textContent = run?.queued ? "排队中" : run?.controller ? "评估中" : "评估";
  evaluateBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (evaluationLocked) return;
    await handleEvaluate(candidate.id);
  });

  const deleteBtn = card.querySelector(".action-delete");
  deleteBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteCandidate(candidate.id);
  });

  return card;
}

function updateLibrary() {
  const groups = { pending: [], shortlisted: [], alternative: [], rejected: [] };
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
  updateBulkEvaluateButton(groups.pending.length);
}

function updateBulkEvaluateButton(pendingCount = pendingCandidateIds().length) {
  if (!els.bulkEvaluateButton) return;
  els.bulkEvaluateButton.disabled = pendingCount === 0 || bulkEvaluating;
  if (bulkEvaluating && bulkEvaluationProgress) {
    els.bulkEvaluateButton.textContent = `评估中 ${bulkEvaluationProgress.done}/${bulkEvaluationProgress.total}`;
    return;
  }
  els.bulkEvaluateButton.textContent = bulkEvaluating ? "评估中…" : (pendingCount ? `一键评估 ${pendingCount}` : "一键评估");
}

function pendingCandidateIds() {
  return Object.values(candidates)
    .filter((candidate) => (candidate.group || "pending") === "pending")
    .map((candidate) => candidate.id);
}

function groupForScore(score) {
  const value = Number(score);
  if (value >= scoringConfig.thresholds.shortlisted) return "shortlisted";
  if (value >= scoringConfig.thresholds.alternative) return "alternative";
  return "rejected";
}

function setDrawerOpen(group, open) {
  const drawer = els.drawers[group];
  if (!drawer) return;

  const toggle = drawer.querySelector(".drawer-toggle");
  const body = drawer.querySelector(".drawer-body");
  drawer.classList.toggle("is-open", open);
  toggle?.classList.toggle("is-open", open);
  toggle?.setAttribute("aria-expanded", String(open));
  if (body) body.hidden = !open;
}

function openDrawer(group) {
  Object.keys(els.drawers).forEach((drawerGroup) => {
    setDrawerOpen(drawerGroup, drawerGroup === group);
  });
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

function hasCandidateDetails(candidate) {
  return ["education", "directions", "experiences", "projects", "publications", "skills", "screening_tags"]
    .every((key) => Object.prototype.hasOwnProperty.call(candidate, key));
}

function hasCandidateEvaluation(candidate) {
  return Object.prototype.hasOwnProperty.call(candidate, "evaluation")
    || Object.prototype.hasOwnProperty.call(candidate, "latest_evaluation");
}

function skillClass(skill) {
  const normalized = String(skill || "").toLowerCase().replace(/\s+/g, " ");
  const rules = [
    [/pytorch/, "skill-pytorch"],
    [/python/, "skill-python"],
    [/javascript|\bjs\b/, "skill-javascript"],
    [/typescript|\bts\b/, "skill-typescript"],
    [/\bjava\b/, "skill-java"],
    [/c\+\+/, "skill-cpp"],
    [/cuda/, "skill-cuda"],
    [/triton/, "skill-triton"],
    [/docker/, "skill-docker"],
    [/kubernetes|\bk8s\b/, "skill-kubernetes"],
    [/react/, "skill-react"],
    [/node\.?js/, "skill-node"],
    [/fastapi/, "skill-fastapi"],
    [/rust/, "skill-rust"],
    [/\bgo\b|golang/, "skill-go"],
    [/\bray\b/, "skill-ray"],
    [/tensorflow/, "skill-tensorflow"],
    [/transformers|hugging face/, "skill-huggingface"],
    [/vllm/, "skill-vllm"],
    [/deepspeed/, "skill-deepspeed"],
    [/megatron/, "skill-megatron"],
    [/tensorrt/, "skill-tensorrt"],
    [/opencv/, "skill-opencv"],
    [/\bclip\b/, "skill-clip"],
    [/llava/, "skill-llava"],
    [/qwen-vl/, "skill-qwen"],
    [/paddleocr/, "skill-paddle"],
    [/layoutlm/, "skill-layoutlm"],
    [/playwright/, "skill-playwright"],
    [/\bgit\b|github/, "skill-git"],
    [/\brag\b/, "skill-rag"],
    [/rlhf|rlvr/, "skill-rl"],
    [/sympy/, "skill-sympy"],
    [/\bsql\b/, "skill-sql"],
    [/\bocr\b/, "skill-ocr"],
  ];
  const match = rules.find(([pattern]) => pattern.test(normalized));
  return match ? match[1] : "skill-generic";
}

async function loadCandidateDetail(candidateId) {
  const existing = candidates[candidateId];
  if (existing && hasCandidateDetails(existing) && hasCandidateEvaluation(existing)) return existing;

  const res = await fetch(`/api/candidates/${encodeURIComponent(candidateId)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Detail failed: ${res.status}`);
  const detail = await res.json();
  if (detail.latest_evaluation && !detail.evaluation) {
    detail.evaluation = detail.latest_evaluation;
  }
  const run = runs.get(candidateId);
  const merged = { ...(existing || {}), ...detail };
  if (run?.result) {
    merged.evaluation = run.result;
    merged.latest_evaluation = run.result;
    merged.group = groupForScore(run.result.overall_score);
  }
  candidates[candidateId] = merged;
  return candidates[candidateId];
}

function renderResume(candidate) {
  els.emptyResume.classList.add("hidden");
  els.resumePane.querySelector(".resume-content")?.remove();

  const c = candidate;
  const safeItems = (items) => Array.isArray(items) ? items.filter((item) => String(item || "").trim()) : [];
  const summaryCounts = [
    { label: "教育", value: safeItems(c.education).length },
    { label: "方向", value: safeItems(c.directions).length },
    { label: "经历", value: Array.isArray(c.experiences) ? c.experiences.length : 0 },
    { label: "项目", value: Array.isArray(c.projects) ? c.projects.length : 0 },
    { label: "成果", value: safeItems(c.publications).length },
    { label: "技能", value: safeItems(c.skills).length },
  ];
  const section = (title, body, extraClass = "") => `
    <section class="resume-section ${extraClass}">
      <h3>${escapeHtml(title)}</h3>
      <div class="resume-section-body">${body}</div>
    </section>
  `;

  const basicBody = `
    <dl class="info-grid">
      <dt>姓名</dt><dd>${escapeHtml(c.name || "—")}</dd>
      <dt>目标岗位</dt><dd>${escapeHtml(c.role || "—")}</dd>
      <dt>初筛等级</dt><dd>${escapeHtml(c.level || "—")}</dd>
      <dt>方向</dt><dd>${escapeHtml(c.category || "—")}</dd>
      <dt>阶段</dt><dd>${escapeHtml(c.stage || "—")}</dd>
      <dt>分组</dt><dd>${escapeHtml(c.group || "—")}</dd>
      <dt>分类置信度</dt><dd>${Number.isFinite(c.confidence) ? (c.confidence * 100).toFixed(0) + "%" : "—"}</dd>
    </dl>
  `;

  const miniCards = (items) => {
    const values = safeItems(items);
    return values.length
      ? `<div class="mini-card-list">${values.map((i) => `<article class="mini-card">${escapeHtml(String(i))}</article>`).join("")}</div>`
      : "<p>无</p>";
  };

  const skillChips = safeItems(c.skills).length
    ? `<div class="skill-cloud">${safeItems(c.skills).map((skill) => `<span class="${skillClass(skill)}">${escapeHtml(String(skill))}</span>`).join("")}</div>`
    : "<p>无</p>";

  const publicationCards = window.PublicationCards.analyze(c.publications, c.name);
  const publicationsBody = publicationCards.length
    ? `<div class="publication-list">${publicationCards.map((publication) => `
        <article class="publication-card">
          <div class="publication-card-head">
            <span class="publication-status is-${publication.status.key}">${escapeHtml(publication.status.label)}</span>
            ${publication.venueStatus?.key === "missing" ? `<span class="publication-status is-incomplete">${escapeHtml(publication.venueStatus.label)}</span>` : ""}
            ${publication.positionLabel ? `<span class="publication-position">${escapeHtml(publication.positionLabel)}</span>` : ""}
          </div>
          <h4>${escapeHtml(publication.title || publication.raw)}</h4>
          ${publication.authors.length ? `<p class="publication-authors">${publication.authors.map((author) => author.isCandidate
            ? `<strong>${escapeHtml(author.display)}</strong>`
            : `<span>${escapeHtml(author.display)}</span>`).join("<span class=\"author-separator\">, </span>")}</p>` : ""}
          ${publication.venue ? `<p class="publication-venue">${escapeHtml(publication.venue)}</p>` : ""}
        </article>
      `).join("")}</div>`
    : "<p>无</p>";

  const eduBody = miniCards(c.education);

  const directionsBody = miniCards(c.directions);

  const experiencesBody = Array.isArray(c.experiences) && c.experiences.length
    ? `<div class="experience-list">${c.experiences.map((experience) => {
        const dates = experience.period || [experience.start_date, experience.end_date].filter(Boolean).join(" - ");
        return `
          <article class="experience-item">
            <div class="experience-head">
              <div>
                <h4>${escapeHtml(experience.organization || "未标注机构")}</h4>
                <p>${escapeHtml(experience.role || "未标注岗位")}</p>
              </div>
              <div class="experience-meta">
                ${experience.experience_type ? `<span>${escapeHtml(experience.experience_type)}</span>` : ""}
                ${dates ? `<time>${escapeHtml(dates)}</time>` : ""}
              </div>
            </div>
            ${(experience.details || []).length ? `<ul>${experience.details.map((detail) => `<li>${escapeHtml(String(detail))}</li>`).join("")}</ul>` : "<p>暂无职责或成果细节</p>"}
          </article>
        `;
      }).join("")}</div>`
    : "<p>无</p>";

  const projectsBody = Array.isArray(c.projects) && c.projects.length
    ? `<div class="item-list">${c.projects.map((p) => `
        <div class="item-block">
          <h4>${escapeHtml(p.name || "未命名项目")}</h4>
          ${(p.details || []).length ? `<ul>${p.details.map((d) => `<li>${escapeHtml(String(d))}</li>`).join("")}</ul>` : "<p>无细节</p>"}
        </div>
      `).join("")}</div>`
    : "<p>无</p>";

  const documentAnalysis = c.document_analysis && typeof c.document_analysis === "object"
    ? c.document_analysis
    : {};
  const qualityDimensions = documentAnalysis.quality_dimensions && typeof documentAnalysis.quality_dimensions === "object"
    ? documentAnalysis.quality_dimensions
    : {};
  const qualityLabels = {
    information_architecture: "信息架构",
    evidence_expression: "证据表达",
    content_consistency: "内容一致性",
    targeting: "求职针对性",
  };
  const qualityRows = Object.entries(qualityLabels).map(([key, label]) => {
    const item = qualityDimensions[key] || {};
    const score = Number(item.score);
    return `
      <div class="document-quality-row">
        <span>${escapeHtml(label)}</span>
        <strong>${Number.isFinite(score) ? score.toFixed(1) : "—"} / 5</strong>
        <p>${escapeHtml(item.rationale || "暂无视觉评价")}</p>
      </div>
    `;
  }).join("");
  const documentWarnings = Array.isArray(documentAnalysis.warnings) ? documentAnalysis.warnings : [];
  const documentBody = `
    <div class="document-quality-head">
      <span>${c.source_format === "pdf" ? "PDF 视觉解析" : "文本简历"}</span>
      <span>最终最多计入 3 分</span>
    </div>
    <div class="document-quality-grid">${qualityRows}</div>
    ${documentWarnings.length ? `<div class="document-warning-list"><strong>解析警告</strong><ul>${documentWarnings.map((warning) => `<li>${escapeHtml(String(warning))}</li>`).join("")}</ul></div>` : ""}
  `;

  const content = document.createElement("div");
  content.className = "resume-content";
  content.innerHTML = [
    `<section class="resume-hero">
      <div>
        <h2>${escapeHtml(c.name || "未命名候选人")}</h2>
        <p>${escapeHtml(c.role || "—")}</p>
      </div>
      <div class="hero-tags">
        <span>${escapeHtml(formatPotentialLevel(c.level))}</span>
        <span>${escapeHtml(c.category || "—")}</span>
        <span>${escapeHtml((c.source_format || "text").toUpperCase())}</span>
        ${safeItems(c.screening_tags).slice(0, 2).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
      </div>
      <div class="summary-strip">
        ${summaryCounts.map((item) => `<span><strong>${item.value}</strong>${escapeHtml(item.label)}</span>`).join("")}
      </div>
    </section>`,
    section("基础信息", basicBody, "resume-section-basic"),
    section("教育背景", eduBody, "resume-section-education"),
    section("实习 / 工作经历", experiencesBody, "resume-section-experiences"),
    section("研究方向", directionsBody, "resume-section-directions"),
    section("项目经验", projectsBody, "resume-section-projects"),
    section("核心技能", skillChips, "resume-section-skills"),
    section("研究成果", publicationsBody, "resume-section-publications"),
    (c.source_format === "pdf" || Object.keys(qualityDimensions).length)
      ? section("简历表达（低权重）", documentBody, "resume-section-document")
      : "",
  ].join("");
  els.resumePane.appendChild(content);
}

function getAgentPaneHTML(candidate) {
  const run = runs.get(candidate.id);
  const hasRun = !!run;
  const isQueued = hasRun && run.queued;
  const isRunning = hasRun && run.controller;
  const result = hasRun ? run.result : candidate.evaluation;
  const state = isQueued ? "queued" : isRunning ? "running" : (result ? "done" : "ready");

  let nodeRowsHTML = hasRun ? "" : "<small>点击开始评估以查看节点流转</small>";

  let resultHTML = "";
  if (result) {
    const overall = clampScore(result.overall_score);

    const evidence = Array.isArray(result.evidence) ? result.evidence : [];
    const evidenceIndexById = new Map(evidence.map((item, index) => [String(item.id || ""), index]));
    const dimensions = Array.isArray(result.dimension_scores) ? result.dimension_scores : [];
    const dimRows = dimensions.map((dim) => {
      const rawScore = typeof dim.score === "number" ? dim.score : 0;
      const score = clampScore((rawScore / 5) * 100);
      const label = dim.label || dim.key || "维度";
      const evidenceRefs = Array.isArray(dim.evidence_ids)
        ? dim.evidence_ids
            .map((id) => evidenceIndexById.get(String(id)))
            .filter((index) => Number.isInteger(index))
            .map((index) => {
              const item = evidence[index];
              return `<button class="evidence-link evidence-inline" type="button" data-evidence-index="${index}">${escapeHtml(evidenceLabel(item, `证据${index + 1}`))}</button>`;
            })
            .join("")
        : "";
      return `
        <div class="score-row has-detail">
          <div class="score-main">
            <span class="score-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
            <div class="score-bar"><span style="width: ${score}%"></span></div>
            <span class="score-value">${rawScore.toFixed ? rawScore.toFixed(1) : rawScore}</span>
          </div>
          <p class="score-rationale">${renderEvidenceText(dim.rationale || "", evidence)}${evidenceRefs ? `<span class="evidence-ref-list">${evidenceRefs}</span>` : ""}</p>
        </div>
      `;
    }).join("");

    const assignments = Array.isArray(result.track_assignments) ? result.track_assignments : [];
    const trackEvaluations = Array.isArray(result.track_evaluations) ? result.track_evaluations : [];
    const trackEvaluationByKey = new Map(trackEvaluations.map((item) => [String(item.track || ""), item]));
    const evidenceButtons = (ids) => (Array.isArray(ids) ? ids : [])
      .map((id) => evidenceIndexById.get(String(id)))
      .filter((index) => Number.isInteger(index))
      .map((index) => {
        const item = evidence[index];
        return `<button class="evidence-link evidence-inline" type="button" data-evidence-index="${index}">${escapeHtml(evidenceLabel(item, `证据${index + 1}`))}</button>`;
      })
      .join("");
    const trackRows = assignments.map((assignment) => {
      const key = String(assignment.track || "");
      const evaluation = trackEvaluationByKey.get(key) || {};
      const trackScore = typeof evaluation.calibrated_score === "number" ? evaluation.calibrated_score : 0;
      const weight = typeof assignment.weight === "number" ? assignment.weight : 0;
      const trackDimensions = Array.isArray(evaluation.dimension_scores) ? evaluation.dimension_scores : [];
      const dimensionRows = trackDimensions.map((dimension) => {
        const rawScore = Number(dimension.score || 0);
        const weightedScore = Number(dimension.weighted_score || 0);
        const maxPoints = Number(dimension.max_points || 0);
        const refs = evidenceButtons(dimension.evidence_ids);
        return `
          <div class="track-dimension-row">
            <div class="track-dimension-head">
              <strong>${escapeHtml(dimension.label || dimension.key || "未命名维度")}</strong>
              <span>${rawScore.toFixed(1)} / 5 · ${weightedScore.toFixed(1)} / ${maxPoints.toFixed(0)}</span>
            </div>
            <div class="score-bar" aria-hidden="true"><span style="width: ${clampScore((rawScore / 5) * 100)}%"></span></div>
            <p>${renderEvidenceText(dimension.rationale || "暂无评分理由", evidence)}</p>
            ${refs ? `<div class="track-evidence-list"><span>证据</span>${refs}</div>` : `<div class="track-evidence-list is-empty"><span>证据</span><em>无直接证据</em></div>`}
          </div>
        `;
      }).join("");
      const trackRefs = evidenceButtons(evaluation.evidence_ids || assignment.evidence_ids);
      const trackRisks = [
        ...(Array.isArray(evaluation.risk_notes) ? evaluation.risk_notes : []),
        ...(Array.isArray(evaluation.critic_flags) ? evaluation.critic_flags : []),
      ];
      return `
        <details class="track-result" open>
          <summary class="track-result-summary">
            <span class="track-result-name">${escapeHtml(evaluation.label || key)}</span>
            <span class="track-result-weight">路由 ${(weight * 100).toFixed(0)}%</span>
            <strong>${trackScore.toFixed(1)} / 60</strong>
          </summary>
          <div class="track-result-body">
            <div class="track-contribution">
              <span>加权贡献</span><strong>${(trackScore * weight).toFixed(1)}</strong>
              <span>路由置信度</span><strong>${(Number(assignment.confidence || 0) * 100).toFixed(0)}%</strong>
            </div>
            <p class="track-route-rationale">${renderEvidenceText(assignment.rationale || "暂无路由说明", evidence)}</p>
            ${trackRefs ? `<div class="track-evidence-list"><span>Track 证据</span>${trackRefs}</div>` : ""}
            <div class="track-dimension-list">${dimensionRows || "<p>暂无维度结果</p>"}</div>
            ${trackRisks.length ? `<div class="track-risk-block"><strong>校准与待验证</strong><ul>${[...new Set(trackRisks)].map((risk) => `<li>${renderEvidenceText(risk, evidence)}</li>`).join("")}</ul></div>` : ""}
          </div>
        </details>
      `;
    }).join("");

    const scoreBreakdown = `通用潜力 ${Number(result.common_score || 0).toFixed(1)} / 40 · `
      + `Track 加权 ${trackEvaluations.length ? trackEvaluations.reduce((sum, item) => {
        const assignment = assignments.find((candidate) => candidate.track === item.track);
        return sum + Number(item.calibrated_score || 0) * Number(assignment?.weight || 0);
      }, 0).toFixed(1) : "0.0"} / 60`;

    const strengths = Array.isArray(result.core_strengths) && result.core_strengths.length
      ? `<ol>${result.core_strengths.map((s) => `<li>${renderEvidenceText(s, evidence)}</li>`).join("")}</ol>`
      : "<p>未生成</p>";

    const risks = Array.isArray(result.potential_risks) && result.potential_risks.length
      ? `<ul class="risk-list">${result.potential_risks.map((r) => `<li>${renderEvidenceText(r, evidence)}</li>`).join("")}</ul>`
      : "<p>未生成</p>";

    const questions = Array.isArray(result.interview_questions) && result.interview_questions.length
      ? `<ol>${result.interview_questions.map((q) => `<li>${renderEvidenceText(q, evidence)}</li>`).join("")}</ol>`
      : "<p>未生成</p>";

    const cultivation = Array.isArray(result.cultivation_direction) && result.cultivation_direction.length
      ? `<ul>${result.cultivation_direction.map((c) => `<li>${renderEvidenceText(c, evidence)}</li>`).join("")}</ul>`
      : "<p>未生成</p>";

    const decision = result.decision_method
      ? `<div class="result-section"><h3>决策方式</h3><p>${renderEvidenceText(result.decision_method, evidence)}</p></div>`
      : "";

    resultHTML = `
      <div class="evaluation-view">
        <div class="score-band"><span>${overall}</span><span>综合匹配分</span></div>
        <div class="result-section"><h3>人才画像</h3><p>${renderEvidenceText(result.one_liner || "—", evidence)}</p></div>
        ${decision}
        <div class="result-section result-section-tracks"><h3>Track 专业评估</h3><p>${escapeHtml(scoreBreakdown)}</p><div class="track-result-list">${trackRows || "<p>暂无 Track 结果</p>"}</div></div>
        <div class="result-section"><h3>通用潜力评分</h3><div class="score-list">${dimRows}</div></div>
        <div class="result-section"><h3>核心优势</h3>${strengths}</div>
        <div class="result-section"><h3>风险与待验证</h3>${risks}</div>
        <div class="result-section"><h3>面谈追问</h3>${questions}</div>
        <div class="result-section"><h3>培养方向</h3>${cultivation}</div>
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
          <button class="evaluate-button" id="evaluate-button" data-id="${escapeHtml(candidate.id)}" ${isQueued ? "disabled" : ""}>
            ${isQueued ? "排队中…" : isRunning ? "评估中…" : (result ? "重新评估" : "开始评估")}
          </button>
          <button class="collapse-button" id="agent-collapse" type="button" aria-expanded="true">收起</button>
        </div>
      </div>
      <div class="agent-body" id="agent-body">
        <div class="agent-status-bar">
          <span class="state-chip ${state === "running" || state === "queued" ? "is-running" : state === "done" ? "is-ready" : "is-ready"}" id="agent-state-chip">
            ${state === "queued" ? "QUEUED" : state === "running" ? "RUNNING" : state === "done" ? "DONE" : "READY"}
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

  els.agentPane.querySelector(".agent-content")?.addEventListener("click", (e) => {
    const target = e.target.closest(".evidence-link");
    if (!target) return;
    const result = candidate.evaluation || runs.get(candidate.id)?.result;
    if (!result) return;
    const index = Number(target.dataset.evidenceIndex);
    const item = result.evidence?.[index];
    if (!item) return;
    renderEvidencePopover(target, evidenceContent(item), item.dimension || "证据详情");
  });

  renderNodeFeed(candidate.id);
}

async function selectCandidate(candidateId) {
  currentCandidateId = candidateId;
  const candidate = candidates[candidateId];
  if (!candidate) return;

  document.querySelectorAll(".candidate-card").forEach((card) => card.classList.toggle("is-active", card.dataset.id === candidateId));
  renderResume(candidate);
  renderAgent(candidate);

  loadCandidateDetail(candidateId)
    .then((detail) => {
      if (currentCandidateId !== candidateId) return;
      renderResume(detail);
      renderAgent(detail);
    })
    .catch((err) => {
      if (currentCandidateId === candidateId) {
        showToast("候选人详情加载失败：" + err.message);
      }
    });
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

function upsertAgentNodeEvent(candidateId, nodeKey, label, message, status) {
  const run = runs.get(candidateId);
  if (!run) return;

  const existing = run.nodeRows.get(nodeKey);
  if (existing) {
    existing.label = label || existing.label;
    existing.message = message || existing.message;
    existing.status = status;
  } else {
    run.nodeRows.set(nodeKey, { label, message, status });
  }
  window.AgentGraph.advanceAfterEvent(run.nodeRows, nodeKey);

  renderNodeFeed(candidateId);
}

function renderNodeFeed(candidateId) {
  if (currentCandidateId !== candidateId) return;
  const run = runs.get(candidateId);
  if (!run) return;

  const feed = document.getElementById("node-feed");
  if (!feed) return;

  feed.innerHTML = "";
  const appendNode = (container, nodeKey) => {
    const row = run.nodeRows.get(nodeKey);
    if (!row) return;
    const status = row.status || "pending";
    const rowEl = document.createElement("div");
    rowEl.className = `node-row is-${status}`;
    rowEl.dataset.node = nodeKey;
    rowEl.innerHTML = `
      <div class="node-icon" aria-hidden="true">${status === "done" ? "✓" : status === "skipped" ? "—" : status === "error" ? "!" : ""}</div>
      <div class="node-body">
        <div class="node-title-line">
          <strong>${escapeHtml(row.label)}</strong>
          <span class="node-status">${escapeHtml(window.AgentGraph.statusLabel(status))}</span>
        </div>
        <small>${escapeHtml(row.message || "等待执行…")}</small>
      </div>
    `;
    container.appendChild(rowEl);
  };
  STAGES.forEach((stage) => {
    const stageEl = document.createElement("section");
    stageEl.className = `node-stage ${stage.parallel ? "is-parallel" : ""}`;
    stageEl.dataset.stage = stage.key;
    if (stage.parallel && Array.isArray(stage.lanes)) {
      stageEl.innerHTML = `
        <div class="node-stage-head">
          <strong>${escapeHtml(stage.label)}</strong>
          <span>${escapeHtml(stage.description)}</span>
        </div>
        <div class="parallel-origin"><span>并行启动</span></div>
        <div class="parallel-lanes"></div>
      `;
      const lanes = stageEl.querySelector(".parallel-lanes");
      stage.lanes.forEach((lane) => {
        const laneEl = document.createElement("section");
        laneEl.className = `parallel-lane ${lane.common ? "is-common" : ""}`;
        laneEl.dataset.lane = lane.key;
        laneEl.innerHTML = `
          <div class="parallel-lane-head"><strong>${escapeHtml(lane.label)}</strong><span>${lane.nodes.length > 1 ? "串行链" : "独立 Track"}</span></div>
          <div class="parallel-lane-nodes"></div>
        `;
        const laneNodes = laneEl.querySelector(".parallel-lane-nodes");
        lane.nodes.forEach((nodeKey) => appendNode(laneNodes, nodeKey));
        lanes.appendChild(laneEl);
      });
      feed.appendChild(stageEl);
      return;
    }
    stageEl.innerHTML = `
      <div class="node-stage-head">
        <strong>${escapeHtml(stage.label)}</strong>
        <span>${escapeHtml(stage.description)}</span>
      </div>
      <div class="node-stage-grid"></div>
    `;
    const grid = stageEl.querySelector(".node-stage-grid");
    stage.nodes.forEach((nodeKey) => appendNode(grid, nodeKey));
    feed.appendChild(stageEl);
  });

  const sub = document.getElementById("node-panel-sub");
  if (sub) {
    sub.textContent = run.queued
      ? "等待批量调度"
      : run.controller
        ? "流式运行中"
        : run.result
          ? "已完成"
          : run.error
            ? "失败"
            : "未开始";
  }
}

function finishAgentRun(candidateId, result) {
  const run = runs.get(candidateId);
  if (!run) return;

  run.controller = null;
  run.result = result;
  window.AgentGraph.setNodeStatus(run.nodeRows, "formatter", "done", "结构化结果已生成。");
  candidates[candidateId].evaluation = result;
  candidates[candidateId].group = result ? groupForScore(result.overall_score) : "rejected";

  updateLibrary();
  if (!run.bulk) {
    openDrawer(candidates[candidateId].group);
  }

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
  const runningNode = [...run.nodeRows.entries()].find(([, row]) => row.status === "running");
  if (runningNode) {
    window.AgentGraph.setNodeStatus(run.nodeRows, runningNode[0], "error", error.message || "节点执行失败。");
  }

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

function requestBulkEvaluation() {
  const ids = pendingCandidateIds();
  if (!ids.length) {
    showToast("待评价库为空");
    return;
  }
  if (bulkEvaluating) return;

  const message = `将同时提交 ${ids.length} 位待评价候选人并开始评估。完成后，${scoringConfig.routing_note}`;
  if (!els.bulkConfirmDialog?.showModal) {
    if (confirm(message)) evaluatePendingCandidates(ids);
    return;
  }

  els.bulkConfirmTitle.textContent = "确认评估待评价库";
  els.bulkConfirmMessage.textContent = message;
  els.bulkConfirmSubmit.dataset.ids = JSON.stringify(ids);
  els.bulkConfirmDialog.showModal();
}

function queueAgentRun(candidateId, bulk = true) {
  const existing = runs.get(candidateId);
  if (existing?.controller || existing?.result) return;

  const run = {
    candidateId,
    controller: null,
    nodeRows: window.AgentGraph.createNodeRows(),
    result: null,
    error: null,
    panelOpen: existing?.panelOpen ?? true,
    bulk,
    queued: true,
  };
  window.AgentGraph.setNodeStatus(run.nodeRows, NODE_ORDER[0], "queued", "等待批量调度…");
  runs.set(candidateId, run);
}

async function runWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(limit, items.length);

  const workers = Array.from({ length: workerCount }, async () => {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      try {
        results[currentIndex] = { status: "fulfilled", value: await worker(items[currentIndex], currentIndex) };
      } catch (reason) {
        results[currentIndex] = { status: "rejected", reason };
      }
    }
  });

  await Promise.all(workers);
  return results;
}

async function evaluatePendingCandidates(ids) {
  if (!ids.length || bulkEvaluating) return;
  bulkEvaluating = true;
  bulkEvaluationProgress = { done: 0, total: ids.length };
  ids.forEach((candidateId) => queueAgentRun(candidateId, true));
  updateBulkEvaluateButton(ids.length);
  if (currentCandidateId && ids.includes(currentCandidateId)) {
    renderAgent(candidates[currentCandidateId]);
  }
  showToast(`开始评估 ${ids.length} 位候选人`);

  const settled = await runWithConcurrency(ids, BULK_EVALUATION_CONCURRENCY, async (candidateId) => {
    try {
      await startEvaluation(candidateId, { select: false, bulk: true });
      const run = runs.get(candidateId);
      if (run?.error) throw run.error;
    } finally {
      bulkEvaluationProgress.done += 1;
      updateBulkEvaluateButton(ids.length);
    }
  });
  const successCount = settled.filter((item) => item.status === "fulfilled").length;
  const failedCount = settled.length - successCount;
  bulkEvaluating = false;
  bulkEvaluationProgress = null;
  updateBulkEvaluateButton();
  updateLibrary();

  if (Object.values(candidates).some((candidate) => candidate.group === "shortlisted")) {
    openDrawer("shortlisted");
  } else if (Object.values(candidates).some((candidate) => candidate.group === "alternative")) {
    openDrawer("alternative");
  } else {
    openDrawer("rejected");
  }
  showToast(failedCount ? `批量评估完成：成功 ${successCount}，失败 ${failedCount}` : `批量评估完成：成功 ${successCount}`);
}

async function handleEvaluate(candidateId) {
  return startEvaluation(candidateId, { select: true, bulk: false });
}

async function startEvaluation(candidateId, options = {}) {
  const { select = true, bulk = false } = options;
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
    nodeRows: window.AgentGraph.createNodeRows(),
    result: null,
    error: null,
    panelOpen: existing?.panelOpen ?? true,
    bulk,
    queued: false,
  };
  window.AgentGraph.setNodeStatus(run.nodeRows, NODE_ORDER[0], "running", "正在执行…");
  runs.set(candidateId, run);

  if (select) {
    await selectCandidate(candidateId);
  } else if (currentCandidateId === candidateId) {
    renderAgent(candidates[candidateId]);
  }

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
          upsertAgentNodeEvent(candidateId, event.node, event.label, event.message, event.status || "done");
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
    if (bulk) throw err;
  }
}

function renderImportProgress() {
  if (!importState) return;
  const completed = window.ImportProgress.completedCount(importState);
  const total = importState.items.length;
  els.importFileName.textContent = `批量导入 ${completed}/${total}`;
  els.importState.textContent = window.ImportProgress.statusLabel(importState.status);
  els.importState.className = `import-state is-${importState.status}`;
  els.progressText.textContent = importState.message;
  els.importStageList.innerHTML = importState.items.map((item) => `
    <div class="import-file-row is-${item.status}">
      <div class="import-file-row-head">
        <span class="import-file-row-name" title="${escapeHtml(item.fileName)}">${escapeHtml(item.candidateName || item.fileName)}</span>
        <small>${escapeHtml(item.stageLabel)} · ${escapeHtml(window.ImportProgress.statusLabel(item.status))}</small>
      </div>
      <div class="import-file-track" role="progressbar" aria-label="${escapeHtml(item.fileName)} 导入进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${item.progress}">
        <span style="width: ${item.progress}%"></span>
      </div>
      <div class="import-file-message">${escapeHtml(item.message)}</div>
    </div>
  `).join("");
  els.importCancel.classList.toggle("hidden", importState.status !== "running");
  const hasErrors = importState.items.some((item) => item.status === "error");
  els.importRetry.classList.toggle("hidden", !hasErrors && importState.status !== "error");
  els.importCancel.classList.remove("hidden");
  els.importCancel.textContent = importState.status === "running" ? "取消" : "关闭";
}

async function handleImportFiles(files) {
  const selectedFiles = Array.from(files || []);
  if (!selectedFiles.length) return;
  if (selectedFiles.length > 50) {
    showToast("单次最多导入 50 份简历");
    return;
  }

  importController?.abort();
  importController = new AbortController();
  lastImportFiles = selectedFiles;
  importState = window.ImportProgress.createState(selectedFiles);
  els.importButton.classList.add("is-busy");
  els.progressBox.classList.remove("hidden");
  renderImportProgress();

  const formData = new FormData();
  selectedFiles.forEach((file) => formData.append("files", file));

  try {
    const res = await fetch("/api/import-file", {
      method: "POST",
      body: formData,
      cache: "no-store",
      signal: importController.signal,
    });
    if (!res.ok || !res.body) throw new Error(`导入请求失败（${res.status}）`);
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
        let event;
        try {
          event = JSON.parse(trimmed.slice(6));
        } catch (error) {
          continue;
        }
        window.ImportProgress.applyEvent(importState, event);
        renderImportProgress();
        if (event.type === "candidate") {
          candidates[event.candidate.id] = event.candidate;
          updateLibrary();
          openDrawer("pending");
        } else if (event.type === "done") {
          showToast(event.failed_files ? `导入完成，${event.failed_files} 份失败` : `已导入 ${event.total} 份简历`);
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    if (importState.status !== "error") {
      window.ImportProgress.applyEvent(importState, { type: "error", message: err.message });
    }
    renderImportProgress();
    showToast("导入失败：" + err.message);
  } finally {
    els.importButton.classList.remove("is-busy");
    importController = null;
  }
}

els.drawerToggles.forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const drawer = toggle.closest(".drawer");
    if (!drawer?.dataset.group) return;
    if (drawer.classList.contains("is-open")) {
      setDrawerOpen(drawer.dataset.group, false);
    } else {
      openDrawer(drawer.dataset.group);
    }
  });
});

els.importCancel.addEventListener("click", () => {
  if (importState?.status === "running") {
    importController?.abort();
    window.ImportProgress.cancel(importState);
    renderImportProgress();
  } else {
    els.progressBox.classList.add("hidden");
  }
  els.importButton.classList.remove("is-busy");
});

els.importRetry.addEventListener("click", () => {
  const failedFiles = importState?.items
    .filter((item) => item.status === "error")
    .map((item) => item.file)
    .filter(Boolean);
  handleImportFiles(failedFiles?.length ? failedFiles : lastImportFiles);
});

els.importInput.addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  if (files.length) handleImportFiles(files);
  els.importInput.value = "";
});

els.bulkEvaluateButton?.addEventListener("click", requestBulkEvaluation);

els.bulkConfirmCancel?.addEventListener("click", () => {
  els.bulkConfirmDialog?.close();
});

els.bulkConfirmSubmit?.addEventListener("click", () => {
  const ids = JSON.parse(els.bulkConfirmSubmit.dataset.ids || "[]");
  els.bulkConfirmDialog?.close();
  evaluatePendingCandidates(ids);
});

openDrawer("pending");
loadCandidates();
