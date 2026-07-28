/* 设置页 JS：GET /api/config 脱敏读取 + PUT 原子写入 + 连接测试 */
(function () {
  "use strict";

  const groups = {
    "settings-llm": ["DEEPSEEK_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_TIMEOUT_SECONDS"],
    "settings-search": ["Z_AI_API_KEY", "Z_AI_MODE", "AMINER_AUTH_TOKEN", "AMINER_MCP_URL", "OPENALEX_MAILTO"],
    "settings-vector": ["QDRANT_URL", "QDRANT_API_KEY", "QDRANT_COLLECTION"],
    "settings-db": ["DB_USER", "DB_HOST", "DB_PORT", "DB_NAME"],
  };
  const sensitiveKeys = new Set(["DEEPSEEK_API_KEY", "Z_AI_API_KEY", "AMINER_AUTH_TOKEN", "QDRANT_API_KEY", "DB_PASSWORD", "APP_AUTH_PASSWORD", "FLASK_SESSION_SECRET"]);

  async function loadConfig() {
    const resp = await fetch("/api/config");
    if (!resp.ok) return;
    const data = await resp.json();
    Object.entries(groups).forEach(([containerId, keys]) => {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = keys
        .filter((k) => data[k] !== undefined)
        .map((k) => {
          const val = data[k];
          const isSensitive = sensitiveKeys.has(k);
          const display = isSensitive
            ? (val.configured ? val.masked : "未配置")
            : val;
          return `
            <div class="settings-field">
              <span class="settings-field-label">${k}</span>
              <input class="settings-field-value ${isSensitive ? "masked" : ""}"
                     data-key="${k}" data-sensitive="${isSensitive}"
                     value="${esc(display)}" placeholder="${isSensitive ? "输入新值以更新" : ""}">
            </div>`;
        }).join("");
    });
  }

  document.getElementById("settings-save")?.addEventListener("click", async () => {
    const updates = {};
    document.querySelectorAll(".settings-field-value").forEach((el) => {
      const key = el.dataset.key;
      const val = el.value.trim();
      // 敏感字段只有用户输入了新值才提交
      if (el.dataset.sensitive === "true" && val.includes("***")) return;
      if (val) updates[key] = val;
    });
    if (!Object.keys(updates).length) return;
    const resp = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    const result = await resp.json();
    if (resp.ok) {
      alert("配置已保存");
      loadConfig();
    } else {
      alert("保存失败：" + (result.detail || ""));
    }
  });

  document.getElementById("settings-test")?.addEventListener("click", async () => {
    const resultEl = document.getElementById("settings-test-result");
    resultEl.hidden = false;
    resultEl.textContent = "测试中…";
    try {
      const resp = await fetch("/api/config/test");
      const data = await resp.json();
      const llm = data.llm || {};
      resultEl.innerHTML = `LLM: ${llm.ok ? "✓ 可用" : "✗ " + (llm.reason || "失败")}`;
    } catch (err) {
      resultEl.textContent = "测试失败：" + err.message;
    }
  });

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }

  loadConfig();
})();