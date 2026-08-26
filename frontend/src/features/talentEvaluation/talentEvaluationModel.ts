import type {
  AssessmentCard,
  CandidateBrief,
  InterviewAssessment,
  InterviewAssessmentRun,
} from "@/lib/types";

/**
 * 人才评估统一外壳的左侧"候选人文件夹"组装逻辑（纯函数，node:test 覆盖）。
 *
 * 规则（docs/rebuild.md §2.1）：
 * - 候选人列表与人才库同源（导入即入库），每个候选人是一个文件夹；
 *   标题始终使用姓名，姓名为空时由展示层退回"未命名"，绝不回退到内部 ID；
 * - 文件夹下挂该候选人的评估对象：每个候选人–JD 配对的当前准入评估；
 * - 进入 / 不进入面试的结果都保留入口；失效报告显示"需重评"，不隐藏；
 * - 正在运行的配对显示"评估中"（锁），运行状态优先于历史报告状态。
 */

export type FolderChildStatus =
  | "running"
  | "interview"
  | "no_interview"
  | "stale"
  | "unevaluated";

export interface FolderChild {
  /** "jd:<jd_id>" */
  key: string;
  jdId: string;
  jdTitle: string;
  status: FolderChildStatus;
  updatedAt: string | null;
}

export interface CandidateFolder {
  candidateId: string;
  name: string;
  role: string;
  stage: string;
  /** 是否已有任何岗位评估（报告或运行中），用于列表区分已评估/未评估 */
  evaluated: boolean;
  /** JD 子项按标题排序 */
  children: FolderChild[];
  /** 正在评估中的配对数 */
  activeCount: number;
}

/** 单个配对在文件夹中的展示状态：运行态优先，其次失效，最后当前结论 */
export function pairChildStatus(
  assessment: InterviewAssessment | undefined,
  hasActiveRun: boolean,
): FolderChildStatus {
  if (hasActiveRun) return "running";
  if (!assessment) return "unevaluated";
  if (!assessment.is_valid) return "stale";
  return assessment.decision === "interview" ? "interview" : "no_interview";
}

export function buildCandidateFolders(
  candidates: CandidateBrief[],
  assessments: InterviewAssessment[],
  activeRuns: InterviewAssessmentRun[],
): CandidateFolder[] {
  const activePairKeys = new Set(
    activeRuns.map((run) => `${run.candidate_id}::${run.jd_id}`),
  );

  return candidates.map((brief) => {
    const folder: CandidateFolder = {
      candidateId: brief.id,
      name: brief.name || "",
      role: brief.role || "",
      stage: brief.stage || "",
      evaluated: false,
      children: [],
      activeCount: 0,
    };
    const ownAssessments = assessments.filter(
      (item) => item.candidate_id === folder.candidateId,
    );
    const children: FolderChild[] = [];

    for (const assessment of ownAssessments) {
      const hasActiveRun = activePairKeys.has(
        `${assessment.candidate_id}::${assessment.jd_id}`,
      );
      if (hasActiveRun) folder.activeCount += 1;
      children.push({
        key: `jd:${assessment.jd_id}`,
        jdId: assessment.jd_id,
        jdTitle: assessment.jd_title || "",
        status: pairChildStatus(assessment, hasActiveRun),
        updatedAt: assessment.updated_at || null,
      });
    }

    // 有活动运行但没有当前报告的配对（例如首次评估仍在跑）
    for (const run of activeRuns) {
      if (run.candidate_id !== folder.candidateId) continue;
      if (ownAssessments.some((item) => item.jd_id === run.jd_id)) continue;
      folder.activeCount += 1;
      children.push({
        key: `jd:${run.jd_id}`,
        jdId: run.jd_id,
        jdTitle: run.jd_title || "",
        status: "running",
        updatedAt: null,
      });
    }

    children.sort((a, b) => a.jdTitle.localeCompare(b.jdTitle, "zh-Hans-CN"));
    folder.children = children;
    folder.evaluated = children.length > 0;
    return folder;
  });
}

/** 文件夹搜索：匹配姓名 / 方向 / 阶段 / JD 子项标题（小写包含） */
export function filterFolders(
  folders: CandidateFolder[],
  query: string,
): CandidateFolder[] {
  const keyword = query.trim().toLowerCase();
  if (!keyword) return folders;
  return folders.filter((folder) => {
    const haystack = [folder.name, folder.role, folder.stage]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (haystack.includes(keyword)) return true;
    return folder.children.some((child) =>
      child.jdTitle.toLowerCase().includes(keyword),
    );
  });
}

// ---- 加权总分与准入判定（确定性换算，与后端 evaluator 规则一致） ----

export const IMPORTANCE_COEFFICIENTS: Record<string, number> = {
  primary: 3,
  major: 2,
  supporting: 1,
};

export interface ScoreRow {
  taskId: string;
  title: string;
  importance: string;
  level: number;
  coefficient: number;
  /** 单项百分制 = 等级 / 4 × 100 */
  perItem: number;
  /** 该任务对分子的贡献 = 单项百分制 × 系数 */
  weighted: number;
}

export interface ScoreBreakdown {
  rows: ScoreRow[];
  /** Σ(单项 × 系数) / Σ系数 */
  total: number;
  /** 所有首要任务等级不低于 2 */
  primaryThresholdMet: boolean;
  /** 加权总分不低于 50 */
  scoreThresholdMet: boolean;
}

/**
 * 按岗位卡任务权重换算加权总分与准入条件。
 * 没有岗位卡（如 JD 已被删除）时退化为等权计算，仅用于展示。
 */
export function computeScoreBreakdown(
  taskAssessments: Array<{ task_id?: string; level?: number }>,
  card: AssessmentCard | null | undefined,
): ScoreBreakdown {
  const cardTask = (taskId: string) =>
    card?.core_tasks.find((task) => task.id === taskId);
  const rows: ScoreRow[] = taskAssessments.map((task) => {
    const id = task.task_id || "";
    const meta = cardTask(id);
    const importance = meta?.importance || "major";
    const coefficient = IMPORTANCE_COEFFICIENTS[importance] ?? 2;
    const level = Math.max(0, Math.min(4, Number(task.level ?? 0)));
    const perItem = (level / 4) * 100;
    return {
      taskId: id,
      title: meta?.title || id,
      importance,
      level,
      coefficient,
      perItem,
      weighted: perItem * coefficient,
    };
  });
  const coefficientSum = rows.reduce((sum, row) => sum + row.coefficient, 0);
  const total = coefficientSum
    ? rows.reduce((sum, row) => sum + row.weighted, 0) / coefficientSum
    : 0;
  const primaryRows = rows.filter((row) => row.importance === "primary");
  return {
    rows,
    total,
    primaryThresholdMet: primaryRows.every((row) => row.level >= 2),
    scoreThresholdMet: total >= 50,
  };
}
