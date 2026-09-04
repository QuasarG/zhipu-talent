// API 响应类型定义

export interface CandidateBrief {
  id: string;
  name: string;
  name_note: string;
  display_name: string;
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
  search_text?: string;
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
  // 姓名备注：person 主档人工补充，展示优先于 name；等于 name 时为空
  name_note: string;
  display_name: string;
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
  workflow_version?: string;
  phases: EvaluationGraphPhase[];
}

export type InterviewDecision = "interview" | "hold" | "reject";

export interface JobRequirementAssessment {
  requirement: string;
  status: "met" | "unmet" | "unknown";
  evidence: string[];
  rationale: string;
}

export interface JobFitDimension {
  key: string;
  label: string;
  score: number;
  weight: number;
  rationale: string;
  evidence: string[];
}

export interface JobFitFinding {
  summary: string;
  evidence: string[];
}

export interface JobFitAssessment {
  jd_id: string;
  jd_title: string;
  decision: InterviewDecision;
  confidence: number;
  fit_score: number;
  hard_requirements: JobRequirementAssessment[];
  dimensions: JobFitDimension[];
  strengths: JobFitFinding[];
  risks: JobFitFinding[];
  missing_information: string[];
  interview_questions: string[];
  decision_reason: string;
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
  publication_score?: number;
  safety_net_score?: number;
  track_assignments: TrackAssignment[];
  track_evaluations: TrackEvaluation[];
  routing_confidence: number;
  evaluation_mode: string;
  status: string;
  error_message?: string;
  created_at?: string | null;
  completed_at?: string | null;
  academic_report?: AcademicReport;
  evaluation_graph: EvaluationGraph;
  node_runs: EvaluationNodeRun[];
  interview_decision?: InterviewDecision | "";
  best_fit_jd_id?: string;
  best_fit_jd_title?: string;
  decision_summary?: string;
  job_fit_assessments?: JobFitAssessment[];
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
  name_note: string;
  display_name: string;
  org: string;
  direction: string;
  person_type: string;
  group_id: string | null;
  // 新准入评估快照（一岗一评）；无旧 evaluations 时以此判定"已评估"
  jd_evaluated?: boolean;
  latest_jd_decision?: string | null;
  latest_jd_score?: number | null;
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
  assessment_view?: PersonAssessmentView;
}

export interface PersonAdmissionAssessment {
  id: string;
  candidate_id: string;
  jd_id: string;
  jd_title: string;
  status: string;
  is_valid: boolean;
  invalid_reason: string;
  decision: "interview" | "no_interview";
  total_score: number;
  task_assessments: Array<Record<string, unknown>>;
  review_corrections: Array<Record<string, unknown>>;
  interview_focus: Array<Record<string, string>>;
  model_usage: ModelUsage[];
  run_trace: WorkflowNodeEvent[];
  created_at: string | null;
  updated_at: string | null;
}

export interface PersonAssessmentView {
  schema_version: "person-assessment-view.v1";
  person_id: string;
  candidate_id: string | null;
  resume: {
    has_resume: boolean;
    submission_id: string | null;
    candidate_id: string | null;
    filename: string;
    source_format: string;
    parse_status: string | null;
    structured: Record<string, unknown>;
    structured_sections: string[];
    updated_at: string | null;
  };
  general_evaluation: {
    id: number;
    candidate_id: string;
    status: string;
    overall_score: number;
    level: string;
    tier: string;
    one_liner: string;
    stage_profile: string;
    core_strengths: string[];
    potential_risks: string[];
    recommended_tracks: TrackRecommendation[];
    academic_report: AcademicReport;
    created_at: string | null;
    completed_at: string | null;
  } | null;
  admissions: PersonAdmissionAssessment[];
  latest: {
    source_type: "interview_admission" | "general_evaluation";
    source_id: string;
    candidate_id: string;
    jd_id?: string;
    jd_title?: string;
    decision: "interview" | "no_interview" | null;
    score: number;
    generated_at: string | null;
  } | null;
}

export interface TalentGroup {
  id: string;
  name: string;
  sort_order: number;
  count: number;
}

export interface ResumeVersionEntry {
  submission_id: string;
  filename: string;
  source_format: string;
  created_at: string;
  structured: Record<string, unknown>;
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
  // 人才库引用的完整人物信息（tool_search_persons 注册时写入）
  meta?: {
    person_id: string;
    name?: string;
    org?: string;
    direction?: string;
    schools?: unknown[];
    person_type?: string;
    group?: string | null;
    overall_score?: number;
    level?: string;
    tier?: string;
  };
}

export type ChatActionKind = "select_person" | "propose_add_person" | "resolve_fact_conflict" | "clarify" | "review_reputation";

