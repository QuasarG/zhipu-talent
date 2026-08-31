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
  PersonBrief,
  PersonDetail,
  ReputationReport,
  ResumeVersionEntry,
  ResumeOriginalMetadata,
  ScholarshipApplication,
  ScholarshipEvaluation,
  ScholarshipReputationItem,
  TalentGroup,
} from "./types";

const BASE = "";
export const UNAUTHORIZED_EVENT = "talent-radar:unauthorized";

export class UnauthorizedError extends Error {
  readonly status = 401;

  constructor(message = "未鉴权，请先登录。") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, { cache: "no-store", ...init });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    if (resp.status === 401) {
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT, { detail: { url } }));
      }
      throw new UnauthorizedError(err.detail);
    }
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// 统一认证 fetch：非 JSON 场景（文件上传、SSE 流）也要一致的 401 处理，
// 会话过期时派发同一事件由全局边界跳登录，而不是各调用点自行其是。
export async function authedFetch(url: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(BASE + url, { cache: "no-store", ...init });
  if (resp.status === 401) {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT, { detail: { url } }));
    }
    throw new UnauthorizedError();
  }
  return resp;
}

// ---- 候选人 ----
export const api = {
  candidates: {
    /** 统一人才目录：已入库或拥有准入报告的候选人（与人才库列表同源） */
    list: () => fetchJSON<CandidateBrief[]>("/api/candidates"),
    get: (id: string) => fetchJSON<CandidateDetail>(`/api/candidates/${id}`),
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
    originalMetadata: (id: string) =>
      fetchJSON<ResumeOriginalMetadata>(`/api/candidates/${id}/original-metadata`),
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
    setNameNote: (id: string, note: string) =>
      fetchJSON<{ name_note: string; display_name: string }>(`/api/persons/${id}/name-note`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name_note: note }),
      }),
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
    resolveDeck: (ids: string[]) =>
      fetchJSON<{
        schema_version: "comparison-deck.v2";
        entries: Array<{ input_id: string; person_id: string; candidate_id: string; name: string; migrated: boolean }>;
        invalid: Array<{ input_id: string; reason: string }>;
      }>("/api/persons/resolve-deck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      }),
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
    start: (
      pairs: Array<{ candidate_id: string; jd_id: string }>,
      requestId: string,
      forceReason = "",
    ) =>
      fetchJSON<InterviewAssessmentBatch>("/api/interview-assessment-batches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pairs, request_id: requestId, force_reason: forceReason }),
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
    authedFetch("/api/import-file", { method: "POST", body: formData }),
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
      authedFetch("/api/knowledge/ask", {
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
      authedFetch("/api/knowledge/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, action_id: actionId, decision, lang }),
      }),
  },
  config: {
    get: () => fetchJSON<Record<string, unknown>>("/api/config"),
    audit: () => fetchJSON<Record<string, { changed_by: string; changed_at: string }>>("/api/config/audit"),
    put: (updates: Record<string, string>) =>
      fetchJSON<{
        applied: Record<string, unknown>;
        rejected: Record<string, string>;
        runtime_refreshed: boolean;
        audit_status: "recorded" | "failed" | "not_required";
        warning?: string;
      }>("/api/config", {
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
      authedFetch("/api/grill/chat", {
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
  // 静默看门狗：流被中间层掐断时 reader.read() 会永久 pending，
  // 超过该时长无任何字节则判定断流，抛错让上层把卡片标失败并复位状态。
  const IDLE_TIMEOUT_MS = 120_000;

  try {
    while (true) {
      if (signal?.aborted) break;
      const { value, done } = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          setTimeout(() => reject(new Error("SSE_IDLE_TIMEOUT")), IDLE_TIMEOUT_MS);
        }),
      ]).catch((err) => {
        if (err instanceof Error && err.message === "SSE_IDLE_TIMEOUT") {
          void reader.cancel().catch(() => undefined);
          throw new Error("连接中断，导入已停止");
        }
        throw err;
      });
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
