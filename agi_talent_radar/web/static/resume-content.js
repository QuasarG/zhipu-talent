/* ============================================================================
   简历内容区（模块 6）：监听 candidate-selected 事件，渲染中栏。
   无框章节布局；论文条目展示自述状态；项目带证据定位标记。
   ========================================================================== */

(function () {
  "use strict";

  const pane = document.getElementById("resume-pane");
  let viewMode = "structured"; // structured | raw

  // ---- 监听候选人选中 ----
  window.addEventListener("candidate-selected", (e) => {
    render(e.detail);
  });

  // ---- 渲染 ----
  function render(detail) {
    pane.innerHTML = `
      <div class="resume-header">
        <div class="segmented resume-mode-toggle">
          <button class="pill is-active" data-mode="structured">结构化简历</button>
          <button class="pill" data-mode="raw">原文</button>
        </div>
      </div>
      <div class="resume-body" id="resume-body"></div>
    `;
    bindModeToggle(detail);
    renderStructured(detail);
  }

  function bindModeToggle(detail) {
    pane.querySelectorAll(".resume-mode-toggle .pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        pane.querySelectorAll(".resume-mode-toggle .pill").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        viewMode = btn.dataset.mode;
        if (viewMode === "raw") renderRaw(detail);
        else renderStructured(detail);
      });
    });
  }

  function renderStructured(detail) {
    const body = pane.querySelector("#resume-body");
    const directions = (detail.directions || []).filter(Boolean);
    body.innerHTML = `
      <div class="resume-title-block">
        <h2 class="resume-name">${esc(detail.name || detail.id)}</h2>
        <p class="resume-affil muted">${esc(detail.stage || "")}${detail.role ? " · " + esc(detail.role) : ""}</p>
        ${directions.length ? `<div class="resume-tags">${directions.map((d) => `<span class="badge badge--info">${esc(d)}</span>`).join("")}</div>` : ""}
      </div>
      ${section("教育经历", renderEducation(detail.education))}
      ${section("实习 / 工作经历", renderExperiences(detail.experiences))}
      ${section("项目经历", renderProjects(detail.projects))}
      ${section("论文与成果", renderPublications(detail.publications))}
      ${section("技能", renderSkills(detail.skills))}
    `;
  }

  function renderRaw(detail) {
    const body = pane.querySelector("#resume-body");
    const text = detail.raw_text || "（无原文）";
    body.innerHTML = `<pre class="resume-raw-text">${esc(text)}</pre>`;
  }

  // ---- 章节 ----
  function section(title, contentHtml) {
    if (!contentHtml.trim()) return "";
    return `
      <section class="resume-section">
        <h3 class="resume-section-title">${esc(title)}</h3>
        ${contentHtml}
      </section>`;
  }

  // ---- 教育 ----
  function renderEducation(items) {
    if (!items || !items.length) return "";
    if (typeof items[0] === "string") {
      return items.map((s) => `<p class="resume-edu-item">${esc(s)}</p>`).join("");
    }
    return items.map((edu) => `
      <div class="resume-edu-item">
        <span class="resume-edu-school">${esc(edu.school || edu.organization || edu.name || "")}</span>
        <span class="resume-edu-degree muted">${esc(edu.degree || edu.major || "")}</span>
        ${edu.period || edu.year ? `<span class="resume-edu-period muted">${esc(edu.period || edu.year || "")}</span>` : ""}
      </div>`).join("");
  }

  // ---- 实习/工作 ----
  function renderExperiences(items) {
    if (!items || !items.length) return "";
    return items.map((exp) => `
      <div class="resume-exp-item">
        <div class="resume-exp-head">
          <span class="resume-exp-role">${esc(exp.role || "")}</span>
          ${exp.organization ? `<span class="resume-exp-org muted">${esc(exp.organization)}</span>` : ""}
        </div>
        ${(exp.details || []).map((d) => `<p class="resume-exp-detail">${esc(d)}</p>`).join("")}
      </div>`).join("");
  }

  // ---- 项目 ----
  function renderProjects(items) {
    if (!items || !items.length) return "";
    return items.map((proj, i) => {
      const pageTag = proj.page ? `<span class="evidence-loc" title="证据定位">P${esc(proj.page)}</span>` : "";
      return `
        <div class="resume-proj-item">
          <div class="resume-proj-head">
            <span class="resume-proj-name">${esc(proj.name || "未命名项目")}</span>
            ${pageTag}
          </div>
          ${(proj.details || []).map((d) => `<p class="resume-proj-detail">${esc(d)}</p>`).join("")}
        </div>`;
    }).join("");
  }

  // ---- 论文 ----
  function renderPublications(items) {
    if (!items || !items.length) return "";
    return items.map((pub) => {
      if (typeof pub === "string") {
        return `<div class="resume-pub-item"><span class="resume-pub-title">${esc(pub)}</span></div>`;
      }
      const title = esc(pub.title || pub.name || "");
      const venue = pub.venue || pub.journal || "";
      const year = pub.year || "";
      const status = pub.claimed_status || pub.status || "";
      const role = pub.claimed_role || pub.role || "";
      return `
        <div class="resume-pub-item">
          <div class="resume-pub-head">
            <span class="resume-pub-title">${title}</span>
            ${status ? `<span class="badge ${pubBadgeClass(status)}">${esc(pubStatusLabel(status))}</span>` : ""}
          </div>
          <div class="resume-pub-meta muted">
            ${venue ? esc(venue) : ""}${year ? " · " + esc(year) : ""}${role ? " · " + esc(role) : ""}
          </div>
        </div>`;
    }).join("");
  }

  function pubBadgeClass(status) {
    const s = String(status || "").toLowerCase();
    if (s.includes("published") || s.includes("已发表")) return "badge--confirmed";
    if (s.includes("review") || s.includes("在审") || s.includes("submit") || s.includes("投稿") || s.includes("在投")) return "badge--pending";
    if (s.includes("draft") || s.includes("草稿")) return "badge--neutral";
    return "badge--neutral";
  }

  function pubStatusLabel(status) {
    const s = String(status || "").toLowerCase();
    if (s.includes("published") || s.includes("已发表")) return "已发表";
    if (s.includes("review") || s.includes("在审")) return "在审";
    if (s.includes("submit") || s.includes("投稿") || s.includes("在投")) return "已投稿";
    if (s.includes("accept") || s.includes("接收")) return "已接收";
    if (s.includes("draft") || s.includes("草稿")) return "草稿";
    return esc(status) || "未说明";
  }

  // ---- 技能 ----
  function renderSkills(items) {
    if (!items || !items.length) return "";
    return `<div class="resume-skills">${items.map((s) => `<span class="badge badge--neutral">${esc(s)}</span>`).join("")}</div>`;
  }

  // ---- HTML 转义 ----
  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }
})();