window.ImportProgress = (() => {
  const STAGE_META = {
    validation: { label: "文件校验" },
    rendering: { label: "PDF 渲染", pdfOnly: true },
    vision: { label: "视觉理解", pdfOnly: true },
    classification: { label: "初筛分类" },
  };

  function createState(file) {
    const isPdf = file.name.toLowerCase().endsWith(".pdf");
    const stages = Object.entries(STAGE_META)
      .filter(([, meta]) => isPdf || !meta.pdfOnly)
      .map(([key, meta]) => ({ key, label: meta.label, status: "pending", message: "等待执行" }));
    return { fileName: file.name, stages, status: "running", message: "正在上传简历文件…" };
  }

  function applyEvent(state, event) {
    if (event.type === "stage") {
      const stage = state.stages.find((item) => item.key === event.stage);
      if (stage) {
        stage.status = event.status || "running";
        stage.message = event.message || stage.message;
      }
      state.message = event.message || state.message;
    } else if (event.type === "done") {
      state.status = "done";
      state.message = event.message || "导入完成。";
    } else if (event.type === "error") {
      state.status = "error";
      state.message = event.message || "导入失败。";
      const stage = state.stages.find((item) => item.key === event.stage);
      if (stage) stage.status = "error";
    }
    return state;
  }

  function cancel(state) {
    state.status = "cancelled";
    state.message = "已取消本次导入。";
    const running = state.stages.find((item) => item.status === "running");
    if (running) running.status = "cancelled";
    return state;
  }

  function statusLabel(status) {
    const labels = {
      pending: "等待",
      running: "进行中",
      done: "完成",
      error: "失败",
      cancelled: "已取消",
    };
    return labels[status] || status;
  }

  return { createState, applyEvent, cancel, statusLabel };
})();
