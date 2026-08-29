import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCandidateFolders,
  buildBatchRiskPlan,
  computeScoreBreakdown,
  filterFolders,
  pairChildStatus,
  resolveEvaluationUiState,
} from "../src/features/talentEvaluation/talentEvaluationModel.ts";

const brief = (id, name, extra = {}) => ({
  id,
  name,
  role: "",
  stage: "",
  group: "pending",
  level: "",
  category: "",
  engagement_status: "newly_admitted",
  admitted_at: null,
  ...extra,
});

const assessment = (candidateId, jdId, extra = {}) => ({
  id: `${candidateId}:${jdId}`,
  candidate_id: candidateId,
  candidate_name: "",
  jd_id: jdId,
  jd_title: "",
  status: "completed",
  is_valid: true,
  invalid_reason: "",
  decision: "interview",
  total_score: 80,
  task_assessments: [],
  review_corrections: [],
  interview_focus: [],
  model_usage: [],
  run_trace: [],
  updated_at: "2026-08-26T00:00:00",
  ...extra,
});

const run = (candidateId, jdId, extra = {}) => ({
  id: `${candidateId}:${jdId}:run`,
  batch_id: "b",
  candidate_id: candidateId,
  candidate_name: "",
  jd_id: jdId,
  jd_title: "",
  status: "running",
  current_node: "",
  run_trace: [],
  model_usage: [],
  error_message: "",
  cancellation_requested: false,
  ...extra,
});

test("folder children are JD items sorted by title (no extra entries)", () => {
  const folders = buildCandidateFolders(
    [brief("c1", "张三")],
    [
      assessment("c1", "jd-b", { jd_title: "Data Pipeline" }),
      assessment("c1", "jd-a", { jd_title: "Agent Evaluation" }),
    ],
    [],
  );
  assert.equal(folders.length, 1);
  const jdTitles = folders[0].children.map((child) => child.jdTitle);
  assert.deepEqual(jdTitles, ["Agent Evaluation", "Data Pipeline"]);
});

test("candidate folders never fall back to internal ids for names", () => {
  const folders = buildCandidateFolders(
    [brief("candidate_xxx", "")],
    [],
    [],
  );
  // 姓名为空 → 空字符串，由展示层显示"未命名"，绝不回退到 candidate_xxx
  assert.equal(folders[0].name, "");
});

test("folders come from the candidate directory only; stray assessments are ignored", () => {
  // 目录接口保证"有报告的人必在列表中"，模型不再从报告侧兜底建文件夹
  const folders = buildCandidateFolders(
    [brief("c1", "张三")],
    [
      assessment("c1", "jd-1", { jd_title: "A" }),
      assessment("ghost", "", { candidate_name: "李四", jd_title: "B" }),
    ],
    [],
  );
  assert.equal(folders.length, 1);
  assert.equal(folders[0].candidateId, "c1");
  assert.equal(folders[0].children.length, 1);
});

test("folders with any report or active run count as evaluated", () => {
  const folders = buildCandidateFolders(
    [brief("c1", "张三"), brief("c2", "李四")],
    [assessment("c1", "jd-1", { jd_title: "A" })],
    [run("c2", "jd-2", { jd_title: "B" })],
  );
  assert.equal(folders[0].evaluated, true);
  assert.equal(folders[1].evaluated, true);

  const untouched = buildCandidateFolders([brief("c3", "王五")], [], []);
  assert.equal(untouched[0].evaluated, false);
  assert.deepEqual(untouched[0].children, []);
});

test("both admission outcomes stay visible; invalid reports show stale status", () => {
  const folders = buildCandidateFolders(
    [brief("c1", "张三")],
    [
      assessment("c1", "jd-1", { decision: "interview", jd_title: "A" }),
      assessment("c1", "jd-2", { decision: "no_interview", jd_title: "B" }),
      assessment("c1", "jd-3", { is_valid: false, jd_title: "C" }),
    ],
    [],
  );
  const statuses = folders[0].children.map((child) => child.status);
  assert.deepEqual(statuses, ["interview", "no_interview", "stale"]);
});

test("an active run overrides the saved report and counts toward the lock badge", () => {
  const folders = buildCandidateFolders(
    [brief("c1", "张三")],
    [
      assessment("c1", "jd-1", { jd_title: "A" }),
      assessment("c1", "jd-2", { jd_title: "B" }),
    ],
    [run("c1", "jd-1"), run("c1", "jd-9", { jd_title: "新评估的岗位" })],
  );
  const byJd = new Map(folders[0].children.map((child) => [child.jdId, child]));
  assert.equal(byJd.get("jd-1").status, "running");
  assert.equal(byJd.get("jd-2").status, "interview");
  assert.equal(byJd.get("jd-9").status, "running");
  assert.equal(folders[0].activeCount, 2);
});

test("pairChildStatus precedence: running > stale > decision", () => {
  assert.equal(pairChildStatus(undefined, true), "running");
  assert.equal(pairChildStatus(assessment("c", "j", { is_valid: false }), true), "running");
  assert.equal(pairChildStatus(assessment("c", "j", { is_valid: false }), false), "stale");
  assert.equal(pairChildStatus(assessment("c", "j"), false), "interview");
  assert.equal(pairChildStatus(undefined, false), "unevaluated");
});

test("filterFolders matches candidate fields and JD sub-item titles", () => {
  const folders = buildCandidateFolders(
    [brief("c1", "张三", { role: "多模态" }), brief("c2", "李四")],
    [assessment("c2", "jd-1", { jd_title: "预测训练数据算法工程师" })],
    [],
  );
  assert.deepEqual(filterFolders(folders, "张三").map((f) => f.candidateId), ["c1"]);
  assert.deepEqual(filterFolders(folders, "多模态").map((f) => f.candidateId), ["c1"]);
  assert.deepEqual(filterFolders(folders, "训练数据").map((f) => f.candidateId), ["c2"]);
  assert.equal(filterFolders(folders, "  ").length, 2);
});

