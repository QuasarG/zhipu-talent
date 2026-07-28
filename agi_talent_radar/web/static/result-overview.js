/* ============================================================================
   评估结果区（模块 7）：能力总览 + 分维度条形图 + Track 推荐 + 研究组匹配。
   监听 candidate-selected，从 detail.evaluation 读取数据。
   ========================================================================== */

(function () {
  "use strict";

  const pane = document.getElementById("result-pane");

  window.addEventListener("candidate-selected", (e) => {
    render(e.detail);
  });

  function render(detail) {
    const ev = detail.evaluation || detail.latest_evaluation;
    if (!ev) {
      pane.innerHTML = `
        <div class="pane-empty muted">
          <p>尚未评估</p>
          <p class="sub">选择候选人并点击评估后，能力评分与 Track 推荐将显示在此</p>
        </div>`;
      return;
    }
    const dims = extractDimensions(ev);
    const tracks = ev.recommended_tracks || [];
    const rgStatus = ev.research_group_matching_status || "not_configured";

    pane.innerHTML = `
      ${renderScoreOverview(ev, dims)}
      ${renderDimensions(dims)}
      ${renderTrackRecommendation(tracks, ev.routing_confidence)}
      ${renderResearchGroupMatching(rgStatus)}
      <div id="result-extra"></div>
    `;
  }

  // ---- 能力总览 ----
  function renderScoreOverview(ev, dims) {
    const evidenceCount = (ev.evidence || []).length;
    return `
      <section class="result-section">
        <div class="score-overview">
          <div class="score-main">
            <span class="score-number">${ev.overall_score ?? "—"}</span>
            <span class="score-unit muted">/ 100</span>
          </div>
          <div class="score-meta">
            <p class="score-label">能力总分</p>
            <p class="score-disclaimer muted">仅用于能力描述，不代表录取结论</p>
          </div>
          <div class="score-badges">
            ${ev.routing_confidence ? `<span class="badge badge--info">路由置信度 ${(ev.routing_confidence * 100).toFixed(0)}%</span>` : ""}
            ${evidenceCount ? `<span class="badge badge--neutral">证据 ${evidenceCount} 条</span>` : ""}
          </div>
        </div>
      </section>`;
  }

  // ---- 分维度条形图 ----
  function extractDimensions(ev) {
    const common = ev.dimension_scores || [];
    return common.map((d) => ({
      label: d.label || d.key || "",
      score: d.score || 0,
      max: d.max_points || 20,
    }));
  }

  function renderDimensions(dims) {
    if (!dims.length) return "";
    const colors = ["var(--teal-700)", "var(--blue-700)", "var(--amber-700)", "var(--teal-500)", "var(--coral-700)"];
    return `
      <section class="result-section">
        <h3 class="result-section-title">能力维度</h3>
        <div class="dim-chart">
          ${dims.map((d, i) => {
            const pct = d.max > 0 ? (d.score / d.max) * 100 : 0;
            const color = colors[i % colors.length];
            return `
              <div class="dim-row">
                <span class="dim-label">${esc(d.label)}</span>
                <div class="dim-bar-track">
                  <div class="dim-bar-fill" style="width:${pct}%;background:${color}"></div>
                </div>
                <span class="dim-score mono">${d.score}/${d.max}</span>
              </div>`;
          }).join("")}
        </div>
      </section>`;
  }

  // ---- Track 推荐 ----
  function renderTrackRecommendation(tracks, routingConfidence) {
    if (!tracks.length) return "";
    return `
      <section class="result-section">
        <div class="result-section-head">
          <h3 class="result-section-title">推荐 Track</h3>
          ${routingConfidence ? `<span class="badge badge--neutral">路由置信度 ${(routingConfidence * 100).toFixed(0)}%</span>` : ""}
        </div>
        <div class="track-list">
          ${tracks.map((t) => {
            const track = t.track || t.name || t.key || "";
            const weight = t.weight || 0;
            const rationale = t.rationale || t.reason || "";
            const pct = (weight * 100).toFixed(0);
            return `
              <div class="track-item">
                <div class="track-head">
                  <span class="track-name">${esc(track)}</span>
                  <span class="track-weight mono">${pct}%</span>
                </div>
                <div class="track-bar-track">
                  <div class="track-bar-fill" style="width:${pct}%"></div>
                </div>
                ${rationale ? `<p class="track-rationale muted">${esc(rationale)}</p>` : ""}
              </div>`;
          }).join("")}
        </div>
      </section>`;
  }

  // ---- 研究组匹配（独立横条，固定 not_configured） ----
  function renderResearchGroupMatching(status) {
    const isNotConfigured = status === "not_configured";
    return `
      <section class="result-section">
        <div class="rg-match-bar ${isNotConfigured ? "is-pending" : ""}">
          <div class="rg-match-left">
            <h3 class="rg-match-title">研究组匹配</h3>
            <p class="rg-match-status">
              ${isNotConfigured
                ? '<span class="badge badge--neutral">尚未配置研究组要求</span>'
                : `<span class="badge badge--info">${esc(status)}</span>`}
            </p>
          </div>
          <p class="rg-match-note muted">Track 推荐不等于具体研究组匹配</p>
        </div>
      </section>`;
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }

  // 暴露给模块 8（论文核验 + 面谈建议）
  window.ResultPane = { pane, render };
})();