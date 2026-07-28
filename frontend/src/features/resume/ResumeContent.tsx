import { useState } from "react";
import type { CandidateDetail } from "@/lib/types";
import { cn } from "@/lib/cn";

interface Props {
  detail: CandidateDetail;
}

export default function ResumeContent({ detail }: Props) {
  const [mode, setMode] = useState<"structured" | "raw">("structured");
  const directions = (detail.directions || []).filter(Boolean);

  return (
    <div>
      {/* segmented */}
      <div className="flex gap-1 p-1 rounded-[10px] bg-white/35 w-fit mb-4">
        {(["structured", "raw"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              "px-4 py-1 rounded-full text-xs transition-colors",
              mode === m ? "bg-teal-soft text-teal" : "text-ink-secondary"
            )}
          >
            {m === "structured" ? "结构化简历" : "原文"}
          </button>
        ))}
      </div>

      {mode === "raw" ? (
        <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap break-words p-3 bg-surface-paper rounded-[10px] border border-ink/10 max-h-[70vh] overflow-y-auto">
          {detail.raw_text || "（无原文）"}
        </pre>
      ) : (
        <div>
          {/* 标题块 */}
          <div className="mb-6">
            <h2 className="text-2xl font-semibold">{detail.name || detail.id}</h2>
            <p className="text-sm text-ink-secondary mt-1">
              {detail.stage}
              {detail.role ? ` · ${detail.role}` : ""}
            </p>
            {directions.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {directions.map((d) => (
                  <span key={d} className="text-xs px-2 py-0.5 rounded-full bg-blue-soft text-blue">
                    {d}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 章节 */}
          <Section title="教育经历">
            {(detail.education || []).map((edu, i) => {
              const item = typeof edu === "string" ? { school: edu } : edu;
              return (
                <div key={i} className="flex items-baseline gap-3 py-0.5 text-sm">
                  <span className="font-medium">{item.school || item.organization || item.name || edu}</span>
                  {item.degree || item.major ? <span className="text-xs text-ink-secondary">{item.degree || item.major}</span> : null}
                  {item.period || item.year ? <span className="text-xs text-ink-secondary ml-auto">{item.period || item.year}</span> : null}
                </div>
              );
            })}
          </Section>

          <Section title="实习 / 工作经历">
            {(detail.experiences || []).map((exp, i) => (
              <div key={i} className="py-1">
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className="font-medium text-sm">{exp.role}</span>
                  {exp.organization && <span className="text-xs text-ink-secondary">{exp.organization}</span>}
                </div>
                {(exp.details || []).map((d, j) => (
                  <p key={j} className="text-xs text-ink-secondary ml-1">{d}</p>
                ))}
              </div>
            ))}
          </Section>

          <Section title="项目经历">
            {(detail.projects || []).map((proj, i) => (
              <div key={i} className="py-1">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="font-medium text-sm">{proj.name || "未命名项目"}</span>
                  {proj.page && (
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-teal-soft text-teal shrink-0">
                      P{proj.page}
                    </span>
                  )}
                </div>
                {(proj.details || []).map((d, j) => (
                  <p key={j} className="text-xs text-ink-secondary">{d}</p>
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
                    <span className="font-medium text-sm flex-1">{item.title || item.name || pub}</span>
                    {status && <PubBadge status={status} />}
                  </div>
                  {(item.venue || item.journal || item.year || item.claimed_role || item.role) && (
                    <p className="text-xs text-ink-secondary mt-0.5">
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
                <span key={s} className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const arr = Array.isArray(children) ? children : [children];
  if (!arr.filter(Boolean).length) return null;
  return (
    <section className="mb-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-3 pb-2 border-b border-ink/10">
        {title}
      </h3>
      {children}
    </section>
  );
}

function PubBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const cls =
    s.includes("published") || s.includes("已发表") ? "bg-teal-soft text-teal" :
    s.includes("review") || s.includes("在审") || s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "bg-amber-soft text-amber-glow" :
    "bg-surface-mist text-ink-secondary";
  const label =
    s.includes("published") || s.includes("已发表") ? "已发表" :
    s.includes("review") || s.includes("在审") ? "在审" :
    s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "已投稿" :
    s.includes("accept") || s.includes("接收") ? "已接收" :
    s.includes("draft") || s.includes("草稿") ? "草稿" : status;
  return <span className={cn("text-[10px] px-2 py-0.5 rounded-full shrink-0", cls)}>{label}</span>;
}
