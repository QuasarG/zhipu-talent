import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import type { CandidateDetail } from "@/lib/types";
import Tabs from "@/components/ui/Tabs";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";

interface Props {
  detail: CandidateDetail;
}

export default function ResumeContent({ detail }: Props) {
  const [mode, setMode] = useState<"structured" | "raw">("structured");
  const directions = (detail.directions || []).filter(Boolean);

  return (
    <div className="flex flex-col h-full min-h-0">
      <Tabs
        className="mb-4 shrink-0"
        items={[
          { value: "structured", label: "结构化简历" },
          { value: "raw", label: "简历原文" },
        ]}
        value={mode}
        onChange={setMode}
      />

      <div className="flex-1 min-h-0">
        {mode === "raw" ? (
          <PdfPreview candidateId={detail.id} fallbackText={detail.raw_text || ""} />
        ) : (
          <div className="h-full min-h-0 flex flex-col gap-4">
            {/* 标题块：固定不滚 */}
            <div className="shrink-0">
              <h2 className="text-headline">{detail.name || detail.id}</h2>
              <p className="text-body-sm text-on-surface-variant mt-1">
                {detail.stage}
                {detail.role ? ` · ${detail.role}` : ""}
              </p>
              {directions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {directions.map((d) => (
                    <StatusChip key={d} tone="info">{d}</StatusChip>
                  ))}
                </div>
              )}
            </div>

            {/* 卡片网格：页不滚，每张卡内部可滚 */}
            <div className="flex-1 min-h-0 grid grid-cols-2 gap-4 overflow-hidden">
              <ModuleCard title="教育经历" icon="school">
                <EducationList detail={detail} />
              </ModuleCard>
              <ModuleCard title="实习 / 工作经历" icon="work">
                <ExperienceList detail={detail} />
              </ModuleCard>
              <ModuleCard title="项目经历" icon="construction">
                <ProjectList detail={detail} />
              </ModuleCard>
              <ModuleCard title="论文与成果" icon="menu_book">
                <PublicationList detail={detail} />
              </ModuleCard>
              <ModuleCard title="技能" icon="bolt" className="col-span-2">
                <SkillsList detail={detail} />
              </ModuleCard>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---- PDF 预览（含 raw_text fallback）---- */
function PdfPreview({ candidateId, fallbackText }: { candidateId: string; fallbackText: string }) {
  const [pdfOk, setPdfOk] = useState<boolean | null>(null);

  useEffect(() => {
    setPdfOk(null);
    // HEAD 探测 PDF 是否存在；同源请求自动带 session cookie
    fetch(`/api/candidates/${candidateId}/pdf`, { method: "HEAD" })
      .then((r) => setPdfOk(r.ok))
      .catch(() => setPdfOk(false));
  }, [candidateId]);

  if (pdfOk === null) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingIndicator size={28} label="正在加载 PDF…" />
      </div>
    );
  }

  if (pdfOk) {
    return (
      <iframe
        key={candidateId}
        src={`/api/candidates/${candidateId}/pdf`}
        title="简历 PDF"
        className="w-full h-full rounded-lg border border-outline-variant bg-surface-lowest"
      />
    );
  }

  // 无 PDF（历史数据 / 非 PDF 导入）→ fallback 显示提取文本
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 mb-2 rounded-md bg-warning-container text-warning text-body-sm">
        <Icon name="info" size={16} />
        原始 PDF 不可用，以下为提取文本
      </div>
      <pre className="flex-1 min-h-0 overflow-y-auto font-mono text-body-sm leading-relaxed whitespace-pre-wrap break-words p-4 rounded-lg bg-surface-lowest border border-outline-variant text-on-surface-variant">
        {fallbackText || "（无文本内容）"}
      </pre>
    </div>
  );
}

/* ---- 模块卡片：标题固定，内容区可滚 ---- */
interface ModuleCardProps {
  title: string;
  icon: string;
  className?: string;
  children: ReactNode;
}

function ModuleCard({ title, icon, className, children }: ModuleCardProps) {
  const arr = Array.isArray(children) ? children : [children];
  const hasContent = arr.filter(Boolean).length > 0;
  return (
    <Card variant="outlined" className={`flex flex-col min-h-0 overflow-hidden ${className || ""}`}>
      <div className="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-outline-variant bg-surface-low">
        <Icon name={icon} size={16} className="text-on-surface-variant" />
        <h3 className="text-title text-on-surface">{title}</h3>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {hasContent ? children : (
          <p className="text-body-sm text-on-surface-variant">暂无数据</p>
        )}
      </div>
    </Card>
  );
}

