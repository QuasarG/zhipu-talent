/* ============================================================================
   评估结果区（模块 8）：论文核验 + 面谈建议 + SSE 评估流。
   追加到 ResultPane（模块 7 暴露的 window.ResultPane）。
   ========================================================================== */

(function () {
  "use strict";

  // ---- 论文核验 + 面谈建议：追加到 result-extra ----
  const origRender = window.ResultPane.render;
  window.ResultPane.render = function (detail) {
    origRender(detail);
    const extra = document.getElementById("result-extra");
    if (!extra) return;
    const ev = detail.evaluation || detail.latest_evaluation;
    if (!ev) return;
    extra.innerHTML = `
      ${renderPublicationVerification(ev)}
      ${renderCollapsible("核心优势", ev.core_strengths)}
      ${renderCollapsible("潜在风险", ev.potential_risks)}
      ${renderCollapsible("建议面谈问题", ev.interview_questions)}
    `;
    bindCollapsibles(extra);
    bindRetryButtons(detail);
  };

  // ---- 论文核验 ----
  function renderPublicationVerification(ev) {
    const report = ev.academic_report || {};
    const alignments = report.alignments || [];
    if (!alignments.length && !(ev.evidence || []).some((e) => e.dimension === "academic" || e.track_hints?.includes("paper"))) {
      // 无论文数据时也显示标题区（让用户知道这个区域存在）
      return `
        <section class="result-section">
          <div class="result-section-head">
            <h3 class="result-section-title">论文状态与作者顺序核验</h3>
          </div>
          <p class="muted result-empty-note">该候选人暂无论文条目。</p>
        </section>`;
    }
    return `
      <section class="result-section">
        <div class="result-section-head">
          <h3 class="result-section-title">论文状态与作者顺序核验</h3>
          <button class="pill" id="btn-retry-papers" title="重试待核查项">
            <svg class="icon icon-sm"><use href="#icon-refresh"></use></svg>
            重试待核查项
          </button>
        </div>
        <div class="pub-verify-list">
          ${alignments.map(renderAlignment).join("")}
        </div>
        ${(report.warnings || []).map((w) => `<p class="pub-warning muted">${esc(w)}</p>`).join("")}
      </section>`;
  }

  function renderAlignment(al) {
    const claim = al.claim || {};
    const title = esc(claim.title || al.claim_title || "未命名论文");
    const claimedStatus = esc(claim.claimed_status || al.verdict || "");
    const verifiedStatus = esc(al.verified_status || "");
    const verdict = (al.verdict || "").toLowerCase();
    const claimedRole = esc(claim.claimed_role || "");
    const matchedTitle = esc(al.matched_title || "");
    const discrepancies = al.discrepancies || [];

    const claimBadge = statusBadge(claimedStatus);
    const verifyBadge = verdictBadge(verdict, verifiedStatus);
    const authorBadge = claimedRole ? `<span class="badge badge--neutral">${claimedRole}</span>` : "";

    return `
      <div class="pub-verify-item">
        <div class="pub-verify-title">${title}</div>
        <div class="pub-verify-status-row">
          <div class="pub-verify-cell">
            <span class="pub-verify-cell-label muted">自述</span>
            ${claimBadge}
            ${authorBadge}
          </div>
          <div class="pub-verify-cell">
            <span class="pub-verify-cell-label muted">外部核验</span>
            ${verifyBadge}
          </div>
        </div>
        ${matchedTitle ? `<p class="pub-verify-matched muted">匹配：${matchedTitle}</p>` : ""}
        ${discrepancies.length ? `<div class="pub-verify-conflicts">${discrepancies.map((d) => `<p class="pub-verify-conflict">${esc(d)}</p>`).join("")}</div>` : ""}
        ${al.openalex_url ? `<a href="${esc(al.openalex_url)}" target="_blank" rel="noopener" class="pub-verify-link">OpenAlex 来源</a>` : ""}
      </div>`;
  }

  function statusBadge(status) {
    const s = String(status || "").toLowerCase();
    if (s.includes("已发表") || s.includes("published")) return '<span class="badge badge--confirmed">已发表</span>';
    if (s.includes("在审") || s.includes("review")) return '<span class="badge badge--pending">在审</span>';
    if (s.includes("投稿") || s.includes("在投") || s.includes("submit")) return '<span class="badge badge--pending">已投稿</span>';
    if (s.includes("接收") || s.includes("accept")) return '<span class="badge badge--pending">已接收</span>';
    if (s.includes("草稿") || s.includes("draft")) return '<span class="badge badge--neutral">草稿</span>';
    if (s.includes("verified")) return '<span class="badge badge--confirmed">已核验</span>';
    if (s.includes("mismatch")) return '<span class="badge badge--conflict">冲突</span>';
    if (s.includes("unverifiable")) return '<span class="badge badge--pending">待核查</span>';
    return '<span class="badge badge--neutral">未说明</span>';
  }

  function verdictBadge(verdict, verifiedStatus) {
    if (verdict === "verified") return '<span class="badge badge--confirmed">已核验</span>';
    if (verdict === "mismatch") return '<span class="badge badge--conflict">存在冲突</span>';
    return '<span class="badge badge--pending">待核查</span>';
  }

  // ---- 可折叠区 ----
  function renderCollapsible(title, items) {
    if (!items || !items.length) return "";
    return `
      <details class="collapsible-section">
        <summary class="collapsible-summary">${esc(title)} <span class="collapsible-count muted">(${items.length})</span></summary>
        <div class="collapsible-body">
          ${items.map((item) => `<p class="collapsible-item">${esc(item)}</p>`).join("")}
        </div>
      </details>`;
  }

  function bindCollapsibles(container) {
    container.querySelectorAll(".collapsible-section").forEach((el) => {
      el.addEventListener("toggle", () => {});
    });
  }

  // ---- 重试论文核验 ----
  function bindRetryButtons(detail) {
    const btn = document.getElementById("btn-retry-papers");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const ev = detail.evaluation || {};
      // 评估 ID 在 evaluation 节点里不一定有，用 detail.id 兜底
      const evalId = ev.id || detail.id;
      try {
        const resp = await fetch(`/api/resume-submissions/${evalId}/evaluate`, { method: "POST" });
        if (resp.ok) {
          if (window.ResumeWorkbench) window.ResumeWorkbench.showToast("论文核验任务已派发");
        } else {
          if (window.ResumeWorkbench) window.ResumeWorkbench.showToast("派发失败，请稍后重试");
        }
      } catch (err) {
        if (window.ResumeWorkbench) window.ResumeWorkbench.showToast("网络错误");
      }
      btn.disabled = false;
    });
  }

  // ---- SSE 评估流 ----
  const refreshBtn = document.getElementById("btn-refresh");

  async function startEvaluation(candidateId) {
    if (!candidateId) return;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    if (window.ResumeWorkbench) {
      window.ResumeWorkbench.els.toolbarCandidate.textContent = "评估中…";
    }
    try {
      const resp = await fetch(`/api/candidates/${candidateId}/evaluate`, {
        method: "POST",
        cache: "no-store",
      });
      if (!resp.ok) throw new Error(`评估请求失败: ${resp.status}`);
      const reader = resp.body.getReader();
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
          try {
            const event = JSON.parse(trimmed.slice(6));
            handleSSEEvent(event, candidateId);
          } catch (e) { /* skip */ }
        }
      }
    } catch (err) {
      if (window.ResumeWorkbench) window.ResumeWorkbench.showToast(err.message);
    } finally {
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove("is-spinning");
      }
    }
  }

  function handleSSEEvent(event, candidateId) {
    if (event.type === "node") {
      // 可以更新工具条状态
      if (window.ResumeWorkbench) {
        window.ResumeWorkbench.els.toolbarCandidate.textContent = `${event.label || event.node}…`;
      }
    } else if (event.type === "result") {
      // 评估完成，重新加载详情
      if (window.ResumeWorkbench) {
        window.ResumeWorkbench.selectCandidate(candidateId);
      }
      if (window.ResumeWorkbench) window.ResumeWorkbench.showToast("评估完成");
    } else if (event.type === "error") {
      if (window.ResumeWorkbench) window.ResumeWorkbench.showToast(event.message || "评估失败");
    }
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      const id = window.ResumeWorkbench?.state?.selectedId;
      if (id) startEvaluation(id);
    });
  }

  // 暴露给模块 9
  window.EvaluationSSE = { startEvaluation };

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }
})();