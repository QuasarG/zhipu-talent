/* ============================================================================
   简历导入 SSE 流（模块 9）：
   点击导入按钮 → 上传文件 → SSE 流式解析 → 队列进度 + 单条失败隔离。
   接入 /api/import-file（事件 type=stage/candidate/done/error）。
   ========================================================================== */

(function () {
  "use strict";

  const fileInput = document.getElementById("import-file-input");
  const queueList = document.getElementById("queue-list");
  const toast = document.getElementById("toast");

  if (!fileInput) return;

  fileInput.addEventListener("change", handleFiles);

  async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    e.target.value = ""; // 允许重复选择同一文件

    // 创建导入进度浮层
    const overlay = createImportOverlay(files);
    document.body.appendChild(overlay);

    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));

    try {
      const resp = await fetch("/api/import-file", {
        method: "POST",
        body: formData,
        cache: "no-store",
      });
      if (!resp.ok) throw new Error(`导入失败: ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const fileStates = {}; // file_id → { stage, status, message }

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
            handleImportEvent(event, fileStates, overlay);
          } catch (err) { /* skip */ }
        }
      }
    } catch (err) {
      showToast(err.message);
    } finally {
      // 延迟关闭浮层
      setTimeout(() => {
        overlay.classList.add("is-fading");
        setTimeout(() => overlay.remove(), 300);
      }, 1500);
      // 刷新候选人列表
      if (window.ResumeWorkbench) {
        try {
          window.ResumeWorkbench.state.candidates = await window.ResumeWorkbench.fetchCandidates();
          window.ResumeWorkbench.updateCounts();
          window.ResumeWorkbench.renderQueue();
        } catch (err) { /* skip */ }
      }
    }
  }

  function createImportOverlay(files) {
    const overlay = document.createElement("div");
    overlay.className = "import-overlay";
    overlay.innerHTML = `
      <div class="import-overlay-card glass">
        <div class="import-overlay-head">
          <span class="import-overlay-title">导入简历</span>
          <span class="import-overlay-count muted">${files.length} 个文件</span>
        </div>
        <div class="import-overlay-list" id="import-file-list">
          ${files.map((f, i) => `
            <div class="import-file-row" data-file-id="file-${i + 1}" data-file-name="${esc(f.name)}">
              <div class="import-file-head">
                <span class="import-file-name">${esc(f.name)}</span>
                <span class="import-file-status badge badge--neutral">等待中</span>
              </div>
              <div class="import-file-stage muted"></div>
            </div>
          `).join("")}
        </div>
      </div>
    `;
    return overlay;
  }

  function handleImportEvent(event, fileStates, overlay) {
    const fileId = event.file_id;
    const fileName = event.file_name;
    if (!fileId) return;

    const row = overlay.querySelector(`[data-file-id="${CSS.escape(fileId)}"]`);
    if (!row) return;

    const statusEl = row.querySelector(".import-file-status");
    const stageEl = row.querySelector(".import-file-stage");

    if (event.type === "stage") {
      const status = event.status; // running / done
      const stage = event.stage;   // validation / extracting / classification
      const message = event.message || "";
      if (status === "running") {
        statusEl.className = "import-file-status badge badge--info";
        statusEl.textContent = stage || "处理中";
      } else if (status === "done") {
        statusEl.className = "import-file-status badge badge--confirmed";
        statusEl.textContent = "完成";
      }
      stageEl.textContent = message;
    } else if (event.type === "candidate") {
      // 解析出候选人
      stageEl.textContent = `已识别 ${event.total || 1} 位候选人`;
    } else if (event.type === "error") {
      statusEl.className = "import-file-status badge badge--conflict";
      statusEl.textContent = "失败";
      stageEl.textContent = event.message || `失败于 ${event.stage || "未知阶段"}`;
    } else if (event.type === "done") {
      // 整体完成
      const imported = event.imported_files || 0;
      const failed = event.failed_files || 0;
      const total = event.total || 0;
      if (failed > 0) {
        showToast(`导入完成：${imported} 份成功，${failed} 份失败，${total} 位候选人`);
      } else {
        showToast(`导入完成：${imported} 份成功，${total} 位候选人`);
      }
    }
  }

  function showToast(msg) {
    if (window.ResumeWorkbench) {
      window.ResumeWorkbench.showToast(msg);
    } else if (toast) {
      toast.textContent = msg;
      toast.classList.add("is-visible");
      setTimeout(() => toast.classList.remove("is-visible"), 3000);
    }
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }
})();