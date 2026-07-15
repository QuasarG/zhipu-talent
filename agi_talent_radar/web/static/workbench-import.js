window.ImportProgress = (() => {
  const STAGE_META = {
    validation: { label: "文件校验", running: 8, done: 15 },
    rendering: { label: "PDF 渲染", running: 28, done: 45 },
    vision: { label: "视觉理解", running: 60, done: 80 },
    classification: { label: "初筛分类", running: 90, done: 100 },
  };

  function createState(files) {
    const list = Array.from(files || []);
    return {
      status: "running",
      message: `正在导入 ${list.length} 份简历…`,
      items: list.map((file, index) => ({
        id: `file-${index + 1}`,
        file,
        fileName: file.name,
        status: "pending",
        stage: "validation",
        stageLabel: "等待处理",
        message: "已加入导入队列",
        progress: 0,
      })),
      importedFiles: 0,
      failedFiles: 0,
      candidateTotal: 0,
    };
  }

  function applyEvent(state, event) {
    const item = event.file_id
      ? state.items.find((entry) => entry.id === event.file_id)
      : state.items[0];
    if (event.type === "stage" && item) {
      const meta = STAGE_META[event.stage] || { label: event.stage, running: item.progress, done: item.progress };
      item.stage = event.stage;
      item.stageLabel = meta.label;
      item.status = event.status === "done" && event.stage === "classification" ? "done" : "running";
      item.progress = meta[event.status === "done" ? "done" : "running"] ?? item.progress;
      item.message = event.message || item.message;
    } else if (event.type === "candidate" && item) {
      item.candidateName = event.candidate?.name || "";
      item.progress = Math.max(item.progress, 96);
    } else if (event.type === "done") {
      state.importedFiles = Number(event.imported_files || 0);
      state.failedFiles = Number(event.failed_files || 0);
      state.candidateTotal = Number(event.total || 0);
      state.status = state.failedFiles > 0 ? "partial" : "done";
      state.message = event.message || "导入完成。";
    } else if (event.type === "error") {
      if (item) {
        const meta = STAGE_META[event.stage];
        item.status = "error";
        item.stage = event.stage || item.stage;
        item.stageLabel = meta?.label || "导入失败";
        item.message = event.message || "导入失败。";
      } else {
        state.status = "error";
        state.message = event.message || "导入失败。";
      }
    }
    return state;
  }

  function cancel(state) {
    state.status = "cancelled";
    state.message = "已取消本次导入。";
    state.items.forEach((item) => {
      if (["pending", "running"].includes(item.status)) item.status = "cancelled";
    });
    return state;
  }

  function completedCount(state) {
    return state.items.filter((item) => ["done", "error", "cancelled"].includes(item.status)).length;
  }

  function statusLabel(status) {
    const labels = {
      pending: "等待",
      running: "进行中",
      done: "完成",
      partial: "部分失败",
      error: "失败",
      cancelled: "已取消",
    };
    return labels[status] || status;
  }

  return { createState, applyEvent, cancel, completedCount, statusLabel };
})();
