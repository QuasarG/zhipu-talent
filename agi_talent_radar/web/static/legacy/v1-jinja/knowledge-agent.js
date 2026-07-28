/* ============================================================================
   人才知识 Agent 对话 JS（模块 10-12）
   原生 JS，无框架。接入 /api/knowledge/ask SSE 流。
   ========================================================================== */

(function () {
  "use strict";

  const els = {
    conversation: document.getElementById("ka-conversation"),
    empty: document.getElementById("ka-empty"),
    messages: document.getElementById("ka-messages"),
    input: document.getElementById("ka-input"),
    send: document.getElementById("ka-send"),
    traceBody: document.getElementById("ka-trace-body"),
    traceToggle: document.querySelector(".ka-trace-toggle"),
    personContext: document.getElementById("ka-person-context"),
    personName: document.getElementById("ka-person-name"),
    personMeta: document.getElementById("ka-person-meta"),
    personStatus: document.getElementById("ka-person-status"),
    contextPill: document.getElementById("ka-context"),
    toast: document.getElementById("toast"),
    newBtn: document.getElementById("ka-new-investigate"),
  };

  let isAsking = false;

  // ---- 发送 ----
  function send() {
    const prompt = els.input.value.trim();
    if (!prompt || isAsking) return;
    isAsking = true;
    els.send.disabled = true;

    // 显示对话区
    els.empty.hidden = true;
    els.messages.hidden = false;

    // 渲染用户消息
    appendMessage("user", prompt);
    els.input.value = "";

    // 清空 trace
    els.traceBody.innerHTML = "";

    // 发起 SSE
    askKnowledge(prompt);
  }

  async function askKnowledge(prompt) {
    try {
      const resp = await fetch("/api/knowledge/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, conversation_id: "default" }),
        cache: "no-store",
      });
      if (!resp.ok) throw new Error(`请求失败: ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let agentMsg = null;

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
            agentMsg = handleEvent(event, agentMsg);
          } catch (e) { /* skip */ }
        }
      }
    } catch (err) {
      appendMessage("agent", `⚠️ ${esc(err.message)}`);
      showToast(err.message);
    } finally {
      isAsking = false;
      els.send.disabled = false;
    }
  }

  function handleEvent(event, agentMsg) {
    const { type, payload } = event;

    if (type === "intent") {
      const intent = payload.intent;
      const scope = (payload.scope || []).join(", ");
      addTraceNode("意图识别", "ok", `${intentLabel(intent)}${scope ? " · " + scope : ""}`);
      return agentMsg;
    }

    if (type === "clarification") {
      agentMsg = appendMessage("agent", "");
      agentMsg.querySelector(".ka-agent-body").innerHTML = `<p>${esc(payload.message)}</p>`;
      return agentMsg;
    }

    if (type === "local_facts") {
      const count = payload.count;
      const sufficient = payload.sufficient;
      addTraceNode(
        "MySQL 人才库检索",
        "ok",
        `命中 ${count} 条${sufficient ? " · 库内足够" : " · 需要外部补充"}`
      );
      return agentMsg;
    }

    if (type === "tool_plan") {
      const tools = payload.tools || [];
      if (tools.length && tools[0] !== "none") {
        addTraceNode("工具规划", "ok", `将调用：${tools.join(", ")}`);
      } else {
        addTraceNode("工具规划", "ok", "库内足够，不调用外部");
      }
      return agentMsg;
    }

    if (type === "external_fact") {
      addTraceNode("外部调查", "ok", `新增 ${payload.count} 条事实`);
      return agentMsg;
    }

    if (type === "tool_failure") {
      const failed = payload.failed_tools || [];
      addTraceNode("部分链路失败", "warning", `${failed.join(", ")} 不可用`);
      return agentMsg;
    }

    if (type === "answer") {
      if (!agentMsg) {
        agentMsg = appendMessage("agent", "");
      }
      const body = agentMsg.querySelector(".ka-agent-body");
      const answer = payload.answer || "";
      const citations = payload.citations || [];

      // 渲染回答文本（简单 markdown：换行 + 列表）
      body.innerHTML = renderAnswer(answer);

      // 渲染 citation chips
      if (citations.length) {
        body.innerHTML += renderCitationChips(citations);
      }

      // 添加命令按钮
      const actions = document.createElement("div");
      actions.className = "ka-agent-actions";
      actions.innerHTML = `
        <button class="pill" onclick="navigator.clipboard.writeText(${JSON.stringify(answer)}).then(()=>showToast('已复制'))">
          <svg class="icon icon-sm"><use href="#icon-copy"></use></svg> 复制
        </button>
      `;
      agentMsg.appendChild(actions);
      return agentMsg;
    }

    if (type === "warning") {
      if (agentMsg) {
        const body = agentMsg.querySelector(".ka-agent-body");
        body.innerHTML += `<p class="muted">⚠️ ${esc(payload.message)}</p>`;
      }
      return agentMsg;
    }

    if (type === "done") {
      // 滚动到底部
      els.conversation.scrollTop = els.conversation.scrollHeight;
      return agentMsg;
    }

    return agentMsg;
  }

  // ---- 渲染辅助 ----
  function renderAnswer(text) {
    // 简单 markdown：列表 / 换行
    const lines = text.split("\n");
    let html = "";
    let inList = false;
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("- ") || trimmed.startsWith("• ")) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${esc(trimmed.slice(2))}</li>`;
      } else if (trimmed) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<p>${esc(trimmed)}</p>`;
      }
    }
    if (inList) html += "</ul>";
    return html || `<p>${esc(text)}</p>`;
  }

  function renderCitationChips(citations) {
    if (!citations.length) return "";
    return `<p class="muted" style="margin-top:8px;font-size:12px">引用：${citations.map((c, i) => {
      const status = c.verification_status || "pending";
      const cls = `citation-chip citation-chip--${status}`;
      const label = citationLabel(c);
      return `<span class="${cls}" title="${esc(label)}">[${i + 1}] ${esc(c.source || "?")}</span>`;
    }).join(" ")}</p>`;
  }

  function citationLabel(c) {
    const parts = [c.source || "", c.verification_status || ""];
    if (c.fetched_at) parts.push(new Date(c.fetched_at).toLocaleDateString("zh-CN"));
    return parts.filter(Boolean).join(" · ");
  }

  function intentLabel(intent) {
    const labels = {
      pool_query: "库内查询",
      known_person: "已知人物调查",
      talent_discovery: "人才发现（不支持）",
      unsupported: "不支持",
    };
    return labels[intent] || intent;
  }

  // ---- DOM 操作 ----
  function appendMessage(role, text) {
    const msg = document.createElement("div");
    if (role === "user") {
      msg.className = "ka-msg-user";
      msg.textContent = text;
    } else {
      msg.className = "ka-msg-agent";
      msg.innerHTML = `
        <div class="ka-agent-head">
          <span class="ka-agent-icon"><svg><use href="#icon-check"></use></svg></span>
          <span class="ka-agent-name">人才知识 Agent</span>
        </div>
        <div class="ka-agent-body">${esc(text)}</div>
      `;
    }
    els.messages.appendChild(msg);
    els.conversation.scrollTop = els.conversation.scrollHeight;
    return msg;
  }

  function addTraceNode(name, status, meta) {
    const iconMap = {
      ok: '<svg><use href="#icon-check"></use></svg>',
      running: '<svg><use href="#icon-clock"></use></svg>',
      warning: '<svg><use href="#icon-warning"></use></svg>',
    };
    const node = document.createElement("div");
    node.className = "trace-node";
    node.innerHTML = `
      <span class="trace-node-icon ${status}">${iconMap[status] || iconMap.ok}</span>
      <div class="trace-node-body">
        <div class="trace-node-name">${esc(name)}</div>
        <div class="trace-node-meta">${esc(meta || "")}</div>
      </div>
    `;
    els.traceBody.appendChild(node);
  }

  // ---- 事件绑定 ----
  els.send.addEventListener("click", send);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  els.newBtn.addEventListener("click", () => {
    els.messages.innerHTML = "";
    els.messages.hidden = true;
    els.empty.hidden = false;
    els.traceBody.innerHTML = '<div class="ka-trace-empty muted">执行链将在提问后显示</div>';
    els.personContext.hidden = true;
    els.input.focus();
  });

  els.traceToggle.querySelectorAll(".pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.traceToggle.querySelectorAll(".pill").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      // 切换 trace / citations 视图（citations 暂用空态）
      const tab = btn.dataset.tab;
      if (tab === "citations") {
        els.traceBody.innerHTML = '<div class="ka-trace-empty muted">引用将在回答后显示</div>';
      }
    });
  });

  // ---- 工具函数 ----
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

  els.input.focus();
})();