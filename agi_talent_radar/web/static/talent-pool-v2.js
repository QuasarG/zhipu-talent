/* ============================================================================
   人才库 V2 JS（模块 13-14）：列表 + 来源筛选 + 人物详情 + HR 状态修改。
   ========================================================================== */

(function () {
  "use strict";

  const els = {
    list: document.getElementById("pool-list"),
    search: document.getElementById("pool-search"),
    sourceSeg: document.getElementById("pool-source-seg"),
    filterChips: document.getElementById("pool-filter-chips"),
    detailPane: document.getElementById("pool-detail-pane"),
    counts: {
      all: document.getElementById("count-all"),
      resume: document.getElementById("count-resume"),
      invest: document.getElementById("count-invest"),
    },
    toast: document.getElementById("toast"),
  };

  let state = {
    persons: [],
    search: "",
    source: "",
    track: "",
    selectedId: null,
  };

  // ---- API ----
  async function fetchPersons() {
    const params = new URLSearchParams();
    if (state.search) params.set("name", state.search);
    const resp = await fetch("/api/persons?" + params);
    if (!resp.ok) throw new Error(`加载失败: ${resp.status}`);
    return resp.json();
  }

  async function fetchPersonDetail(id) {
    const resp = await fetch(`/api/persons/${id}`);
    if (!resp.ok) throw new Error(`详情加载失败: ${resp.status}`);
    return resp.json();
  }

  async function fetchCandidateDetail(candidateId) {
    const resp = await fetch(`/api/candidates/${candidateId}`);
    if (!resp.ok) return null;
    return resp.json();
  }

  async function updateEngagementStatus(candidateId, status, changedBy, note) {
    const resp = await fetch(`/api/candidates/${candidateId}/engagement-status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, changed_by: changedBy, note }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "更新失败");
    }
    return resp.json();
  }

  // ---- 渲染列表 ----
  function classifySource(p) {
    // persons API 没有 sources 字段；用 person_type 粗分
    if (p.person_type === "guest") return "person_investigation";
    return "resume_evaluation";
  }

  function classifyTrack(p) {
    const dir = (p.direction || "").toLowerCase();
    if (dir.includes("agent")) return "agent";
    if (dir.includes("safe")) return "safety";
    if (dir.includes("system")) return "systems";
    if (dir.includes("multimodal") || dir.includes("多模态")) return "multimodal";
    if (dir.includes("science") || dir.includes("ai4s")) return "ai4science";
    return "";
  }

  function filterPersons() {
    return state.persons.filter((p) => {
      if (state.source && classifySource(p) !== state.source) return false;
      if (state.track && classifyTrack(p) !== state.track) return false;
      return true;
    });
  }

  function updateCounts() {
    const counts = { all: state.persons.length, resume: 0, invest: 0 };
    state.persons.forEach((p) => {
      counts[classifySource(p)]++;
    });
    els.counts.all.textContent = counts.all;
    els.counts.resume.textContent = counts.resume;
    els.counts.invest.textContent = counts.invest;
  }

  function renderList() {
    const items = filterPersons();
    if (!items.length) {
      els.list.innerHTML = '<div class="pool-list-empty muted">无匹配人才</div>';
    } else {
      els.list.innerHTML = items.map(renderRow).join("");
      els.list.querySelectorAll(".pool-talent-row").forEach((el) => {
        el.addEventListener("click", () => selectPerson(el.dataset.id));
      });
    }
    // 通知图谱更新
    window.dispatchEvent(new CustomEvent("pool-data-updated", { detail: items }));
  }

  function renderRow(p) {
    const isSelected = p.id === state.selectedId ? " is-selected" : "";
    const track = classifyTrack(p);
    const source = classifySource(p);
    const statusBadge = engagementBadge(p.engagement_status || "newly_admitted");
    return `
      <div class="pool-talent-row${isSelected}" data-id="${p.id}" role="listitem">
        <div class="pool-talent-head">
          <span class="pool-talent-name">${esc(p.name || p.id)}</span>
          ${statusBadge}
        </div>
        <div class="pool-talent-meta">
          <span class="pool-talent-org">${esc(p.org || "—")} · ${esc(track || "未分类")}</span>
        </div>
        <div class="pool-talent-tags">
          <span class="pool-talent-tag tag-${source === 'resume_evaluation' ? 'resume' : 'invest'}">
            ${source === "resume_evaluation" ? "简历评估" : "人物调查"}
          </span>
        </div>
      </div>`;
  }

  function engagementBadge(status) {
    const labels = {
      newly_admitted: ["新入库", "badge--neutral"],
      to_contact: ["待联系", "badge--pending"],
      contacted: ["已联系", "badge--info"],
      interviewing: ["面试中", "badge--info"],
      ongoing_follow: ["持续关注", "badge--confirmed"],
      closed: ["已结束", "badge--neutral"],
    };
    const [label, cls] = labels[status] || ["未知", "badge--neutral"];
    return `<span class="badge ${cls}">${label}</span>`;
  }

  // ---- 详情 ----
  async function selectPerson(id) {
    state.selectedId = id;
    renderList();
    els.detailPane.innerHTML = '<div class="pool-detail-empty muted">加载中…</div>';
    try {
      const person = await fetchPersonDetail(id);
      renderDetail(person);
      // 通知图谱高亮
      window.dispatchEvent(new CustomEvent("pool-node-selected", { detail: id }));
    } catch (err) {
      els.detailPane.innerHTML = `<div class="pool-detail-empty muted">加载失败：${esc(err.message)}</div>`;
    }
  }

  function renderDetail(person) {
    const initials = (person.name || "?").charAt(0);
    const evaluations = person.evaluations || [];
    const latest = evaluations[0];
    const reputation = person.reputation_reports || [];
    const candidateId = latest?.candidate_id || person.id;

    els.detailPane.innerHTML = `
      <div class="detail-avatar">${esc(initials)}</div>
      <div class="detail-name">${esc(person.name || person.id)}</div>
      <div class="detail-affil">${esc(person.org || "—")} · ${esc(person.direction || "—")}</div>
      <div class="pool-talent-tags" style="margin-bottom:12px">
        <span class="pool-talent-tag tag-${person.person_type === 'guest' ? 'invest' : 'resume'}">
          ${person.person_type === "guest" ? "人物调查" : "简历评估"}
        </span>
      </div>

      <div class="detail-section">
        <h3>HR 跟进状态</h3>
        <div class="detail-engagement">
          <select id="detail-engagement-select">
            <option value="newly_admitted">新入库</option>
            <option value="to_contact">待联系</option>
            <option value="contacted">已联系</option>
            <option value="interviewing">面试中</option>
            <option value="ongoing_follow">持续关注</option>
            <option value="closed">已结束</option>
          </select>
          <button class="pill" id="detail-engagement-save">保存</button>
        </div>
      </div>

      ${latest ? `
      <div class="detail-section">
        <h3>能力概览</h3>
        <div class="detail-score-row">
          <span class="detail-score">${latest.overall_score ?? "—"}</span>
          <span class="detail-score-note muted">能力描述，不代表录取结论</span>
        </div>
        ${latest.recommended_tracks?.length ? `
          <p style="margin-top:4px;font-size:12px" class="muted">
            推荐：${latest.recommended_tracks.map((t) => t.track || t.name || "").join(", ")}
          </p>` : ""}
      </div>` : ""}

      ${evaluations.length > 1 ? `
      <div class="detail-section">
        <h3>评估历史 (${evaluations.length})</h3>
        ${evaluations.map((e) => `
          <div style="font-size:12px;padding:4px 0;color:var(--color-fg-secondary)">
            ${e.overall_score ?? "—"} 分 · ${esc(e.one_liner || "")}
          </div>`).join("")}
      </div>` : ""}

      ${reputation.length ? `
      <div class="detail-section">
        <h3>舆情报告</h3>
        ${reputation.map((r) => `
          <div style="font-size:12px;padding:4px 0">
            ${engagementBadge(r.level === "red" ? "closed" : r.level === "yellow" ? "to_contact" : "ongoing_follow")}
            ${esc(r.review_status || "")}
          </div>`).join("")}
      </div>` : ""}

      <button class="pill" style="width:100%;justify-content:center;margin-top:8px"
              onclick="window.location.href='/resume-evaluate'">
        查看完整档案
      </button>
    `;

    // HR 状态保存
    const select = document.getElementById("detail-engagement-select");
    const saveBtn = document.getElementById("detail-engagement-save");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        try {
          await updateEngagementStatus(candidateId, select.value, "hr-web", "网页修改");
          showToast("HR 状态已更新");
        } catch (err) {
          showToast(err.message);
        }
      });
    }
  }

  // ---- 事件绑定 ----
  let searchTimer;
  els.search.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      state.search = e.target.value.trim();
      await reload();
    }, 200);
  });

  els.sourceSeg.querySelectorAll(".pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.sourceSeg.querySelectorAll(".pill").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.source = btn.dataset.source;
      renderList();
    });
  });

  els.filterChips.querySelectorAll(".pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.filterChips.querySelectorAll(".pill").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.track = btn.dataset.track;
      renderList();
    });
  });

  // ---- 初始化 ----
  async function reload() {
    try {
      state.persons = await fetchPersons();
      updateCounts();
      renderList();
    } catch (err) {
      els.list.innerHTML = `<div class="pool-list-empty muted">加载失败：${esc(err.message)}</div>`;
    }
  }

  let toastTimer;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("is-visible"), 3000);
  }
  window.showToast = showToast;

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }

  window.TalentPool = { state, reload, classifyTrack, classifySource };
  reload();
})();