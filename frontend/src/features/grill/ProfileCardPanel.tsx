import { useState } from "react";
import type { GrillProfileCard as ProfileCard, GrillProfileField as ProfileField } from "@/lib/types";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { StatusChip } from "@/components/ui/Chip";
import SubmitDialog from "./SubmitDialog";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

type FieldState = "empty" | "rag" | "inferred" | "confirmed";

const STATE_META: Record<FieldState, { label: string; tone: "neutral" | "info" | "warning" | "success" }> = {
  empty: { label: "待澄清", tone: "neutral" },
  rag: { label: "RAG 参考", tone: "info" },
  inferred: { label: "待确认", tone: "warning" },
  confirmed: { label: "已确认", tone: "success" },
};

// 简历式分区：短字段两列网格，长文本字段独占一行
const SECTIONS: { title: string; keys: string[]; long: string[] }[] = [
  { title: "基本信息", keys: ["job_category", "base_city", "graduation_window"], long: [] },
  { title: "硬性门槛", keys: ["degree_min", "hard_skills", "must_have_experience"], long: ["hard_skills", "must_have_experience"] },
  { title: "弹性偏好", keys: ["bonus_items", "soft_traits", "target_schools", "team_fit"], long: ["bonus_items", "soft_traits", "target_schools", "team_fit"] },
];

function hasValue(v: ProfileField["value"]): boolean {
  return v != null && v !== "" && !(Array.isArray(v) && v.length === 0);
}

/** 字段四态推导：空→待澄清；confirmed/≥0.8→已确认；≤0.35→RAG 预填；其余→推断待确认（0.8 与后端收敛阈值一致） */
function fieldState(f: ProfileField): FieldState {
  if (!hasValue(f.value)) return "empty";
  const conf = f.confidence || 0;
  if (f.status === "confirmed" || conf >= 0.8) return "confirmed";
  if (conf <= 0.35) return "rag";
  return "inferred";
}

function valueText(v: ProfileField["value"]): string | null {
  return hasValue(v) ? (Array.isArray(v) ? v.join("、") : String(v)) : null;
}

