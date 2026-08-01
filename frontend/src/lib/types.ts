// API 响应类型定义

export interface CandidateBrief {
  id: string;
  name: string;
  role: string;
  stage: string;
  group: string;
  level: string;
  category: string;
  engagement_status: string;
  admitted_at: string | null;
  evaluated?: boolean;
  academic_check_status?: "none" | "running" | "done";
  verification_result?: "none" | "running" | "verified" | "rejected" | "needs_review";
  evaluable?: boolean;
  evaluation_status?: "idle" | "running" | "completed" | "failed";
  evaluation_run_id?: number | null;
}

export interface CandidateDetail extends CandidateBrief {
  confidence: number;
  raw_text: string;
  supplementary_info?: string;
  education: string[] | EduItem[];
  directions: string[];
  experiences: ExperienceItem[];
  projects: ProjectItem[];
  publications: string[] | PublicationItem[];
  skills: string[];
  screening_tags: string[];
  source_format: string;
  document_analysis: Record<string, unknown>;
  person_id: string | null;
  sources: string[];
  academic_report?: AcademicReport;
  evaluation_graph: EvaluationGraph;
  evaluation?: Evaluation;
  latest_evaluation?: Evaluation;
  evaluation_run?: EvaluationRun;
}

export interface PaperClaim {
  title: string;
  venue?: string;
  year?: string;
  claimed_role?: string;
  claimed_status?: string;
}

export interface ClaimAlignment {
  claim: PaperClaim;
  verdict: "verified" | "mismatch" | "unverifiable";
  machine_verdict?: "verified" | "mismatch" | "unverifiable";
  verified_status?: string;
  matched_title?: string;
  discrepancies?: string[];
  cited_by_count?: number;
  is_retracted?: boolean;
  openalex_url?: string;
  source_url?: string;
  candidate_author_position?: number;
  candidate_author_name?: string;
  is_co_first?: boolean;
  external_record?: ExternalPaperRecord;
  checks?: VerificationChecks;
  note?: string;
  human_status?: "unreviewed" | "confirmed" | "dismissed";
  human_reviewer?: string;
  human_note?: string;
  human_reviewed_at?: string;
}

export type VerificationCheckStatus = "match" | "mismatch" | "pending";

export interface VerificationChecks {
  title: VerificationCheckStatus;
  author_identity: VerificationCheckStatus;
  author_position: VerificationCheckStatus;
  publication_status: VerificationCheckStatus;
}

export interface ExternalPaperRecord {
  source: string;
  source_url: string;
  title: string;
  authors: string[];
  venue: string;
  year: string;
  publication_status: string;
  cited_by_count: number;
  is_retracted: boolean;
}

export interface PendingPublication {
  candidate_id: string;
  alignment_index: number;
  candidate_name: string;
  title: string;
  claimed_venue?: string;
  claimed_year?: string;
  claimed_role?: string;
  claimed_status?: string;
  verdict: "unverifiable" | "mismatch";
  review_kind?: "verify" | "rehabilitate";
  note?: string;
  discrepancies?: string[];
  matched_title?: string;
  source_url?: string;
}

export interface AcademicReport {
  alignments?: ClaimAlignment[];
  warnings?: string[];
}

export interface EduItem {
  school?: string;
  organization?: string;
  name?: string;
  degree?: string;
  major?: string;
  period?: string;
  year?: string;
}

export interface ExperienceItem {
  role?: string;
  organization?: string;
  details?: string[];
}

export interface ProjectItem {
  name?: string;
  details?: string[];
  page?: number;
}

export interface PublicationItem {
  title?: string;
  name?: string;
  venue?: string;
  journal?: string;
  year?: string;
  claimed_status?: string;
  status?: string;
  claimed_role?: string;
  role?: string;
}

export interface DimensionScore {
  key: string;
  label: string;
  score: number;
  weighted_score: number;
  max_points: number;
  rationale: string;
  evidence_ids: string[];
  risk_notes: string[];
}

export interface TrackAssignment {
  track: string;
  weight: number;
  confidence: number;
  rationale: string;
  evidence_ids: string[];
}

export interface TrackRecommendation {
  track?: string;
  name?: string;
  label?: string;
  score?: number;
  weight: number;
  confidence?: number;
  rationale?: string;
  reason?: string;
  evidence_ids?: string[];
}

export interface TrackEvaluation {
  track: string;
  label: string;
  weight: number;
  confidence: number;
  raw_score: number;
  calibrated_score: number;
  dimension_scores: DimensionScore[];
  evidence_ids: string[];
  risk_notes: string[];
  critic_flags: string[];
}

export type EvaluationNodeStatus = "pending" | "running" | "done" | "skipped" | "error";

export interface EvaluationNodeRun {
  node: string;
  label?: string;
  phase: string;
  status: EvaluationNodeStatus;
  message: string;
  sequence?: number;
}

export interface EvaluationRun {
  id: number;
  candidate_id: string;
  status: "running" | "completed" | "failed";
  error_message: string;
  created_at: string | null;
  completed_at: string | null;
  evaluation_graph: EvaluationGraph;
  node_runs: EvaluationNodeRun[];
}

