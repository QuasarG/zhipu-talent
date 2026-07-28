import { useState } from "react";
import type { ReactNode } from "react";
import type { CandidateDetail } from "@/lib/types";
import Tabs from "@/components/ui/Tabs";
import { StatusChip } from "@/components/ui/Chip";

interface Props {
  detail: CandidateDetail;
}

export default function ResumeContent({ detail }: Props) {
  const [mode, setMode] = useState<"structured" | "raw">("structured");
  const directions = (detail.directions || []).filter(Boolean);

  return (
    <div>
      <Tabs
        className="mb-5"
        items={[
          { value: "structured", label: "结构化简历" },
          { value: "raw", label: "原文" },
        ]}
        value={mode}
        onChange={setMode}
      />

      {mode === "raw" ? (
        <pre className="font-mono text-body-sm leading-relaxed whitespace-pre-wrap break-words p-4 rounded-md bg-surface-lowest border border-outline-variant text-on-surface-variant max-h-[70vh] overflow-y-auto">
          {detail.raw_text || "（无原文）"}
        </pre>
      ) : (
        <div>
          {/* 标题块 */}
          <div className="mb-6">
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

          {/* 章节 */}
          <Section title="教育经历">
            {(detail.education || []).map((edu, i) => {
              const item = typeof edu === "string" ? { school: edu } : edu;
              return (
                <div key={i} className="flex items-baseline gap-3 py-0.5 text-body">
                  <span className="font-medium">{item.school || item.organization || item.name || (typeof edu === "string" ? edu : "")}</span>
                  {item.degree || item.major ? <span className="text-body-sm text-on-surface-variant">{item.degree || item.major}</span> : null}
                  {item.period || item.year ? <span className="text-body-sm text-on-surface-variant ml-auto">{item.period || item.year}</span> : null}
                </div>
              );
            })}
          </Section>

          <Section title="实习 / 工作经历">
            {(detail.experiences || []).map((exp, i) => (
              <div key={i} className="py-1">
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className="font-medium text-body">{exp.role}</span>
                  {exp.organization && <span className="text-body-sm text-on-surface-variant">{exp.organization}</span>}
                </div>
                {(exp.details || []).map((d, j) => (
                  <p key={j} className="text-body-sm text-on-surface-variant ml-1">{d}</p>
                ))}
              </div>
            ))}
          </Section>

          <Section title="项目经历">
            {(detail.projects || []).map((proj, i) => (
              <div key={i} className="py-1">
                <div className="flex items-center justify-between gap-2 mb-0.5">
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
          </Section>

          <Section title="论文与成果">
            {(detail.publications || []).map((pub, i) => {
              const item = typeof pub === "string" ? { title: pub } : pub;
              const status = item.claimed_status || item.status || "";
              return (
                <div key={i} className="py-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-body flex-1">{item.title || item.name || (typeof pub === "string" ? pub : "")}</span>
                    {status && <PubBadge status={status} />}
                  </div>
                  {(item.venue || item.journal || item.year || item.claimed_role || item.role) && (
                    <p className="text-body-sm text-on-surface-variant mt-0.5">
                      {[item.venue || item.journal, item.year, item.claimed_role || item.role].filter(Boolean).join(" · ")}
                    </p>
                  )}
                </div>
              );
            })}
          </Section>

          <Section title="技能">
            <div className="flex flex-wrap gap-2">
              {(detail.skills || []).map((s) => (
                <span key={s} className="text-body-sm px-2.5 py-1 rounded-sm bg-surface-high text-on-surface-variant">
                  {s}
                </span>
              ))}
            </div>
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const arr = Array.isArray(children) ? children : [children];
  if (!arr.filter(Boolean).length) return null;
  return (
    <section className="mb-6">
      <h3 className="text-label uppercase tracking-wider text-on-surface-variant mb-3 pb-2 border-b border-outline-variant">
        {title}
      </h3>
      {children}
    </section>
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
