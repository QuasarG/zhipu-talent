import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type {
  AcademicReport,
  CandidateDetail,
  ClaimAlignment,
  VerificationCheckStatus,
} from "@/lib/types";
import { api } from "@/lib/api";
import Tabs from "@/components/ui/Tabs";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import { getSchoolLogo } from "@/lib/schoolLogos";
import { useSessionState } from "@/lib/sessionState";
import { useI18n } from "@/lib/i18n";
import TypewriterText from "@/features/resume/TypewriterText";

interface Props {
  detail: CandidateDetail;
  /** 论文人工裁决后的回调：触发上层刷新详情（含核验状态/评估按钮态） */
  onReviewed?: () => void;
  /** 外层已提供简历/原件 tab（如滑轨卡）时置 true，隐藏内层 Tabs */
  hideTabs?: boolean;
  /** 姓名备注编辑器（人才库场景传入；缺省不渲染） */
  nameNoteEditor?: ReactNode;
}

export default function ResumeContent({ detail, onReviewed, hideTabs, nameNoteEditor }: Props) {
  const [mode, setMode] = useSessionState<"structured" | "raw">(`resume-evaluate.resume-mode.${detail.id}`, "structured");
  const { t } = useI18n();
  const directions = (detail.directions || []).filter(Boolean);
  const academicReport = detail.academic_report || null;
  const effectiveMode = hideTabs ? "structured" : mode;
  // 导入预览态：分节字段逐字显式，日常查看直接渲染
  const importing = detail.group === "importing";

  return (
    <div className="flex flex-col h-full min-h-0">
      {hideTabs ? null : (
        <Tabs
          className="mb-4 shrink-0"
          items={[
            { value: "structured", label: t("结构化简历") },
            { value: "raw", label: t("简历原件") },
          ]}
          value={mode}
          onChange={setMode}
        />
      )}

      <div className={hideTabs ? "flex-1 min-h-0" : "flex-1 min-h-0"}>
        {effectiveMode === "raw" ? (
          <OriginalPreview candidateId={detail.id} sourceFormat={detail.source_format} fallbackText={detail.raw_text || ""} />
        ) : (
          <div className="h-full min-h-0 overflow-y-auto pr-1">
            <header className="pb-4 border-b-2 border-outline-variant">
              <h2 className="text-headline font-bold text-on-surface flex items-center gap-2 flex-wrap">
                {importing ? <TypewriterText text={detail.name || t("解析中…")} enabled={!!detail.name} /> : (detail.name || t("未命名候选人"))}
                {nameNoteEditor}
              </h2>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
                <MetaField label={t("候选阶段")} value={importing && detail.stage ? <TypewriterText text={detail.stage} /> : detail.stage} />
                <MetaField label={t("目标岗位")} value={importing && detail.role ? <TypewriterText text={detail.role} /> : detail.role} />
              </div>
              {directions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {directions.map((direction) => (
                    <StatusChip key={direction} tone="info">{direction}</StatusChip>
                  ))}
                </div>
              )}
            </header>

            <SupplementaryBox detail={detail} />

            <div className="grid grid-cols-2 gap-4 py-4">
              <RecordSection title={t("教育经历")} icon="school" importing={importing}>
                <EducationList detail={detail} importing={importing} />
              </RecordSection>
              <RecordSection title={t("实习 / 工作经历")} icon="work" importing={importing}>
                <ExperienceList detail={detail} importing={importing} />
              </RecordSection>
            </div>

            <RecordSection title={t("项目经历")} icon="construction" className="mb-4" importing={importing}>
              <ProjectList detail={detail} importing={importing} />
            </RecordSection>

            <RecordSection
              title={t("论文与成果")}
              icon="menu_book"
              count={(detail.publications || []).length}
              className="mb-4"
              importing={importing}
            >
              <PublicationList detail={detail} academicReport={academicReport} importing={importing} onReviewed={onReviewed} />
            </RecordSection>

            <RecordSection title={t("技能")} icon="bolt" importing={importing}>
              <SkillsList detail={detail} importing={importing} />
            </RecordSection>
          </div>
        )}
      </div>
    </div>
  );
}