/** 简历条目：label 小字 + 值正文 + 状态小 chip + 可折叠证据（置信度仅作后端收敛信号，不展示） */
function FieldItem({
  field,
  long,
  conflicted,
}: {
  field: ProfileField;
  long: boolean;
  conflicted: boolean;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const { t } = useI18n();
  const state = fieldState(field);
  const meta = STATE_META[state];
  const value = valueText(field.value);

  return (
    <div
      className={cn(
        "min-w-0",
        long && "col-span-2",
        conflicted && "rounded-sm bg-error-container/40 px-1 ring-1 ring-error/40"
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-label text-on-surface-variant">{t(field.label)}</span>
        <StatusChip tone={meta.tone} variant={state === "confirmed" ? "filled" : "dot"} className="h-5 px-2">
          {t(meta.label)}
        </StatusChip>
        {conflicted && (
          <StatusChip tone="error" variant="filled" className="h-5 px-2">
            {t("冲突")}
          </StatusChip>
        )}
      </div>
      <div className={cn("mt-0.5 text-body", value ? "text-on-surface" : "text-on-surface-variant/50")}>
        {value || t("待澄清")}
      </div>
      {field.evidence && (
        <div className="mt-0.5">
          <button
            type="button"
            onClick={() => setShowEvidence((v) => !v)}
            className="inline-flex items-center gap-0.5 text-label text-on-surface-variant hover:text-on-surface"
          >
            <Icon name={showEvidence ? "expand_less" : "expand_more"} size={14} />
            {t("证据")}
          </button>
          {showEvidence && (
            <div className="mt-0.5 rounded-sm bg-surface-high/60 px-2 py-1 text-label text-on-surface-variant whitespace-pre-wrap">
              {t("“{text}”", { text: field.evidence })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface Props {
  profile: ProfileCard | null;
  hasDeliverables: boolean;
  busy: boolean;
  onConfirm: () => void;
  onOpenDeliverables: () => void;
}

// 空白态（未开始对话）兜底画像卡：展示完整字段框架，全「待澄清」
const EMPTY_FIELD = (label: string): ProfileField => ({ label, value: null, confidence: 0, evidence: "", status: "empty" });
const EMPTY_PROFILE: ProfileCard = {
  required_fields: {
    position_name: EMPTY_FIELD("岗位名称"),
    job_category: EMPTY_FIELD("岗位类别"),
    degree_min: EMPTY_FIELD("学历门槛"),
    graduation_window: EMPTY_FIELD("届别/毕业时间"),
    base_city: EMPTY_FIELD("Base 地"),
    hard_skills: EMPTY_FIELD("核心技术要求"),
    must_have_experience: EMPTY_FIELD("必备经历"),
  },
  optional_fields: {
    bonus_items: EMPTY_FIELD("加分项"),
    soft_traits: EMPTY_FIELD("软素质偏好"),
    target_schools: EMPTY_FIELD("目标院校倾向"),
    team_fit: EMPTY_FIELD("团队匹配/培养预期"),
  },
  conflicts: [],
  converged: false,
};

/** 画像卡：简历纸形态——卡头岗位名大标题 + 分区小框 + 条目式字段 */
export default function ProfileCardPanel({ profile: rawProfile, hasDeliverables, busy, onConfirm, onOpenDeliverables }: Props) {
  const { t } = useI18n();
  const [showSubmit, setShowSubmit] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const profile = rawProfile ?? EMPTY_PROFILE;
  const openConflicts = profile.conflicts.filter((c) => c.status === "open");
  const conflictedFields = new Set(openConflicts.flatMap((c) => c.fields));
  const allFields: Record<string, ProfileField> = {
    ...profile.required_fields,
    ...profile.optional_fields,
  };
  const labelOf = (key: string) => allFields[key]?.label || key;
  const labelText = (key: string) => t(labelOf(key));

  const required = Object.values(profile.required_fields);
  const confirmedCount = required.filter((f) => fieldState(f) === "confirmed").length;
  const position = valueText(profile.required_fields.position_name?.value ?? null);

  return (
    <Card variant="outlined" className="flex h-full flex-col p-4">
      {/* 简历头部：岗位名大标题 + 整体状态 + 硬性门槛进度 */}
      <div className="flex items-start justify-between gap-2">
        <h2
          className={cn(
            "text-title-lg",
            position ? "text-on-surface" : "text-on-surface-variant/60"
          )}
        >
          {position || t("岗位待定")}
        </h2>
        {hasDeliverables ? (
          <StatusChip tone="success" variant="filled" icon="check_circle" className="shrink-0">
            {t("已确认")}
          </StatusChip>
        ) : profile.converged ? (
          <StatusChip tone="primary" variant="filled" className="shrink-0">
            {t("可收敛 · 待确认")}
          </StatusChip>
        ) : (
          <StatusChip tone="primary" className="shrink-0">
            {t("澄清中")}
          </StatusChip>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between text-label text-on-surface-variant">
        <span>{t("招聘画像 · 简历卡")}</span>
        <span>
          {t("硬性门槛已确认 {confirmed}/{total}", { confirmed: confirmedCount, total: required.length })}
        </span>
      </div>
      <Progress
        value={required.length ? (confirmedCount / required.length) * 100 : 0}
        className="mt-1 mb-3"
      />

      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {openConflicts.map((c, i) => (
          <div
            key={i}
            className="mb-2 flex items-start gap-2 rounded-md bg-error-container px-3 py-2 text-body-sm text-on-error-container"
          >
            <Icon name="warning" size={16} className="mt-0.5 shrink-0 text-error" />
            <span>
              <span className="font-medium">{c.fields.map(labelText).join(" / ")}</span>
              {t("：{desc}", { desc: c.description })}
            </span>
          </div>
        ))}

        <div className="space-y-2.5">
          {SECTIONS.map((sec) => {
            const entries = sec.keys
              .map((k) => [k, allFields[k]] as const)
              .filter((kv): kv is readonly [string, ProfileField] => !!kv[1]);
            if (!entries.length) return null;
            const done = entries.filter(([, f]) => fieldState(f) === "confirmed").length;
            return (
              <section key={sec.title} className="rounded-md bg-surface-low p-2.5">
                <div className="mb-1.5 flex items-center justify-between">
                  <h3 className="text-label font-semibold text-on-surface">{t(sec.title)}</h3>
                  <span className="text-label text-on-surface-variant">
                    {t("已确认 {done}/{total}", { done, total: entries.length })}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                  {entries.map(([name, f]) => (
                    <FieldItem
                      key={name}
                      field={f}
                      long={sec.long.includes(name)}
                      conflicted={conflictedFields.has(name)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {profile.converged && !hasDeliverables && (
        <Button variant="filled" icon="check" className="mt-3 w-full shrink-0" disabled={busy} onClick={onConfirm}>
          {t("确认画像，生成需求包")}
        </Button>
      )}
      {hasDeliverables && (
        <Button variant="filled" icon="description" className="mt-3 w-full shrink-0" onClick={onOpenDeliverables}>
          {t("打开需求包")}
        </Button>
      )}
      <Button
        variant={submitted ? "tonal" : "outlined"}
        icon={submitted ? "check_circle" : "send"}
        className="mt-2 w-full shrink-0"
        onClick={() => !submitted && setShowSubmit(true)}
      >
        {submitted ? t("已提交给 HR 团队") : t("提交给 HR 团队")}
      </Button>

      {showSubmit && (
        <SubmitDialog
          confirmed={confirmedCount}
          total={required.length}
          onConfirm={() => setSubmitted(true)}
          onClose={() => setShowSubmit(false)}
        />
      )}
    </Card>
  );
}
