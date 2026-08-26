import type {
  CandidateBrief,
  CandidateDetail,
  ChatConversation,
  ChatMessage,
  GrillDeliverables,
  GrillSessionState,
  GrillSessionSummary,
  HealthReport,
  JdEntry,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
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
    /** 人才评估目录：队列 ∪ 有准入报告的候选人（含已过队列保留期/已软移出但报告仍在的人） */
    evaluationDirectory: () => fetchJSON<CandidateBrief[]>("/api/evaluation-candidates"),
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
    list: (params?: { person_type?: string; name?: string; q?: string; level?: string; group_id?: string }) => {
      const qs = new URLSearchParams();
      if (params?.person_type) qs.set("person_type", params.person_type);
      if (params?.name) qs.set("name", params.name);
      if (params?.q) qs.set("q", params.q);
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
    batchEvaluate: (personIds: string[]) =>
      fetchJSON<{ started: number; total: number; results: { person_id: string; status: string; candidate_id?: string }[] }>(`/api/persons/batch-evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_ids: personIds }),
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
  jds: {
    list: () => fetchJSON<JdEntry[]>("/api/jds"),
    parse: (text: string) =>
      fetchJSON<{ title: string; team: string }>("/api/jds/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    create: (data: { title: string; team: string; raw_text: string }) =>
      fetchJSON<JdEntry>("/api/jds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    update: (id: string, data: { title: string; team: string; raw_text: string; supplements?: string[] }) =>
      fetchJSON<JdEntry>(`/api/jds/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      fetchJSON<{ id: string; deleted: boolean }>(`/api/jds/${id}`, { method: "DELETE" }),
    generateCard: (id: string, supplements: string[]) =>
      fetchJSON<JdEntry>(`/api/jds/${id}/assessment-card`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ supplements }),
      }),
    setArchived: (id: string, archived: boolean) =>
      fetchJSON<JdEntry>(`/api/jds/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: archived ? "archived" : "draft" }),
      }),
  },
  interviewAssessments: {
    start: (candidateIds: string[], jdIds: string[]) =>
      fetchJSON<InterviewAssessmentBatch>("/api/interview-assessment-batches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_ids: candidateIds, jd_ids: jdIds }),
      }),
    batch: (id: string) =>
      fetchJSON<InterviewAssessmentBatch>(`/api/interview-assessment-batches/${id}`),
    cancelBatch: (id: string) =>
      fetchJSON<{ batch_id: string; cancelled: number }>(`/api/interview-assessment-batches/${id}/cancel`, { method: "POST" }),
    cancelRun: (id: string) =>
      fetchJSON<{ run_id: string; cancelled: boolean }>(`/api/interview-assessment-runs/${id}/cancel`, { method: "POST" }),
    active: () => fetchJSON<InterviewAssessmentRun[]>("/api/interview-assessment-runs/active"),
    list: (candidateIds?: string[], jdIds?: string[]) => {
      const query = new URLSearchParams();
      if (candidateIds?.length) query.set("candidate_ids", candidateIds.join(","));
      if (jdIds?.length) query.set("jd_ids", jdIds.join(","));
      return fetchJSON<InterviewAssessment[]>(`/api/interview-assessments?${query}`);
    },
  },
  tracks: {
    active: () => fetchJSON<{ key: string; label: string }[]>("/api/tracks/active"),
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
  personResume: (personId: string) =>
    fetchJSON<CandidateDetail>(`/api/persons/${personId}/resume`),
  share: {
    create: (personId: string) =>
      fetchJSON<{ share_path: string; token: string }>(`/api/persons/${personId}/share`, { method: "POST" }),
    revoke: (personId: string) =>
      fetchJSON<{ revoked: boolean }>(`/api/persons/${personId}/share`, { method: "DELETE" }),
    // 公开端点（无鉴权，凭随机 token）
    get: (token: string) => fetchJSON<PersonDetail>(`/api/share/${token}`),
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
    askSSE: (conversationId: string, prompt: string, lang: "zh" | "en" = "zh") =>
      fetch(BASE + "/api/knowledge/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, prompt, lang }),
      }),
    actionSSE: (
      conversationId: string,
      actionId: string,
      decision: Record<string, unknown>,
      lang: "zh" | "en" = "zh"
    ) =>
      fetch(BASE + "/api/knowledge/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, action_id: actionId, decision, lang }),
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
  grill: {
    listSessions: () => fetchJSON<{ sessions: GrillSessionSummary[] }>("/api/grill/sessions"),
    createSession: () =>
      fetchJSON<{ session_id: string }>("/api/grill/sessions", { method: "POST" }),
    deleteSession: (sid: string) =>
      fetchJSON<{ deleted: number }>(`/api/grill/sessions/${sid}`, { method: "DELETE" }),
    deleteSessions: (sids: string[]) =>
      fetchJSON<{ deleted: number }>("/api/grill/sessions/batch-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_ids: sids }),
      }),
    getState: (sid: string) => fetchJSON<GrillSessionState>(`/api/grill/sessions/${sid}/state`),
    regenerateDeliverables: (sid: string) =>
      fetchJSON<GrillDeliverables>(`/api/grill/sessions/${sid}/deliverables/regenerate`, {
        method: "POST",
      }),
    chatSSE: (sid: string, message: string) =>
      fetch(BASE + "/api/grill/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message }),
      }),
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
