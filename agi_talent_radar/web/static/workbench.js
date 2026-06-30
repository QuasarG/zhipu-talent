const state = {
  data: null,
  selectedId: "",
  tier: "all",
  category: "all",
  sortDesc: true,
};

const els = {
  list: document.querySelector("#candidateList"),
  status: document.querySelector("#statusText"),
  metricCount: document.querySelector("#metricCount"),
  metricTop: document.querySelector("#metricTop"),
  metricStrong: document.querySelector("#metricStrong"),
  selectedTier: document.querySelector("#selectedTier"),
  selectedName: document.querySelector("#selectedName"),
  selectedRole: document.querySelector("#selectedRole"),
  selectedImportCategory: document.querySelector("#selectedImportCategory"),
  selectedScore: document.querySelector("#selectedScore"),
  selectedLevel: document.querySelector("#selectedLevel"),
  oneLiner: document.querySelector("#oneLiner"),
  dimensions: document.querySelector("#dimensionScores"),
  strengths: document.querySelector("#strengthList"),
  risks: document.querySelector("#riskList"),
  evidence: document.querySelector("#evidenceList"),
  evidenceCount: document.querySelector("#evidenceCount"),
  questions: document.querySelector("#questionList"),
  cultivation: document.querySelector("#cultivationList"),
  rerun: document.querySelector("#rerunButton"),
  fileInput: document.querySelector("#fileInput"),
  sort: document.querySelector("#sortButton"),
  categorySelect: document.querySelector("#categorySelect"),
  toast: document.querySelector("#toast"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadEvaluations();
});

function bindEvents() {
  document.querySelectorAll(".tier-tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tier-tab").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      state.tier = button.dataset.tier;
      renderList();
    });
  });

  els.rerun.addEventListener("click", async () => {
    await postAndRender("/api/evaluate-sample", null, "样本评估已刷新");
  });

  els.fileInput.addEventListener("change", async () => {
    const file = els.fileInput.files[0];
    if (!file) return;
    const payload = new FormData();
    payload.append("file", file);
    await postAndRender("/api/evaluate-upload", payload, "上传文件评估完成");
    els.fileInput.value = "";
  });

  els.sort.addEventListener("click", () => {
    state.sortDesc = !state.sortDesc;
    renderList();
    showToast(state.sortDesc ? "已按分数从高到低排序" : "已按分数从低到高排序");
  });

  els.categorySelect.addEventListener("change", () => {
    state.category = els.categorySelect.value;
    renderList();
  });
}