export type ChatSegment =
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "observer"; action?: string; text: string }
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
  | { type: "thinking_delta"; payload: { text: string } }
  | { type: "tool_start"; payload: { call_id: string; tool: string; label: string; args_summary: string } }
  | { type: "tool_end"; payload: { call_id: string; tool: string; status: "ok" | "error"; summary: string; detail: string } }
  | { type: "observer"; payload: { action: string; text: string } }
  | { type: "action_required"; payload: { action_id: string; kind: ChatActionKind; payload: Record<string, unknown> } }
  | { type: "sources"; payload: { items: ChatCitation[] } }
  | { type: "message_done"; payload: { message_id: string } }
  | { type: "error"; payload: { message: string } }
  | { type: "done"; payload: { status: "completed" | "awaiting_action" } };

// ---- grill 画像澄清 ----

export interface GrillTextSegment {
  type: "text";
  text: string;
}

export interface GrillThinkingSegment {
  type: "thinking";
  text: string;
}

export interface GrillToolSegment {
  type: "tool";
  call_id: string;
  tool: string;
  label: string;
  args_summary?: string;
  status?: "ok" | "error";
  summary?: string;
  detail?: string;
}

export type GrillChatSegment = GrillThinkingSegment | GrillTextSegment | GrillToolSegment;

export interface GrillChatMessage {
  id: string;
  role: "user" | "assistant";
  segments: GrillChatSegment[];
  error?: string;
}

export interface GrillProfileField {
  label: string;
  value: string | string[] | null;
  confidence: number;
  evidence: string;
  status: "empty" | "probing" | "confirmed";
}

export interface GrillConflict {
  fields: string[];
  description: string;
  status: "open" | "resolved";
  resolution: string | null;
}

export interface GrillProfileCard {
  required_fields: Record<string, GrillProfileField>;
  optional_fields: Record<string, GrillProfileField>;
  conflicts: GrillConflict[];
  converged: boolean;
}

export interface GrillOutlineNode {
  id: string;
  parent_id: string | null;
  order: number;
  topic: string;
  question_hint: string;
  linked_fields: string[];
  status: "pending" | "active" | "covered" | "obsolete";
  source: "initial" | "dynamic";
  answer_summary: string | null;
}

export interface GrillDeliverables {
  persona_profile?: string;
  jd_draft: string;
  screening_criteria: { hard_requirements?: string[]; bonus_items?: string[] };
  reference_jobs?: { job_id: string; title: string; score: number }[];
}

export interface GrillStoredMessage {
  role: "user" | "assistant";
  text: string;
  tools: { tool: string; label: string; status: string; summary: string; detail?: string }[];
  segments?: GrillChatSegment[];
  status?: "running" | "completed" | "error";
  error?: string;
}

export interface GrillSessionState {
  session_id: string;
  profile: GrillProfileCard;
  outline: GrillOutlineNode[];
  messages: GrillStoredMessage[];
  deliverables: GrillDeliverables | null;
  converged: boolean;
  running: boolean;
}

export interface GrillSessionSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: string;
}

// ---- 奖学金初筛 ----

export interface ScholarshipReputationItem {
  id: number;
  subject: string;
  subject_role: string;
  sentiment: string;
  title: string;
  url: string;
  snippet: string;
  concern: string;
  review_status: string;
  adjustment: number;
  reviewer: string;
}

/** 评分 agent 轨迹 segment：thinking=本轮目的说明，tool=工具调用卡，text=系统提示，final=终态 */
export type ScorerTraceSegment =
  | { type: "thinking"; text: string }
  | { type: "tool"; call_id: string; tool: string; label: string; status: string; summary: string; detail: string }
  | { type: "text"; text: string }
  | { type: "final"; text: string; blind_score: number; recommend_tier: string; reputation_findings: ReputationFinding[] };

export interface ReputationFinding {
  subject: string;
  sentiment: string;
  title: string;
  url: string;
  note: string;
}

export interface ScholarshipEvaluation {
  id: number;
  config_version: string;
  status: string;
  blind_score: number;
  dimensions: { key: string; label: string; score: number; max_points: number; reason: string; evidence_level?: string }[];
  highlights: string[];
  risks: string[];
  error_message: string;
  created_at: string | null;
  trace?: ScorerTraceSegment[];
  recommend_tier?: string;
  reputation_findings?: ReputationFinding[];
}

export interface ScholarshipMaterial {
  id: number;
  kind: string;
  filename: string;
  advisor_name: string;
  raw_text: string;
  has_file?: boolean;
}