export interface EvaluationGraphNode {
  node: string;
  label: string;
  description: string;
  order: number;
}

export interface EvaluationGraphGroup {
  key: string;
  label: string;
  description?: string;
  collapsible?: boolean;
  nodes: EvaluationGraphNode[];
}

export interface EvaluationGraphPhase {
  key: string;
  label: string;
  description: string;
  groups: EvaluationGraphGroup[];
}

export interface EvaluationGraph {
  phases: EvaluationGraphPhase[];
}

export interface Alignment {
  claim?: {
    title?: string;
    claimed_status?: string;
    claimed_role?: string;
  };
  claim_title?: string;
  verdict: string;
  verified_status?: string;
  matched_title?: string;
  discrepancies?: string[];
  cited_by_count?: number;
  is_retracted?: boolean;
  openalex_url?: string;
  note?: string;
}

export interface Evaluation {
  id?: number;
  overall_score: number;
  one_liner: string;
  core_strengths: string[];
  potential_risks: string[];
  interview_questions: string[];
  cultivation_direction: string[];
  recommended_tracks: TrackRecommendation[];
  stage_profile: string;
  dimension_scores: DimensionScore[];
  evidence: EvidenceItem[];
  critic_flags: string[];
  normalized_education: string[];
  screening_tags: string[];
  common_score: number;
  document_score: number;
  track_assignments: TrackAssignment[];
  track_evaluations: TrackEvaluation[];
  routing_confidence: number;
  evaluation_mode: string;
  status: string;
  error_message?: string;
  created_at?: string | null;
  completed_at?: string | null;
  research_group_matching_status: string;
  academic_report?: AcademicReport;
  evaluation_graph: EvaluationGraph;
  node_runs: EvaluationNodeRun[];
}

export interface EvidenceItem {
  id: string;
  dimension: string;
  source: string;
  quote: string;
  signals: string[];
  strength: number;
  has_metric: boolean;
  has_specific_tool: boolean;
  has_ownership: boolean;
  track_hints: string[];
  page: number | null;
}

export interface PersonEducation {
  school: string;
  degree: string;
  period: string;
}

export interface PersonBrief {
  id: string;
  name: string;
  org: string;
  direction: string;
  person_type: string;
  schools?: PersonEducation[];
  top_schools?: string[];
  overall_score: number | null;
  level: string | null;
  reputation_level: string | null;
  reputation_status: string | null;
  updated_at: string | null;
  candidate_id: string | null;
  engagement_status: string;
  source_kinds: string[];
  dominant_track: string;
  dominant_track_weight: number;
}

export interface PersonDetail extends PersonBrief {
  created_at: string;
  evaluations: Evaluation[];
  reputation_reports: ReputationReport[];
}

export interface ReputationReport {
  id: number;
  person_id: string;
  level: string;
  events: Record<string, unknown>[];
  review_status: string;
  reviewer: string;
  review_note: string;
  created_at: string;
  reviewed_at: string | null;
}

// ---- 人才问答（ReAct Agent） ----

export interface ChatConversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message: string;
}

export interface ChatCitation {
  id: string;
  type: string;
  title: string;
  url: string;
  status: string;
}

export type ChatActionKind = "select_person" | "propose_add_person" | "resolve_fact_conflict" | "clarify";

export type ChatSegment =
  | { type: "text"; text: string }
  | {
      type: "tool";
      call_id: string;
      tool: string;
      label: string;
      status?: "ok" | "error";
      summary?: string;
      detail?: string;
      args_summary?: string;
    }
  | {
      type: "action";
      action_id: string;
      kind: ChatActionKind;
      payload: Record<string, unknown>;
      decision?: Record<string, unknown> | null;
    };

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: { segments: ChatSegment[] };
  citations: ChatCitation[];
  status: "completed" | "awaiting_action" | "running";
  created_at: string;
}

// 问答 SSE 事件
export type ChatEvent =
  | { type: "meta"; payload: { conversation_id: string; message_id: string } }
  | { type: "answer_delta"; payload: { text: string } }
  | { type: "tool_start"; payload: { call_id: string; tool: string; label: string; args_summary: string } }
  | { type: "tool_end"; payload: { call_id: string; tool: string; status: "ok" | "error"; summary: string; detail: string } }
  | { type: "action_required"; payload: { action_id: string; kind: ChatActionKind; payload: Record<string, unknown> } }
  | { type: "sources"; payload: { items: ChatCitation[] } }
  | { type: "message_done"; payload: { message_id: string } }
  | { type: "error"; payload: { message: string } }
  | { type: "done"; payload: { status: "completed" | "awaiting_action" } };

// 健康检查
export interface HealthReport {
  overall: "ok" | "degraded" | "down";
  checked_at: string;
  services: ServiceHealth[];
}

export interface ServiceHealth {
  name: string;
  status: "ok" | "degraded" | "down";
  required: boolean;
  detail: string;
  latency_ms: number;
}
