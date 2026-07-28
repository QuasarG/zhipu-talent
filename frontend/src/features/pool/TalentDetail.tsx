import { useState } from "react";
import type { PersonDetail } from "@/lib/types";
import { api } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import Progress from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import { classifyTrack, STATUS_LABELS } from "./TalentList";

interface Props {
  person: PersonDetail | null;
  personId: string | null;
  onUpdated: (id: string) => void;
}

const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }));

const TRACK_TOKENS: Record<string, string> = {
  agent: "var(--color-track-agent)", safety: "var(--color-track-safety)",
  systems: "var(--color-track-systems)", ai4science: "var(--color-track-ai4science)",
  multimodal: "var(--color-track-multimodal)",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TalentDetail({ person, personId, onUpdated }: Props) {
  const [engagement, setEngagement] = useState("");
  const [saving, setSaving] = useState(false);

  if (!person) {
    return (
      <Card variant="elevated" className="min-h-0 overflow-y-auto p-4">
        <div className="flex flex-col items-center justify-center h-full text-center gap-2">
          <Icon name="person_search" size={32} className="text-on-surface-variant" />
          <p className="text-body text-on-surface">从左侧选择一位人才</p>
          <p className="text-body-sm text-on-surface-variant">查看统一人才档案</p>
        </div>
      </Card>
    );
  }

  const evaluations = person.evaluations || [];
  const latest = evaluations[0];
  const reputation = person.reputation_reports || [];
  const initials = (person.name || "?").charAt(0);
  const candidateId = personId || "";
  const track = classifyTrack(person);

  const saveEngagement = async () => {
    if (!engagement || !candidateId) return;
    setSaving(true);
    try {
      // person.id 作为 candidate_id 兜底
      await api.candidates.updateEngagement(candidateId, engagement, "hr-web", "网页修改");
      onUpdated(candidateId);
    } catch {
      // person_id 可能不等于 candidate_id，尝试 person admit 后再 update
    } finally {
      setSaving(false);
    }
  };

  const tracks = [...(latest?.recommended_tracks || [])].sort((a, b) => b.weight - a.weight).slice(0, 3);

  return (
    <Card variant="elevated" className="min-h-0 overflow-y-auto flex flex-col">
      <div className="p-4 pb-3 border-b border-outline-variant">
        <div className="flex items-start gap-3">
          <div className="w-12 h-12 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-title-lg shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-1">
              <span className="text-title-lg text-on-surface truncate">{person.name}</span>
              <IconButton icon="more_vert" size={18} className="w-8 h-8 shrink-0" />
            </div>
            <p className="text-body-sm text-on-surface-variant truncate">
              {person.org || "—"} · {person.direction || "—"}
            </p>
            <div className="flex gap-1 mt-1.5">
              <StatusChip tone={person.person_type === "guest" ? "info" : "primary"}>
                {person.person_type === "guest" ? "人物调查" : "简历评估"}
              </StatusChip>
              {track && <StatusChip tone="neutral" className="capitalize">{track}</StatusChip>}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 p-4 flex flex-col gap-5">
        {/* HR 跟进状态 */}
        <section>
          <h3 className="text-title mb-2">HR 跟进状态</h3>
          <div className="flex items-center gap-2">
            <select
              value={engagement}
              onChange={(e) => setEngagement(e.target.value)}
              className="h-9 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface cursor-pointer"
            >
              <option value="">选择状态…</option>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <Button variant="tonal" className="h-9 px-4" onClick={saveEngagement} disabled={!engagement || saving}>
              保存
            </Button>
          </div>
        </section>

        {/* 能力概览 */}
        {latest && (
          <section>
            <h3 className="text-title mb-2">能力概览</h3>
            <div className="flex items-baseline gap-2">
              <span className="text-display text-on-surface">{latest.overall_score ?? "—"}</span>
              <span className="text-body-sm text-on-surface-variant">/100</span>
              <span className="ml-auto text-label text-on-surface-variant text-right">
                能力描述，<br />不代表录取结论
              </span>
            </div>
            {latest.dimension_scores?.length > 0 && (
              <div className="flex gap-4 mt-2">
                {latest.dimension_scores.slice(0, 3).map((d) => (
                  <div key={d.key}>
                    <p className="text-label text-on-surface-variant">{d.label}</p>
                    <p className="text-body font-medium text-on-surface">
                      {d.score} <span className="text-on-surface-variant font-normal">/ {d.max_points}</span>
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 推荐 Track */}
        {tracks.length > 0 && (
          <section>
            <h3 className="text-title mb-2">推荐 Track</h3>
            <div className="flex flex-col gap-2">
              {tracks.map((t, i) => {
                const name = t.track || t.name || "";
                return (
                  <div key={i} className="grid grid-cols-[16px_88px_minmax(0,1fr)_36px] items-center gap-2">
                    <span className="text-label text-on-surface-variant">{i + 1}</span>
                    <span className="text-body-sm text-on-surface capitalize truncate">{name}</span>
                    <Progress value={t.weight * 100} color={TRACK_TOKENS[name.toLowerCase()]} />
                    <span className="text-label text-on-surface-variant text-right">{t.weight.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 研究组匹配 */}
        <section className="rounded-md bg-surface-low p-3">
          <h3 className="text-title mb-1.5">研究组匹配</h3>
          <StatusChip tone="neutral">尚未配置研究组要求</StatusChip>
          <p className="text-label text-on-surface-variant mt-1.5">Track 推荐不等于具体研究组匹配</p>
        </section>

        {/* 关系证据 */}
        <section>
          <h3 className="text-title mb-2">关系证据</h3>
          <div className="flex flex-col gap-2">
            {person.org && (
              <div className="flex items-center gap-2">
                <Icon name="school" size={18} className="text-on-surface-variant shrink-0" />
                <span className="text-body-sm text-on-surface flex-1 truncate">{person.org}</span>
                <span className="text-label text-on-surface-variant">教育经历</span>
                <StatusChip tone="success">已确认</StatusChip>
              </div>
            )}
            {reputation.map((r) => {
              const confirmed = ["approved", "confirmed", "已确认"].includes(r.review_status || "");
              return (
                <div key={r.id} className="flex items-center gap-2">
                  <Icon name="campaign" size={18} className="text-on-surface-variant shrink-0" />
                  <span className="text-body-sm text-on-surface flex-1 truncate">舆情核查 · {r.level || "—"}</span>
                  <StatusChip tone={confirmed ? "success" : "warning"}>
                    {confirmed ? "已确认" : "待核验"}
                  </StatusChip>
                </div>
              );
            })}
            {!person.org && reputation.length === 0 && (
              <p className="text-body-sm text-on-surface-variant">暂无关系证据</p>
            )}
          </div>
        </section>

        {/* 最近更新 */}
        <section>
          <h3 className="text-title mb-2">最近更新</h3>
          <div className="flex flex-col gap-1.5 text-body-sm">
            <div className="flex items-center gap-2">
              <Icon name="description" size={16} className="text-on-surface-variant" />
              <span className="text-on-surface flex-1">简历评估</span>
              <span className="text-on-surface-variant">{evaluations.length ? `v${evaluations.length}` : "—"}</span>
            </div>
            <div className="flex items-center gap-2">
              <Icon name="fact_check" size={16} className="text-on-surface-variant" />
              <span className="text-on-surface flex-1">舆情核查</span>
              <span className="text-on-surface-variant">{reputation.length ? `${reputation.length} 条` : "—"}</span>
            </div>
            <div className="flex items-center gap-2">
              <Icon name="schedule" size={16} className="text-on-surface-variant" />
              <span className="text-on-surface flex-1">档案更新</span>
              <span className="text-on-surface-variant">{fmtTime(person.updated_at)}</span>
            </div>
          </div>
        </section>
      </div>

      <div className="p-4 pt-3 border-t border-outline-variant flex items-center gap-2">
        <Button
          variant="filled"
          className="flex-1"
          onClick={() => window.open(`/api/persons/${candidateId}`, "_blank")}
        >
          查看完整档案
        </Button>
        <IconButton icon="more_vert" variant="outlined" size={18} />
      </div>
    </Card>
  );
}