/** HR 补充信息框：简历上没有的信息，持久化到后端，评估时并入输入 */
function SupplementaryBox({ detail }: { detail: CandidateDetail }) {
  const [value, setValue] = useState(detail.supplementary_info || "");
  const [state, setState] = useState<"idle" | "dirty" | "saving" | "saved" | "error">("idle");
  const { t } = useI18n();

  const save = async () => {
    if (state === "saving") return;
    setState("saving");
    try {
      await api.candidates.updateSupplementary(detail.id, value.trim());
      setState("saved");
    } catch {
      setState("error");
    }
  };

  return (
    <RecordSection title={t("补充信息")} icon="note_add" className="mt-4">
      <div className="px-4 py-3">
        <p className="text-label text-on-surface-variant mb-2">
          {t("简历上没有的信息（如推荐人评价、背调笔记），将并入评估输入，随候选人持久保存，刷新不丢失")}
        </p>
        <textarea
          value={value}
          onChange={(e) => { setValue(e.target.value); setState("dirty"); }}
          onBlur={() => { if (state === "dirty") void save(); }}
          rows={3}
          placeholder={t("输入要补充给评估的信息……")}
          className="w-full rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2 text-body text-on-surface outline-none focus:outline-2 focus:outline-primary resize-y"
        />
        <div className="flex items-center justify-end gap-2 mt-1.5">
          <span className="text-label text-on-surface-variant">
            {state === "saving" ? t("保存中…")
              : state === "saved" ? t("已保存")
              : state === "error" ? t("保存失败，请重试")
              : state === "dirty" ? t("未保存") : ""}
          </span>
          <Button variant="tonal" className="h-8 px-3 text-xs" disabled={state !== "dirty"} onClick={save}>
            {t("保存")}
          </Button>
        </div>
      </div>
    </RecordSection>
  );
}

/** 简历原件预览：按 source_format 智能分流渲染。
 *  PDF → iframe；图片 → img；MD → 轻量 markdown 渲染；JSON/TXT → 纯文本。
 *  原件不可用时回退到提取的 raw_text。 */
export function OriginalPreview({ candidateId, sourceFormat, fallbackText }: {
  candidateId: string;
  sourceFormat: string;
  fallbackText: string;
}) {
  const fmt = (sourceFormat || "").toLowerCase();
  const fileUrl = `/api/candidates/${candidateId}/pdf`;
  const [exists, setExists] = useState<boolean | null>(null);

  useEffect(() => { setExists(null); }, [candidateId]);

  const { t } = useI18n();

  // PDF：探测原件是否存在，有则 iframe
  if (fmt === "pdf" || fmt === "" ) {
    if (exists === null) {
      fetch(fileUrl, { method: "HEAD" })
        .then((r) => setExists(r.ok))
        .catch(() => setExists(false));
      return <div className="flex items-center justify-center h-full"><LoadingIndicator size={28} label={t("正在加载原件...")} /></div>;
    }
    if (exists) {
      return (
        <iframe key={candidateId} src={fileUrl} title={t("简历原件")}
          className="w-full h-full rounded-md border border-outline-variant bg-surface-lowest" />
      );
    }
    return <FallbackText text={fallbackText} note={t("原始文件不可用，以下为提取文本")} />;
  }

  // 图片：直接展示
  if (["png", "jpg", "jpeg", "webp", "image"].some((s) => fmt.includes(s))) {
    if (exists === null) {
      fetch(fileUrl, { method: "HEAD" }).then((r) => setExists(r.ok)).catch(() => setExists(false));
      return <div className="flex items-center justify-center h-full"><LoadingIndicator size={28} label={t("正在加载图片...")} /></div>;
    }
    if (exists) {
      return (
        <div className="h-full overflow-y-auto flex justify-center bg-surface-lowest rounded-md border border-outline-variant p-4">
          <img src={fileUrl} alt={t("简历原件")} className="max-w-full h-auto rounded-sm shadow-sm" />
        </div>
      );
    }
    return <FallbackText text={fallbackText} note={t("原始图片不可用，以下为提取文本")} />;
  }

  // Markdown：原件用 iframe 加载源码，回退用轻量渲染提取文本
  if (fmt.includes("md") || fmt.includes("markdown")) {
    if (exists === null) {
      fetch(fileUrl, { method: "HEAD" }).then((r) => setExists(r.ok)).catch(() => setExists(false));
      return <div className="flex items-center justify-center h-full"><LoadingIndicator size={28} label={t("正在加载...")} /></div>;
    }
    if (exists) {
      return (
        <iframe key={`${candidateId}-md`} src={fileUrl} title={t("简历原件 (Markdown)")}
          className="w-full h-full rounded-md border border-outline-variant bg-surface-lowest" />
      );
    }
    return (
      <div className="h-full overflow-y-auto rounded-md border border-outline-variant bg-surface-lowest p-5">
        <MarkdownLite text={fallbackText} />
      </div>
    );
  }

  // JSON / TXT / 其他：纯文本
  return <FallbackText text={fallbackText} note="" />;
}