const card = (importances) => ({
  role_summary: "x",
  background_evidence_guidance: "",
  excluded_requirements: [],
  core_tasks: Object.entries(importances).map(([id, importance]) => ({
    id,
    title: id,
    description: "",
    importance,
    evaluation_focus: "",
    anchors: { level_2: "", level_3: "", level_4: "" },
  })),
});

test("weighted total mirrors the deterministic formula Σ(level/4×100×coef) ÷ Σcoef", () => {
  const breakdown = computeScoreBreakdown(
    [
      { task_id: "t1", level: 4 },
      { task_id: "t2", level: 2 },
      { task_id: "t3", level: 0 },
    ],
    card({ t1: "primary", t2: "major", t3: "supporting" }),
  );
  // (100×3 + 50×2 + 0×1) / 6 = 66.67
  assert.equal(breakdown.total.toFixed(2), "66.67");
  assert.equal(breakdown.primaryThresholdMet, true);
  assert.equal(breakdown.scoreThresholdMet, true);
});

test("a primary task below level 2 and a score below 60 both fail admission", () => {
  const breakdown = computeScoreBreakdown(
    [
      { task_id: "t1", level: 1 },
      { task_id: "t2", level: 4 },
    ],
    card({ t1: "primary", t2: "major" }),
  );
  // (25×3 + 100×2) / 5 = 55 → 总分和首要任务门槛均未达到
  assert.equal(breakdown.total, 55);
  assert.equal(breakdown.primaryThresholdMet, false);
  assert.equal(breakdown.scoreThresholdMet, false);
});

test("missing card falls back to equal weights for display only", () => {
  const breakdown = computeScoreBreakdown(
    [{ task_id: "t1", level: 2 }, { task_id: "t2", level: 4 }],
    null,
  );
  assert.equal(breakdown.total, 75);
});

test("batch plan starts at 0×0 and expands N×M deterministically", () => {
  const jobs = [{ id: "j1", title: "岗位一", assessment_card: card({ t1: "primary" }) }];
  assert.equal(buildBatchRiskPlan([], [], [], jobs, [], []).selectedCount, 0);
  const plan = buildBatchRiskPlan(
    ["c1", "c2", "c2"],
    ["j1"],
    [brief("c1", "甲"), brief("c2", "乙")],
    jobs,
    [],
    [],
  );
  assert.equal(plan.selectedCount, 2);
  assert.equal(plan.runnablePairs.length, 2);
  assert.equal(plan.estimatedModelCalls, 6);
});

test("existing reports are excluded by default and require explicit inclusion", () => {
  const jobs = [{ id: "j1", title: "岗位一", assessment_card: card({ t1: "primary" }) }];
  const existing = [assessment("c1", "j1")];
  const safe = buildBatchRiskPlan(["c1"], ["j1"], [brief("c1", "甲")], jobs, existing, []);
  assert.equal(safe.existingCount, 1);
  assert.equal(safe.runnablePairs.length, 0);
  const forced = buildBatchRiskPlan(["c1"], ["j1"], [brief("c1", "甲")], jobs, existing, [], true);
  assert.equal(forced.runnablePairs.length, 1);
});

test("active pairs are never runnable and oversized batches are rejected", () => {
  const candidates = Array.from({ length: 21 }, (_, index) => brief(`c${index}`, `候选人${index}`));
  const jobs = [{ id: "j1", title: "岗位一", assessment_card: card({ t1: "primary" }) }];
  const plan = buildBatchRiskPlan(
    candidates.map((item) => item.id),
    ["j1"],
    candidates,
    jobs,
    [],
    [run("c0", "j1")],
  );
  assert.equal(plan.activeCount, 1);
  assert.equal(plan.runnablePairs.length, 20);
  assert.equal(plan.exceedsLimit, false);
  const oversized = buildBatchRiskPlan(
    [...candidates.map((item) => item.id), "c21"],
    ["j1"],
    [...candidates, brief("c21", "候选人21")],
    jobs,
    [],
    [],
  );
  assert.equal(oversized.exceedsLimit, true);
});

test("evaluation UI state has one explicit precedence order", () => {
  assert.equal(resolveEvaluationUiState({ selecting: true, batchStatus: "running", selectedCandidateId: "c", selectedJdId: "j" }), "selecting");
  assert.equal(resolveEvaluationUiState({ selecting: false, batchStatus: "running", selectedCandidateId: "c", selectedJdId: "j" }), "viewingReport");
  assert.equal(resolveEvaluationUiState({ selecting: false, batchStatus: "running", selectedCandidateId: null, selectedJdId: null }), "running");
  assert.equal(resolveEvaluationUiState({ selecting: false, batchStatus: "completed", selectedCandidateId: null, selectedJdId: null }), "browsing");
  assert.equal(resolveEvaluationUiState({ selecting: false, batchStatus: null, selectedCandidateId: "c", selectedJdId: null }), "browsing");
});

test("JD cards missing core_tasks no longer crash batch planning or score breakdown", () => {
  const brokenCard = { id: "j1", title: "岗位一", assessment_card: {} };
  const plan = buildBatchRiskPlan(
    ["c1"],
    ["j1"],
    [brief("c1", "甲")],
    [brokenCard],
    [],
    [],
  );
  assert.equal(plan.selectedCount, 1);
  assert.equal(plan.estimatedModelCalls, 2);
  const breakdown = computeScoreBreakdown([{ task_id: "t1", level: 3 }], {});
  assert.equal(breakdown.total, 75);
});
