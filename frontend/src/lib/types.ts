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
}

export interface CandidateDetail extends CandidateBrief {
  confidence: number;
  raw_text: string;
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
  evaluation?: Evaluation;
  latest_evaluation?: Evaluation;
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
  weight: number;
  rationale?: string;
  reason?: string;
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
  track_evaluations: unknown[];
  routing_confidence: number;
  evaluation_mode: string;
  status: string;
  research_group_matching_status: string;
  academic_report?: {
    alignments: Alignment[];
    warnings: string[];
  };
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

export interface PersonBrief {
  id: string;
  name: string;
  org: string;
  direction: string;
  person_type: string;
  overall_score: number | null;
  level: string | null;
  reputation_level: string | null;
  reputation_status: string | null;
  updated_at: string | null;
  engagement_status?: string;
}

export interface PersonDetail {
  id: string;
  name: string;
  org: string;
  direction: string;
  person_type: string;
  created_at: string;
  updated_at: string;
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

// 知识 Agent SSE 事件
export interface AgentEvent {
  type:
    | "node" | "intent" | "clarification" | "local_facts"
    | "tool_plan" | "external_fact" | "tool_failure"
    | "answer" | "warning" | "done";
  payload: Record<string, unknown>;
}

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