/** Markdown 轻量内联渲染（不引外部依赖），支持标题/加粗/列表/代码。 */
function MarkdownLite({ text }: { text: string }) {
  const html = renderMarkdown(text);
  return <div className="prose-custom text-body leading-relaxed text-on-surface" dangerouslySetInnerHTML={{ __html: html }} />;
}

function renderMarkdown(src: string): string {
  // 转义防 XSS
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let lines = src.split("\n").map(esc);
  const out: string[] = [];
  let inList = false;
  for (let line of lines) {
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { if (inList) { out.push("</ul>"); inList = false; } out.push(`<h${h[1].length}>${h[2]}</h${h[1].length}>`); continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${li[1]}</li>`); continue; }
    if (line.trim() === "") { if (inList) { out.push("</ul>"); inList = false; } out.push(""); continue; }
    if (inList) { out.push("</ul>"); inList = false; }
    line = line.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out.push(`<p>${line}</p>`);
  }
  if (inList) out.push("</ul>");
  return out.join("\n");
}

function FallbackText({ text, note }: { text: string; note: string }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col h-full min-h-0">
      {note && (
        <div className="shrink-0 flex items-center gap-2 px-3 py-2 mb-2 rounded-md bg-warning-container text-warning text-body-sm">
          <Icon name="info" size={16} />
          {note}
        </div>
      )}
      <pre className="flex-1 min-h-0 overflow-y-auto font-mono text-body-sm leading-relaxed whitespace-pre-wrap break-words p-4 rounded-md bg-surface-lowest border border-outline-variant text-on-surface-variant">
        {text || t("（无文本内容）")}
      </pre>
    </div>
  );
}

interface RecordSectionProps {
  title: string;
  icon: string;
  count?: number;
  className?: string;
  children: ReactNode;
  /** 导入预览态：无内容时显示等待骨架而非"暂无数据" */
  importing?: boolean;
}

function RecordSection({ title, icon, count, className, children, importing }: RecordSectionProps) {
  const { t } = useI18n();
  return (
    <section className={`border border-outline-variant rounded-md overflow-hidden bg-surface-lowest ${className || ""}`}>
      <div className="flex items-center gap-2 min-h-11 px-4 py-2.5 border-b border-outline-variant bg-surface-low">
        <Icon name={icon} size={18} className="text-primary" />
        <h3 className="text-title-lg font-bold text-on-surface">{title}</h3>
        {count !== undefined && <span className="ml-auto text-label text-on-surface-variant">{t("{n} 条", { n: count })}</span>}
      </div>
      <div>{children || (importing ? <SkeletonRows /> : <EmptyText />)}</div>
    </section>
  );
}

/** 导入中占位：脉冲骨架行，提示正在等待解析结果返回 */
function SkeletonRows() {
  return (
    <div className="px-4 py-3 space-y-2">
      {[88, 62].map((w, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="skeleton-block h-3.5 w-3.5 rounded-full" />
          <span className="skeleton-block h-3.5" style={{ width: `${w}%` }} />
        </div>
      ))}
    </div>
  );
}

function EmptyText() {
  const { t } = useI18n();
  return <p className="px-4 py-4 text-body-sm text-on-surface-variant">{t("暂无数据")}</p>;
}

function MetaField({ label, value, wide = false }: { label: string; value?: ReactNode; wide?: boolean }) {
  const { t } = useI18n();
  return (
    <div className={wide ? "col-span-2 min-w-0" : "min-w-0"}>
      <span className="block text-label font-medium text-on-surface-variant">{label}</span>
      <span className="block mt-0.5 text-body font-medium text-on-surface break-words">{value || t("未提供")}</span>
    </div>
  );
}

function EducationList({ detail, importing }: { detail: CandidateDetail; importing?: boolean }) {
  const { t } = useI18n();
  if (!(detail.education || []).length) return <EmptyText />;
  return (
    <div className="divide-y divide-outline-variant">
      {(detail.education || []).map((education, index) => {
        const item = typeof education === "string" ? { school: education } : education;
        const school = item.school || item.organization || item.name || "";
        const logo = getSchoolLogo(school);
        return (
          <article key={index} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3 px-4 py-3">
            <RecordIndex value={index + 1} />
            <div className="grid grid-cols-2 gap-x-3 gap-y-2 min-w-0">
              <div className="col-span-2 min-w-0">
                <span className="block text-label font-medium text-on-surface-variant">{t("院校")}</span>
                <p className="mt-0.5 text-body font-medium text-on-surface break-words">
                  {logo && (
                    <img
                      src={logo}
                      alt=""
                      className="inline-block h-[1.3em] w-[1.3em] align-[-0.25em] rounded-full object-contain bg-surface-lowest mr-1"
                    />
                  )}
                  {importing && school ? <TypewriterText text={school} /> : (school || t("未提供"))}
                </p>
              </div>
              <MetaField label={t("学历 / 专业")} value={[item.degree, item.major].filter(Boolean).join(" · ")} />
              <MetaField label={t("时间")} value={item.period || item.year} />
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ExperienceList({ detail, importing }: { detail: CandidateDetail; importing?: boolean }) {
  const { t } = useI18n();
  if (!(detail.experiences || []).length) return <EmptyText />;
  return (
    <div className="divide-y divide-outline-variant">
      {(detail.experiences || []).map((experience, index) => (
        <article key={index} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3 px-4 py-3">
          <RecordIndex value={index + 1} />
          <div className="min-w-0">
            <div className="grid grid-cols-2 gap-x-3 gap-y-2">
              <MetaField label={t("岗位")} value={importing && experience.role ? <TypewriterText text={experience.role} /> : experience.role} />
              <MetaField label={t("机构")} value={importing && experience.organization ? <TypewriterText text={experience.organization} /> : experience.organization} />
            </div>
            <DetailLines items={experience.details} />
          </div>
        </article>
      ))}
    </div>
  );
}

function ProjectList({ detail, importing }: { detail: CandidateDetail; importing?: boolean }) {
  const { t } = useI18n();
  if (!(detail.projects || []).length) return <EmptyText />;
  return (
    <div className="divide-y divide-outline-variant">
      {(detail.projects || []).map((project, index) => (
        <article key={index} className="grid grid-cols-[28px_minmax(0,1fr)_44px] gap-3 px-4 py-3">
          <RecordIndex value={index + 1} />
          <div className="min-w-0">
            <h4 className="text-title font-bold text-on-surface">
              {importing && project.name ? <TypewriterText text={project.name} /> : (project.name || t("未命名项目"))}
            </h4>
            <DetailLines items={project.details} />
          </div>
          <span className="text-label font-mono text-right text-on-surface-variant">{project.page ? `P${project.page}` : ""}</span>
        </article>
      ))}
    </div>
  );
}

function DetailLines({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <ul className="mt-2 space-y-1">
      {items.map((item, index) => (
        <li key={index} className="grid grid-cols-[8px_minmax(0,1fr)] gap-2 text-body-sm text-on-surface-variant">
          <span className="mt-2 w-1 h-1 rounded-full bg-outline" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function RecordIndex({ value }: { value: number }) {
  return (
    <span className="flex items-center justify-center w-7 h-7 rounded-sm bg-surface-high text-label font-bold text-on-surface-variant tabular-nums">
      {String(value).padStart(2, "0")}
    </span>
  );
}

function PublicationList({ detail, academicReport, importing, onReviewed }: { detail: CandidateDetail; academicReport: AcademicReport | null; importing?: boolean; onReviewed?: () => void }) {
  const { t } = useI18n();
  const publications = detail.publications || [];
  if (!publications.length) return <EmptyText />;
  const alignments = academicReport?.alignments || [];

  return (
    <div className="divide-y-2 divide-outline-variant">
      {publications.map((publication, index) => {
        const item = typeof publication === "string" ? { title: publication } : publication;
        const rawTitle = item.title || item.name || t("未命名成果");
        const alignment = findAlignment(rawTitle, index, alignments);
        const claim = alignment?.claim;
        const external = alignment?.external_record;
        const sourceUrl = external?.source_url || alignment?.source_url || alignment?.openalex_url || "";
        const sourceName = inferSourceName(external?.source || "") || inferSourceName(sourceUrl) || external?.source || "";
        const displayTitle = claim?.title || rawTitle;

        return (
          <article key={`${displayTitle}-${index}`}>
            <div className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-3 px-4 py-4 bg-surface-lowest">
              <RecordIndex value={index + 1} />
              <div className="min-w-0">
                <span className="text-label font-semibold text-primary">{t("论文")}</span>
                <h4 className="mt-1 text-[16px] leading-6 font-bold text-on-surface break-words">
                  {importing ? <TypewriterText text={displayTitle} /> : displayTitle}
                </h4>
              </div>
              <PublicationVerdict alignment={alignment} running={detail.academic_check_status === "running"} />
            </div>

            <div className="grid grid-cols-[104px_minmax(0,1fr)] border-t border-outline-variant">
              <RecordBandLabel icon="description" title={t("简历自述")} />
              <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3">
                <MetaField label={t("发表载体")} value={claim?.venue || item.venue || item.journal} />
                <MetaField label={t("年份")} value={claim?.year || item.year} />
                <MetaField label={t("自述状态")} value={claim?.claimed_status || item.claimed_status || item.status} />
                <MetaField label={t("作者角色")} value={claim?.claimed_role || item.claimed_role || item.role} />
              </div>
            </div>

            <div className="grid grid-cols-[104px_minmax(0,1fr)] border-t border-outline-variant bg-surface-low/40">
              <RecordBandLabel icon="travel_explore" title={t("外部记录")} />
              {alignment && (external?.title || alignment.matched_title) ? (
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3">
                  {/* 数据库标题本身即外链，来源名跟在标题后；有 OpenAlex 补充记录时一并给出 */}
                  <div className="col-span-2 min-w-0">
                    <span className="block text-label font-medium text-on-surface-variant">
                      {t("数据库标题")}{sourceName ? ` · ${sourceName}` : ""}
                    </span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                      {sourceUrl ? (
                        <a
                          href={sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-body font-medium text-primary break-words hover:underline underline-offset-2"
                        >
                          {external?.title || alignment.matched_title}
                          <Icon name="open_in_new" size={15} className="shrink-0" />
                        </a>
                      ) : (
                        <span className="text-body font-medium text-on-surface break-words">
                          {external?.title || alignment.matched_title}
                        </span>
                      )}
                      {!!alignment?.openalex_url && alignment.openalex_url !== sourceUrl && (
                        <a
                          href={alignment.openalex_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex shrink-0 items-center gap-0.5 text-label font-semibold text-primary hover:underline underline-offset-2"
                        >
                          OpenAlex
                          <Icon name="open_in_new" size={13} />
                        </a>
                      )}
                    </span>
                  </div>
                  <MetaField label={t("载体 / 年份")} value={[external?.venue, external?.year].filter(Boolean).join(" · ")} />
                  <MetaField label={t("发表状态")} value={external?.publication_status || alignment.verified_status} />
                  <div className="min-w-0">
                    <span className="block text-label font-medium text-on-surface-variant">{t("作者列表")}</span>
                    <p className="mt-0.5 text-body font-medium text-on-surface break-words">
                      <AuthorList authors={external?.authors || []} alignment={alignment} />
                    </p>
                  </div>
                  <MetaField label={t("引用次数")} value={external?.cited_by_count ?? alignment.cited_by_count ?? 0} />
                  <MetaField label={t("撤稿标记")} value={external?.is_retracted || alignment.is_retracted ? t("是") : t("否")} />
                </div>
              ) : (
                <p className="px-4 py-4 text-body-sm text-on-surface-variant">{t("未取得可用的外部论文记录")}</p>
              )}
            </div>

            <div className="grid grid-cols-[104px_minmax(0,1fr)] border-t border-outline-variant">
              <RecordBandLabel icon="fact_check" title={t("核验结论")} />
              <div className="px-4 py-3 min-w-0">
                <div className="grid grid-cols-2 gap-2">
                  <CheckBadge label={t("标题")} status={alignment?.checks?.title} />
                  <CheckBadge label={t("作者身份")} status={alignment?.checks?.author_identity} />
                  <CheckBadge label={t("作者顺序")} status={alignment?.checks?.author_position} />
                  <CheckBadge label={t("发表状态")} status={alignment?.checks?.publication_status} />
                </div>
                {!!alignment?.discrepancies?.length && (
                  <div className="mt-3 border-l-2 border-error pl-3">
                    <p className="text-label font-semibold text-error">{t("发现差异")}</p>
                    {alignment.discrepancies.map((difference, differenceIndex) => (
                      <p key={differenceIndex} className="mt-1 text-body-sm font-medium text-error">{difference}</p>
                    ))}
                  </div>
                )}
                <div className="mt-3 pt-3 border-t border-outline-variant">
                  <p className="text-body-sm text-on-surface-variant">{alignment?.note || t("暂无补充说明")}</p>
                </div>
                {!importing && alignment && detail.academic_check_status === "done" && (
                  <div className="mt-3 pt-3 border-t border-outline-variant">
                    <ReviewActions
                      candidateId={detail.id}
                      alignment={alignment}
                      alignmentIndex={alignments.indexOf(alignment)}
                      onReviewed={onReviewed}
                    />
                  </div>
                )}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function findAlignment(title: string, index: number, alignments: ClaimAlignment[]) {
  const normalized = title.trim().toLowerCase();
  return alignments.find((alignment) => alignment.claim?.title?.trim().toLowerCase() === normalized)
    || alignments.find((alignment) => {
      const claimTitle = alignment.claim?.title?.trim().toLowerCase();
      return claimTitle && (normalized.includes(claimTitle) || claimTitle.includes(normalized));
    })
    || alignments[index];
}

function inferSourceName(url: string) {
  const normalized = url.toLowerCase();
  if (normalized.includes("aminer")) return "AMiner";
  if (normalized.includes("openalex")) return "OpenAlex";
  return "";
}

function RecordBandLabel({ icon, title }: { icon: string; title: string }) {
  return (
    <div className="flex items-start gap-2 px-4 py-3 bg-surface-low border-r border-outline-variant">
      <Icon name={icon} size={16} className="mt-0.5 text-on-surface-variant" />
      <span className="text-label font-bold text-on-surface-variant">{title}</span>
    </div>
  );
}

function PublicationVerdict({ alignment, running }: { alignment?: ClaimAlignment; running: boolean }) {
  const { t } = useI18n();
  if (!alignment && running) {
    return (
      <span className="inline-flex h-7 items-center gap-2 px-2 text-label font-semibold text-primary">
        <LoadingIndicator size={15} color="text-primary" />{t("核验中")}
      </span>
    );
  }
  if (!alignment) return <StatusChip tone="warning" variant="filled" icon="schedule">{t("待核验")}</StatusChip>;
  if (alignment.human_status === "confirmed") return <StatusChip tone="success" variant="filled" icon="person_check">{t("人工通过")}</StatusChip>;
  if (alignment.human_status === "dismissed") return <StatusChip tone="error" variant="filled" icon="person_cancel">{t("人工驳回")}</StatusChip>;
  if (alignment.verdict === "verified") return <StatusChip tone="success" variant="filled" icon="verified">{t("核验通过")}</StatusChip>;
  if (alignment.verdict === "mismatch") return <StatusChip tone="error" variant="filled" icon="error">{t("存在冲突")}</StatusChip>;
  return <StatusChip tone="warning" variant="filled" icon="help">{t("待人工核验")}</StatusChip>;
}

/** 论文人工裁决：判 AI 核验结论对不对，所有 verdict 都可裁决，备注都进评估 */
function ReviewActions({ candidateId, alignment, alignmentIndex, onReviewed }: {
  candidateId: string;
  alignment: ClaimAlignment;
  alignmentIndex: number;
  onReviewed?: () => void;
}) {
  const human = alignment.human_status;
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(human === "unreviewed" || !human);
  const { t } = useI18n();

  // 按钮文案随 verdict 变化（语义：判 AI 结论对不对）
  const presets: Record<string, { ok: { label: string; icon: string }; no: { label: string; icon: string } }> = {
    verified: { ok: { label: t("AI判定正确"), icon: "check" }, no: { label: t("AI判定有误"), icon: "warning" } },
    mismatch: { ok: { label: t("AI判定正确"), icon: "check" }, no: { label: t("AI判定有误"), icon: "undo" } },
    unverifiable: { ok: { label: t("确认属实"), icon: "person_check" }, no: { label: t("驳回"), icon: "person_cancel" } },
  };
  const preset = presets[alignment.verdict] || presets.unverifiable;

  const submit = async (action: "confirmed" | "dismissed") => {
    setBusy(true);
    try {
      await api.candidates.reviewPublication(candidateId, alignmentIndex, action, "HR审核", note.trim());
      setEditing(false);
      onReviewed?.();
    } catch (err) {
      console.error("裁决失败", err);
    } finally {
      setBusy(false);
    }
  };

  if (!editing && human && human !== "unreviewed") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={human === "confirmed" ? "success" : "error"} variant="filled"
          icon={human === "confirmed" ? "person_check" : "person_cancel"}>
          {human === "confirmed" ? t("人工确认（AI判定正确）") : t("人工驳回（AI判定有误）")}
        </StatusChip>
        {alignment.human_reviewer && <span className="text-label text-on-surface-variant">{alignment.human_reviewer}</span>}
        {alignment.human_note && <span className="text-body-sm text-on-surface-variant">· {alignment.human_note}</span>}
        <Button variant="text" className="h-7 px-2 text-xs" onClick={() => { setEditing(true); setNote(alignment.human_note || ""); }}>
          {t("修改")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-label font-medium text-on-surface-variant">{t("人工裁决（判 AI 核验结论对不对，备注将进入评估）")}</p>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        placeholder={t("人工备注（可选），将进入后续评估…")}
        className="w-full rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2 text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary resize-y"
      />
      <div className="flex items-center gap-2">
        <Button variant="filled" icon={preset.ok.icon} disabled={busy} onClick={() => submit("confirmed")} className="h-8">
          {preset.ok.label}
        </Button>
        <Button variant="tonal" icon={preset.no.icon} disabled={busy} onClick={() => submit("dismissed")} className="h-8">
          {preset.no.label}
        </Button>
      </div>
    </div>
  );
}

function CheckBadge({ label, status }: { label: string; status?: VerificationCheckStatus }) {
  const { t } = useI18n();
  const config = status === "match"
    ? { icon: "check_circle", text: t("一致"), className: "text-success" }
    : status === "mismatch"
      ? { icon: "cancel", text: t("冲突"), className: "text-error" }
      : { icon: "schedule", text: t("未确认"), className: "text-on-surface-variant" };
  return (
    <div className="grid grid-cols-[72px_18px_minmax(0,1fr)] items-center gap-2 min-h-8 px-2 bg-surface-low rounded-sm">
      <span className="text-label font-medium text-on-surface-variant">{label}</span>
      <Icon name={config.icon} size={16} className={config.className} />
      <span className={`text-label font-bold ${config.className}`}>{config.text}</span>
    </div>
  );
}

/** 作者列表：候选人高亮加粗。优先用 position 精确加粗，
 *  无 position 时用 candidate_author_name 模糊匹配兜底（含缩写）。 */
function AuthorList({ authors, alignment }: { authors: string[]; alignment?: ClaimAlignment }) {
  const { t } = useI18n();
  if (!authors.length) return <span className="text-on-surface-variant">{t("未提供")}</span>;
  const pos = alignment?.candidate_author_position || 0;
  const matchName = (alignment?.candidate_author_name || "").toLowerCase().replace(/[\s.\-_,]/g, "");
  return (
    <>
      {authors.map((author, i) => {
        const isCandidate = pos > 0
          ? i === pos - 1  // position 精确匹配（1-based）
          : matchName && author.toLowerCase().replace(/[\s.\-_,]/g, "").includes(matchName);
        return (
          <span key={i}>
            {i > 0 && t("、")}
            <span className={isCandidate ? "font-bold text-primary underline decoration-primary/40 underline-offset-2" : ""}>
              {author}
            </span>
          </span>
        );
      })}
    </>
  );
}

function SkillsList({ detail, importing }: { detail: CandidateDetail; importing?: boolean }) {
  if (!(detail.skills || []).length) return <EmptyText />;
  return (
    <div className="grid grid-cols-2 gap-px bg-outline-variant">
      {(detail.skills || []).map((skill, index) => (
        <div key={`${skill}-${index}`} className="grid grid-cols-[28px_minmax(0,1fr)] items-center gap-3 px-4 py-2.5 bg-surface-lowest">
          <RecordIndex value={index + 1} />
          <span className="text-body font-medium text-on-surface">
            {importing ? <TypewriterText text={skill} /> : skill}
          </span>
        </div>
      ))}
    </div>
  );
}