export interface ScholarshipApplication {
  id: string;
  name: string;
  degree_type: string;
  expected_graduation: string;
  direction: string;
  school: string;
  advisors: string[];
  status: string;
  screening_detail: { missing?: string[]; reasons?: string[] };
  // 飞书问卷同步字段（空串/null = 非飞书来源或未推送）
  feishu_record_id: string;
  name_en: string;
  phone: string;
  email: string;
  country: string;
  lab: string;
  advisor_title: string;
  grade: string;
  research_summary: string;
  education_history: string;
  submitted_at: string | null;
  updated_at?: string | null;
  evaluating?: boolean;
  materials_count: number;
  blind_score: number | null;
  total_score: number | null;
  // detail 才有
  materials?: ScholarshipMaterial[];
  evaluations?: ScholarshipEvaluation[];
}

// 健康检查
export interface HealthReport {
  overall: "ok" | "degraded" | "down";
  checked_at: string;
  services: ServiceHealth[];
}

export interface ServiceHealth {
  name: string;
  status: "checking" | "ok" | "degraded" | "down";
  required: boolean;
  detail: string;
  latency_ms: number;
}

export interface ResumeOriginalMetadata {
  exists: boolean;
  mime_type: string;
  size: number;
  filename: string;
  previewable: boolean;
  preview_url: string;
  download_url: string;
  error: string;
}


// ---- JD 池（驱动动态 track 评估）----
export interface JdDimensionSpec {
  key: string;
  label: string;
  max_points: number;
  evidence_rule: string;
}

export interface JdTrackSpec {
  key: string;
  label: string;
  max_points: number;
  evidence_focus: string;
  high_score_rule: string;
  dimensions: JdDimensionSpec[];
  keywords?: string[];
}

export interface JdEntry {
  id: string;
  title: string;
  team: string;
  raw_text: string;
  supplements: string[];
  assessment_card: AssessmentCard | null;
  card_status: "generating" | "ready" | "failed";
  card_error: string;
  card_run_trace: WorkflowNodeEvent[];
  card_model_usage: ModelUsage[];
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssessmentCardTask {
  id: string;
  title: string;
  description: string;
  importance: "primary" | "major" | "supporting";
  evaluation_focus: string;
  anchors: { level_2: string; level_3: string; level_4: string };
}

export interface AssessmentCard {
  role_summary: string;
  core_tasks: AssessmentCardTask[];
  background_evidence_guidance: string;
  excluded_requirements: string[];
}

export interface ModelUsage {
  node_id?: string;
  model: string;
  fallback_reason: string;
  started_at: string;
  completed_at: string;
}

export interface WorkflowNodeEvent {
  run_id?: string;
  node_id: string;
  parent_id?: string;
  label?: string;
  status: string;
  summary: string;
  detail?: Record<string, unknown>;
  error?: string;
  at?: string;
  /** 事件由谁产生；旧记录缺省时由前端按 node_id 兼容推断。 */
  actor?: "evaluator" | "observer" | "system";
  /** 活动流语义，不再把每条事件伪装成 DAG 节点。 */
  event_type?: "stage" | "thinking" | "tool" | "observer" | "validation" | "decision" | "report";
  turn?: number;
  attempt?: number;
  tool?: string;
  call_id?: string;
  args_summary?: string;
}

export interface InterviewAssessmentRun {
  id: string;
  batch_id: string;
  candidate_id: string;
  candidate_name: string;
  jd_id: string;
  jd_title: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  current_node: string;
  run_trace: WorkflowNodeEvent[];
  model_usage: ModelUsage[];
  error_message: string;
  cancellation_requested: boolean;
}

export interface InterviewAssessmentBatch {
  id: string;
  request_id: string;
  config_version: string;
  force_reason: string;
  status: string;
  candidate_ids: string[];
  jd_ids: string[];
  total_pairs: number;
  completed_pairs: number;
  failed_pairs: number;
  cancelled_pairs: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  runs?: InterviewAssessmentRun[];
}

export interface InterviewAssessment {
  id: string;
  candidate_id: string;
  candidate_name: string;
  jd_id: string;
  jd_title: string;
  status: string;
  is_valid: boolean;
  invalid_reason: string;
  decision: "interview" | "no_interview";
  total_score: number;
  task_assessments: Array<Record<string, unknown>>;
  review_corrections: Array<Record<string, unknown>>;
  interview_focus: Array<Record<string, string>>;
  model_usage: ModelUsage[];
  run_trace: WorkflowNodeEvent[];
  updated_at: string;
}

// ---- 人才材料包（一人一 zip，双 agent 解析进档）----
export interface TalentBundleSummary {
  id: string;
  filename: string;
  status: "unpacked" | "noresume" | "importing" | "imported" | "failed";
  person_id: string | null;
  candidate_id: string | null;
  resume_file: string;
  error_message: string;
  file_count: number;
  total_bytes: number;
  created_at: string | null;
  files: { file: string; size_kb: number; url: string }[];
}

export interface TalentBundle extends TalentBundleSummary {
  trace: ChatSegment[];
  profile: Record<string, unknown> | null;
}