/* ---- 各模块内容 ---- */
function EducationList({ detail }: { detail: CandidateDetail }) {
  if (!(detail.education || []).length) return null;
  return (
    <div className="flex flex-col gap-2">
      {(detail.education || []).map((edu, i) => {
        const item = typeof edu === "string" ? { school: edu } : edu;
        return (
          <div key={i} className="flex items-baseline gap-3 text-body">
            <span className="font-medium">{item.school || item.organization || item.name || (typeof edu === "string" ? edu : "")}</span>
            {item.degree || item.major ? <span className="text-body-sm text-on-surface-variant">{item.degree || item.major}</span> : null}
            {item.period || item.year ? <span className="text-body-sm text-on-surface-variant ml-auto">{item.period || item.year}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

function ExperienceList({ detail }: { detail: CandidateDetail }) {
  if (!(detail.experiences || []).length) return null;
  return (
    <div className="flex flex-col gap-3">
      {(detail.experiences || []).map((exp, i) => (
        <div key={i}>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="font-medium text-body">{exp.role}</span>
            {exp.organization && <span className="text-body-sm text-on-surface-variant">{exp.organization}</span>}
          </div>
          {(exp.details || []).map((d, j) => (
            <p key={j} className="text-body-sm text-on-surface-variant ml-1">{d}</p>
          ))}
        </div>
      ))}
    </div>
  );
}

function ProjectList({ detail }: { detail: CandidateDetail }) {
  if (!(detail.projects || []).length) return null;
  return (
    <div className="flex flex-col gap-3">
      {(detail.projects || []).map((proj, i) => (
        <div key={i}>
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="font-medium text-body">{proj.name || "未命名项目"}</span>
            {proj.page && (
              <span className="font-mono text-label px-1.5 rounded-xs bg-primary-container text-on-primary-container shrink-0">
                P{proj.page}
              </span>
            )}
          </div>
          {(proj.details || []).map((d, j) => (
            <p key={j} className="text-body-sm text-on-surface-variant">{d}</p>
          ))}
        </div>
      ))}
    </div>
  );
}

function PublicationList({ detail }: { detail: CandidateDetail }) {
  const pubs = detail.publications || [];
  if (!pubs.length) return null;
  // 论文核验对齐表：以 claim.title 为 key
  const alignments = detail.academic_report?.alignments || [];
  const hasReport = !!detail.academic_report;
  const alignByTitle = new Map<string, typeof alignments[number]>();
  for (const a of alignments) {
    if (a.claim?.title) alignByTitle.set(a.claim.title, a);
  }
  return (
    <div className="flex flex-col gap-3">
      {pubs.map((pub, i) => {
        const item = typeof pub === "string" ? { title: pub } : pub;
        const title = item.title || item.name || (typeof pub === "string" ? pub : "");
        const status = item.claimed_status || item.status || "";
        // 匹配核验结果：优先精确 title，否则按包含匹配
        const align = alignByTitle.get(title)
          || alignments.find((a) => a.claim?.title && title.includes(a.claim.title));
        return (
          <div key={i}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-body flex-1">{title}</span>
              {align ? <VerdictBadge verdict={align.verdict} /> : hasReport ? (
                <StatusChip tone="warning" icon="help">待核验</StatusChip>
              ) : (
                <span className="inline-flex items-center gap-1 text-label text-on-surface-variant shrink-0">
                  <LoadingIndicator size={14} color="text-on-surface-variant" />
                  核验中
                </span>
              )}
            </div>
            {(item.venue || item.journal || item.year || item.claimed_role || item.role) && (
              <p className="text-body-sm text-on-surface-variant mt-0.5">
                {[item.venue || item.journal, item.year, item.claimed_role || item.role].filter(Boolean).join(" · ")}
              </p>
            )}
            {align && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {status && <PubBadge status={status} />}
                {align.matched_title && (
                  <span className="text-label text-on-surface-variant truncate max-w-[200px]" title={align.matched_title}>
                    匹配：{align.matched_title}
                  </span>
                )}
                {align.cited_by_count ? (
                  <span className="text-label text-on-surface-variant">引用 {align.cited_by_count}</span>
                ) : null}
                {align.openalex_url && (
                  <a href={align.openalex_url} target="_blank" rel="noopener noreferrer" className="text-label text-primary hover:underline">
                    OpenAlex ↗
                  </a>
                )}
                {align.note && (
                  <span className="text-label text-on-surface-variant">{align.note}</span>
                )}
              </div>
            )}
            {align?.discrepancies && align.discrepancies.length > 0 && (
              <ul className="mt-1 ml-4 list-disc text-body-sm text-error">
                {align.discrepancies.map((d, j) => <li key={j}>{d}</li>)}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function VerdictBadge({ verdict }: { verdict: "verified" | "mismatch" | "unverifiable" }) {
  const config = {
    verified: { tone: "success" as const, icon: "verified", label: "已验证" },
    mismatch: { tone: "error" as const, icon: "gpp_maybe", label: "存疑" },
    unverifiable: { tone: "warning" as const, icon: "help", label: "待核验" },
  };
  const c = config[verdict] || config.unverifiable;
  return <StatusChip tone={c.tone} icon={c.icon}>{c.label}</StatusChip>;
}

function SkillsList({ detail }: { detail: CandidateDetail }) {
  if (!(detail.skills || []).length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {(detail.skills || []).map((s) => (
        <span key={s} className="text-body-sm px-2.5 py-1 rounded-sm bg-surface-high text-on-surface-variant">
          {s}
        </span>
      ))}
    </div>
  );
}

function PubBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const tone =
    s.includes("published") || s.includes("已发表") ? "success" :
    s.includes("review") || s.includes("在审") || s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "warning" :
    "neutral";
  const label =
    s.includes("published") || s.includes("已发表") ? "已发表" :
    s.includes("review") || s.includes("在审") ? "在审" :
    s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "已投稿" :
    s.includes("accept") || s.includes("接收") ? "已接收" :
    s.includes("draft") || s.includes("草稿") ? "草稿" : status;
  return <StatusChip tone={tone} className="shrink-0">{label}</StatusChip>;
}