async function loadEvaluations() {
  setLoading(true, "加载评估结果");
  try {
    const response = await fetch("/api/evaluations");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "加载失败");
    applyData(data);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

async function postAndRender(url, body, message) {
  setLoading(true, "评估中");
  try {
    const response = await fetch(url, { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "评估失败");
    applyData(data);
    showToast(message);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

function applyData(data) {
  state.data = data;
  const first = data.evaluations?.[0];
  state.selectedId = first ? first.id : "";
  renderMetrics();
  renderCategoryFilter();
  renderList();
  renderDetail(currentCandidate());
}

function renderMetrics() {
  const evaluations = state.data?.evaluations || [];
  const top = evaluations[0]?.overall_score ?? "-";
  const strong = evaluations.filter((item) => item.tier === "强烈建议沟通").length;
  els.metricCount.textContent = String(evaluations.length);
  els.metricTop.textContent = String(top);
  els.metricStrong.textContent = String(strong);
  els.status.textContent = evaluations.length ? "已完成批量初评" : "暂无数据";
}

function renderCategoryFilter() {
  const categories = [...new Set((state.data?.evaluations || [])
    .map((item) => item.import_category)
    .filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  els.categorySelect.innerHTML = '<option value="all">全部分类</option>';
  categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    els.categorySelect.appendChild(option);
  });
  state.category = "all";
}

function renderList() {
  const evaluations = filteredCandidates();
  els.list.innerHTML = "";
  if (!evaluations.length) {
    els.list.innerHTML = '<div class="evidence-item">当前分层没有候选人。</div>';
    return;
  }
  evaluations.forEach((candidate) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `candidate-card ${candidate.id === state.selectedId ? "is-active" : ""}`;
    button.innerHTML = `
      <div>
        <strong>${escapeHtml(candidate.name)}</strong>
        <span>${escapeHtml(candidate.target_role)}</span>
        <small>${escapeHtml(candidate.import_category || "未分类")} · ${escapeHtml(candidate.tier)}</small>
      </div>
      <div class="card-score">${candidate.overall_score}</div>
    `;
    button.addEventListener("click", () => {
      state.selectedId = candidate.id;
      renderList();
      renderDetail(candidate);
    });
    els.list.appendChild(button);
  });
}

function filteredCandidates() {
  const evaluations = [...(state.data?.evaluations || [])];
  const byTier = state.tier === "all" ? evaluations : evaluations.filter((item) => item.tier === state.tier);
  const filtered = state.category === "all" ? byTier : byTier.filter((item) => item.import_category === state.category);
  filtered.sort((a, b) => state.sortDesc ? b.overall_score - a.overall_score : a.overall_score - b.overall_score);
  return filtered;
}

function currentCandidate() {
  const evaluations = state.data?.evaluations || [];
  return evaluations.find((item) => item.id === state.selectedId) || evaluations[0] || null;
}

function renderDetail(candidate) {
  if (!candidate) {
    return;
  }
  els.selectedTier.textContent = candidate.tier;
  els.selectedName.textContent = `${candidate.name} · ${candidate.stage}`;
  els.selectedRole.textContent = candidate.target_role;
  els.selectedImportCategory.textContent = `导入分类：${candidate.import_category || "未分类"} · 置信度 ${Number(candidate.import_confidence || 0).toFixed(2)}`;
  els.selectedScore.textContent = candidate.overall_score;
  els.selectedLevel.textContent = `${candidate.level} 级`;
  els.oneLiner.textContent = candidate.one_liner;
  renderDimensions(candidate.dimension_scores || []);
  renderTextList(els.strengths, candidate.core_strengths || []);
  renderTextList(els.risks, candidate.potential_risks || []);
  renderEvidence(candidate.evidence || []);
  renderOrderedList(els.questions, candidate.interview_questions || []);
  renderTextList(els.cultivation, candidate.cultivation_direction || []);
}

function renderDimensions(items) {
  els.dimensions.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "score-row";
    const width = Math.max(0, Math.min(100, (Number(item.score) / 5) * 100));
    row.innerHTML = `
      <div class="score-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</div>
      <div class="score-bar"><span style="width:${width}%"></span></div>
      <div class="score-value">${Number(item.score).toFixed(2)}</div>
    `;
    els.dimensions.appendChild(row);
  });
}

function renderTextList(target, items) {
  target.innerHTML = "";
  items.forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    target.appendChild(li);
  });
}

function renderOrderedList(target, items) {
  target.innerHTML = "";
  items.forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    target.appendChild(li);
  });
}

function renderEvidence(items) {
  els.evidence.innerHTML = "";
  els.evidenceCount.textContent = `${items.length} items`;
  items.forEach((item) => {
    const block = document.createElement("div");
    block.className = "evidence-item";
    const signals = (item.signals || []).slice(0, 5).map((signal) => (
      `<span class="signal-pill">${escapeHtml(signal)}</span>`
    )).join("");
    block.innerHTML = `
      <div class="evidence-meta">
        <strong>${escapeHtml(item.id)} · ${escapeHtml(item.dimension)}</strong>
        <span>${escapeHtml(item.source)} · strength ${item.strength}</span>
      </div>
      <div class="evidence-quote">${escapeHtml(item.quote)}</div>
      <div class="signal-row">${signals}</div>
    `;
    els.evidence.appendChild(block);
  });
}

function setLoading(isLoading, text = "") {
  document.body.classList.toggle("is-loading", isLoading);
  if (text) els.status.textContent = text;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("is-open");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.classList.remove("is-open");
  }, 2600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
