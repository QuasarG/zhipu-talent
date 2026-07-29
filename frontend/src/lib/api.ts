import type {
  AgentEvent,
  CandidateBrief,
  CandidateDetail,
  HealthReport,
  PersonBrief,
  PersonDetail,
  ReputationReport,
} from "./types";

const BASE = "";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, init);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ---- 候选人 ----
export const api = {
  candidates: {
    list: () => fetchJSON<CandidateBrief[]>("/api/candidates"),
    get: (id: string) => fetchJSON<CandidateDetail>(`/api/candidates/${id}`),
    delete: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/candidates/${id}`, { method: "DELETE" }),
    // 已评估候选人软移出：数据保留（已在人才库），仅退出队列
    dismiss: (id: string) =>
      fetchJSON<{ id: string; group: string; dismissed: boolean }>(`/api/candidates/${id}/dismiss`, {
        method: "POST",
      }),
    evaluateSSE: (id: string, signal?: AbortSignal) =>
      fetch(BASE + `/api/candidates/${id}/evaluate`, { method: "POST", signal }),
    updateEngagement: (id: string, status: string, changedBy: string, note: string) =>
      fetchJSON(`/api/candidates/${id}/engagement-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, changed_by: changedBy, note }),
      }),
    engagementHistory: (id: string) =>
      fetchJSON<unknown[]>(`/api/candidates/${id}/engagement-history`),
  },
  persons: {
    list: (params?: { person_type?: string; name?: string; level?: string }) => {
      const qs = new URLSearchParams();
      if (params?.person_type) qs.set("person_type", params.person_type);
      if (params?.name) qs.set("name", params.name);
      if (params?.level) qs.set("level", params.level);
      return fetchJSON<PersonBrief[]>(`/api/persons?${qs}`);
    },
    get: (id: string) => fetchJSON<PersonDetail>(`/api/persons/${id}`),
    admit: (id: string, changedBy: string, note: string) =>
      fetchJSON(`/api/persons/${id}/admit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changed_by: changedBy, note }),
      }),
    reputation: (id: string) =>
      fetchJSON<ReputationReport[]>(`/api/persons/${id}/reputation`),
    delete: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/persons/${id}`, { method: "DELETE" }),
  },
  reputation: {
    review: (reportId: number, action: "confirmed" | "dismissed", reviewer: string, note: string) =>
      fetchJSON<ReputationReport>(`/api/reputation/${reportId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer, note }),
      }),
  },
  import: (formData: FormData) =>
    fetch(BASE + "/api/import-file", { method: "POST", body: formData }),
  knowledge: {
    askSSE: (prompt: string, conversationId = "default") =>
      fetch(BASE + "/api/knowledge/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, conversation_id: conversationId }),
      }),
  },
  config: {
    get: () => fetchJSON<Record<string, unknown>>("/api/config"),
    put: (updates: Record<string, string>) =>
      fetchJSON("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      }),
    test: () => fetchJSON<{ llm: { ok: boolean; reason?: string } }>("/api/config/test"),
  },
  auth: {
    login: (password: string) =>
      fetchJSON("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      }),
    logout: () => fetchJSON("/api/auth/logout", { method: "POST" }),
    status: () => fetchJSON<{ authenticated: boolean }>("/api/auth/status"),
  },
  health: () => fetchJSON<HealthReport>("/health"),
};

// ---- SSE 流解析 ----
export async function* parseSSE(
  response: Response,
  signal?: AbortSignal
): AsyncGenerator<AgentEvent | Record<string, unknown>> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.length ? lines.pop()! : "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const payload = trimmed.slice(6);
        try {
          yield JSON.parse(payload);
        } catch {
          /* skip */
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
