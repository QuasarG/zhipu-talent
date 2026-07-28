/* ============================================================================
   简历评估工作台 JS（模块 5：候选人队列）
   原生 JS，无框架。fetch + innerHTML 渲染。
   ========================================================================== */

(function () {
  "use strict";

  const els = {
    queueList: document.getElementById("queue-list"),
    queueSearch: document.getElementById("queue-search"),
    segmented: document.querySelector(".queue-segmented"),
    counts: {
      pending: document.getElementById("count-pending"),
      running: document.getElementById("count-running"),
      completed: document.getElementById("count-completed"),
    },
    toolbarCandidate: document.getElementById("toolbar-candidate"),
    toast: document.getElementById("toast"),
  };

  let state = {
    candidates: [],
    filter: "pending",
    search: "",
    selectedId: null,
  };

  const btnRefresh = document.getElementById("btn-refresh");

  // ---- API ----
  async function fetchCandidates() {
    const resp = await fetch("/api/candidates");
    if (!resp.ok) throw new Error(`加载候选人失败: ${resp.status}`);
    return resp.json();
  }

  async function fetchCandidateDetail(id) {
    const resp = await fetch(`/api/candidates/${id}`);
    if (!resp.ok) throw new Error(`加载详情失败: ${resp.status}`);
    return resp.json();
  }

  // ---- 渲染 ----
  function classifyCandidate(row) {
    // 旧数据只有 group 字段；阶段 1 后用 engagement_status。
    // 简化：group=pending 且无 evaluation → pending；
    //       有 evaluation.status=completed → completed；
    //       有 evaluation.status=running/failed → running。
    const group = row.group || "pending";
    if (row.evaluation_status && row.evaluation_status !== "newly_admitted") {
      // 已入库人才默认归入 completed
      return "completed";
    }
    if (group === "pending") return "pending";
    return "completed";
  }

  function filterCandidates() {
    const search = state.search.trim().toLowerCase();
    return state.candidates.filter((c) => {
      if (classifyCandidate(c) !== state.filter) return false;
      if (!search) return true;
      const hay = `${c.name || ""} ${c.role || ""} ${c.stage || ""}`.toLowerCase();
      return hay.includes(search);
    });
  }

  function updateCounts() {
    const counts = { pending: 0, running: 0, completed: 0 };
    state.candidates.forEach((c) => {
      counts[classifyCandidate(c)]++;
    });
    els.counts.pending.textContent = counts.pending;
    els.counts.running.textContent = counts.running;
    els.counts.completed.textContent = counts.completed;
  }

  function renderQueue() {
    const items = filterCandidates();
    if (!items.length) {
      els.queueList.innerHTML = '<div class="queue-empty muted">无匹配候选人</div>';
      return;
    }
    els.queueList.innerHTML = items.map(renderQueueItem).join("");
    els.queueList.querySelectorAll(".queue-item").forEach((el) => {
      el.addEventListener("click", () => selectCandidate(el.dataset.id));
    });
  }

  function renderQueueItem(c) {
    const isSelected = c.id === state.selectedId ? " is-selected" : "";
    const dotClass = classifyCandidate(c);
    const org = c.role || c.stage || "—";
    const updated = c.admitted_at
      ? new Date(c.admitted_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })
      : "";
    return `
      <div class="queue-item${isSelected}" data-id="${c.id}" role="listitem">
        <div class="queue-item-head">
          <span class="queue-item-name">${esc(c.name || c.id)}</span>
          <span class="queue-item-status-dot ${dotClass}"></span>
        </div>
        <div class="queue-item-meta">
          <span class="queue-item-org">${esc(org)}</span>
          ${updated ? `<span class="muted">${updated}</span>` : ""}
        </div>
      </div>`;
  }

  // ---- 选中候选人 ----
  async function selectCandidate(id) {
    state.selectedId = id;
    if (btnRefresh) btnRefresh.disabled = false;
    renderQueue();
    els.toolbarCandidate.textContent = "加载中…";
    try {
      const detail = await fetchCandidateDetail(id);
      els.toolbarCandidate.textContent = `${detail.name} · ${detail.stage || "阶段未知"}`;
      // 模块 6/7 会填充简历内容区和评估结果区
      window.dispatchEvent(new CustomEvent("candidate-selected", { detail }));
    } catch (err) {
      els.toolbarCandidate.textContent = "加载失败";
      showToast(err.message);
    }
  }

  // ---- segmented 切换 ----
  els.segmented.querySelectorAll(".pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.segmented.querySelectorAll(".pill").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.filter = btn.dataset.filter;
      renderQueue();
    });
  });

  // ---- 搜索 ----
  let searchTimer;
  els.queueSearch.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = e.target.value;
      renderQueue();
    }, 200);
  });

  // ---- Toast ----
  let toastTimer;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("is-visible"), 3000);
  }

  // ---- HTML 转义 ----
  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }

  // ---- 初始化 ----
  async function init() {
    try {
      state.candidates = await fetchCandidates();
      updateCounts();
      renderQueue();
    } catch (err) {
      els.queueList.innerHTML = `<div class="queue-empty muted">加载失败：${esc(err.message)}</div>`;
    }
  }

  // 暴露给后续模块
  window.ResumeWorkbench = {
    state, els, selectCandidate, showToast, esc,
    fetchCandidates, updateCounts, renderQueue,
  };
  init();
})();