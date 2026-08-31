// 奖学金模块共享常量：状态/材料类型等中文映射与分数格式化

export type ChipTone = "success" | "warning" | "error" | "info" | "neutral" | "primary";

export const STATUS_LABELS: Record<string, string> = {
  imported: "待评估",
  eligible: "待评估",
  material_incomplete: "待评估",
  ineligible: "不符合申报条件",
  scored: "已评分",
  finalized: "已定稿",
};

export const STATUS_TONES: Record<string, ChipTone> = {
  imported: "info",
  eligible: "info",
  material_incomplete: "info",
  ineligible: "error",
  scored: "success",
  finalized: "primary",
};

export const MATERIAL_KIND_LABELS: Record<string, string> = {
  form: "申请表",
  resume: "简历",
  supplementary: "申请补充表",
  achievement: "代表性成果",
  letter: "推荐信",
};

// 材料分组展示顺序
export const KIND_ORDER = ["form", "resume", "supplementary", "achievement", "letter"];

export const DEGREE_LABELS: Record<string, string> = { master: "硕士", phd: "博士" };

export const SUBJECT_ROLE_LABELS: Record<string, string> = { applicant: "申请人", advisor: "导师" };

export const REVIEW_LABELS: Record<string, string> = {
  pending: "待核验",
  confirmed: "已确认",
  dismissed: "已驳回",
};

export function fmtScore(v: number | null): string {
  return v == null ? "—" : v.toFixed(1);
}

export function fmtAdjust(v: number): string {
  return v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}
