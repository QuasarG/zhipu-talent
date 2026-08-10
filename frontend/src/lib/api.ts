import type {
  CandidateBrief,
  CandidateDetail,
  ChatConversation,
  ChatMessage,
  HealthReport,
  PendingPublication,
  PersonBrief,
  PersonDetail,
  ReputationReport,
  ResumeVersionEntry,
  ScholarshipApplication,
  ScholarshipEvaluation,
  ScholarshipReputationItem,
  TalentGroup,
} from "./types";

const BASE = "";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, { cache: "no-store", ...init });
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
    // 仍需人工处理的 unverifiable 论文
    pendingPublications: () =>
      fetchJSON<PendingPublication[]>(`/api/candidates/pending-publications`),
    reviewPublication: (
      candidateId: string,
      alignmentIndex: number,
      action: "confirmed" | "dismissed",
      reviewer: string,
      note: string,
    ) =>
      fetchJSON<{
        candidate_id: string;
        alignment_index: number;
        human_status: "confirmed" | "dismissed";
        verification_result: CandidateBrief["verification_result"];
        evaluable: boolean;
      }>(`/api/candidates/${candidateId}/publications/${alignmentIndex}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer, note }),
      }),
    // 按需论文核验：选中候选人后触发，返回 academic_report
    verifyPublications: (id: string) =>
      fetchJSON<Record<string, unknown>>(`/api/candidates/${id}/verify-publications`, {
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
    updateSupplementary: (id: string, content: string) =>
      fetchJSON<{ id: string; supplementary_info: string }>(`/api/candidates/${id}/supplementary`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      }),
    engagementHistory: (id: string) =>
      fetchJSON<unknown[]>(`/api/candidates/${id}/engagement-history`),
  },
  persons: {
    list: (params?: { person_type?: string; name?: string; level?: string; group_id?: string }) => {
      const qs = new URLSearchParams();
      if (params?.person_type) qs.set("person_type", params.person_type);
      if (params?.name) qs.set("name", params.name);
      if (params?.level) qs.set("level", params.level);
      if (params?.group_id) qs.set("group_id", params.group_id);
      return fetchJSON<PersonBrief[]>(`/api/persons?${qs}`);
    },
    get: (id: string) => fetchJSON<PersonDetail>(`/api/persons/${id}`),
    create: (data: { name: string; org?: string; direction?: string }) =>
      fetchJSON<PersonBrief>(`/api/persons`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    admit: (id: string, changedBy: string, note: string) =>
      fetchJSON(`/api/persons/${id}/admit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changed_by: changedBy, note }),
      }),
    reputation: (id: string) =>
      fetchJSON<ReputationReport[]>(`/api/persons/${id}/reputation`),
    resumeVersions: (id: string) =>
      fetchJSON<ResumeVersionEntry[]>(`/api/persons/${id}/resume-versions`),
    delete: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/persons/${id}`, { method: "DELETE" }),
    move: (id: string, groupId: string | null) =>
      fetchJSON<{ id: string; group_id: string | null }>(`/api/persons/${id}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: groupId }),
      }),
    batchMove: (personIds: string[], groupId: string | null) =>
      fetchJSON<{ moved: number; group_id: string | null }>(`/api/persons/batch-move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_ids: personIds, group_id: groupId }),
      }),
  },
  talentGroups: {
    list: () => fetchJSON<TalentGroup[]>("/api/talent-groups"),
    create: (name: string) =>
      fetchJSON<TalentGroup>("/api/talent-groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      }),
    rename: (id: string, name: string) =>
      fetchJSON<TalentGroup>(`/api/talent-groups/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      }),
    delete: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/talent-groups/${id}`, { method: "DELETE" }),
  },
  reputation: {
    review: (reportId: number, action: "confirmed" | "dismissed", reviewer: string, note: string) =>
      fetchJSON<ReputationReport>(`/api/reputation/${reportId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer, note }),
      }),
  },
  // ---- 奖学金初筛 ----
  scholarship: {
    list: () => fetchJSON<ScholarshipApplication[]>("/api/scholarship/applications"),
    create: (data: {
      name: string;
      degree_type: string;
      expected_graduation?: string;
      direction?: string;
      school?: string;
      advisors?: string[];
    }) =>
      fetchJSON<ScholarshipApplication>("/api/scholarship/applications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    get: (id: string) => fetchJSON<ScholarshipApplication>(`/api/scholarship/applications/${id}`),
    remove: (id: string) =>
      fetchJSON<{ deleted: boolean }>(`/api/scholarship/applications/${id}`, { method: "DELETE" }),
    // multipart 上传，zip 由后端自动解包
    uploadMaterials: (id: string, files: File[]) => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      return fetchJSON<{ added: number; max_letters: number }>(
        `/api/scholarship/applications/${id}/materials`,
        { method: "POST", body: form },
      );
    },
    screen: (id: string) =>
      fetchJSON<{ status: string; missing: string[]; reasons: string[] }>(
        `/api/scholarship/applications/${id}/screen`,
        { method: "POST" },
      ),
    evaluate: (id: string) =>
      fetchJSON<ScholarshipEvaluation>(`/api/scholarship/applications/${id}/evaluate`, { method: "POST" }),
    reputationScan: (id: string) =>
      fetchJSON<{ created: number; items: ScholarshipReputationItem[] }>(
        `/api/scholarship/applications/${id}/reputation-scan`,
        { method: "POST" },
      ),
    reviewReputation: (itemId: number, action: "confirmed" | "dismissed") =>
      fetchJSON<ScholarshipReputationItem>(`/api/scholarship/reputation-items/${itemId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer: "hr" }),
      }),
    setBrand: (id: string, bonus: number, note: string) =>
      fetchJSON<ScholarshipApplication>(`/api/scholarship/applications/${id}/brand`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bonus, note }),
      }),
  },
  import: (formData: FormData) =>
    fetch(BASE + "/api/import-file", { method: "POST", body: formData }),
  chat: {
    listConversations: () => fetchJSON<ChatConversation[]>("/api/conversations"),
    createConversation: () =>
      fetchJSON<ChatConversation>("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    getMessages: (id: string) => fetchJSON<ChatMessage[]>(`/api/conversations/${id}/messages`),
    renameConversation: (id: string, title: string) =>
      fetchJSON<ChatConversation>(`/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    deleteConversation: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
    askSSE: (conversationId: string, prompt: string) =>
      fetch(BASE + "/api/knowledge/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, prompt }),
      }),
    actionSSE: (conversationId: string, actionId: string, decision: Record<string, unknown>) =>
      fetch(BASE + "/api/knowledge/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, action_id: actionId, decision }),
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
    login: (username: string, password: string) =>
      fetchJSON("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      }),
    logout: () => fetchJSON("/api/auth/logout", { method: "POST" }),
    status: () =>
      fetchJSON<{ authenticated: boolean; user: { id: string; username: string; display_name: string } | null }>(
        "/api/auth/status"
      ),
  },
  health: () => fetchJSON<HealthReport>("/health"),
};

// ---- SSE 流解析 ----
export async function* parseSSE(
  response: Response,
  signal?: AbortSignal
): AsyncGenerator<Record<string, unknown>> {
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
