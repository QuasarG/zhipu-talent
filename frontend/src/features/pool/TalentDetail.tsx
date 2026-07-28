import { useState } from "react";
import type { PersonDetail } from "@/lib/types";
import { api } from "@/lib/api";

interface Props {
  person: PersonDetail | null;
  personId: string | null;
  onUpdated: (id: string) => void;
}

const STATUS_OPTIONS = [
  { value: "newly_admitted", label: "新入库" },
  { value: "to_contact", label: "待联系" },
  { value: "contacted", label: "已联系" },
  { value: "interviewing", label: "面试中" },
  { value: "ongoing_follow", label: "持续关注" },
  { value: "closed", label: "已结束" },
];

export default function TalentDetail({ person, personId, onUpdated }: Props) {
  const [engagement, setEngagement] = useState("");
  const [saving, setSaving] = useState(false);

  if (!person) {
    return (
      <div className="overflow-y-auto p-3">
        <div className="flex flex-col items-center justify-center h-full text-center gap-2 text-ink-secondary">
          <p className="text-sm">从左侧选择一位人才</p>
          <p className="text-xs text-ink-muted">查看统一人才档案</p>
        </div>
      </div>
    );
  }

  const evaluations = person.evaluations || [];
  const latest = evaluations[0];
  const reputation = person.reputation_reports || [];
  const initials = (person.name || "?").charAt(0);
  const candidateId = personId || "";

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

  return (
    <div className="overflow-y-auto p-3">
      <div className="w-12 h-12 rounded-full bg-teal text-white flex items-center justify-center text-xl font-semibold mb-2">
        {initials}
      </div>
      <div className="text-base font-semibold">{person.name}</div>
      <div className="text-xs text-ink-secondary mb-3">
        {person.org || "—"} · {person.direction || "—"}
      </div>

      {/* HR 跟进状态 */}
      <div className="mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-2">HR 跟进状态</h3>
        <div className="flex items-center gap-2">
          <select
            value={engagement}
            onChange={(e) => setEngagement(e.target.value)}
            className="px-2 py-1 rounded-[6px] border border-ink/15 text-xs bg-white"
          >
            <option value="">选择状态…</option>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            onClick={saveEngagement}
            disabled={!engagement || saving}
            className="text-xs px-3 py-1 rounded-full bg-teal-soft text-teal disabled:opacity-40"
          >
            保存
          </button>
        </div>
      </div>

      {/* 能力概览 */}
      {latest && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-2">能力概览</h3>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-bold">{latest.overall_score ?? "—"}</span>
            <span className="text-[10px] text-ink-muted">能力描述，不代表录取结论</span>
          </div>
          {latest.recommended_tracks?.length > 0 && (
            <p className="text-xs text-ink-secondary mt-1">
              推荐：{latest.recommended_tracks.map((t) => t.track || t.name || "").join(", ")}
            </p>
          )}
        </div>
      )}

      {/* 研究组匹配 */}
      {latest && (
        <div className="mb-4 p-3 rounded-[10px] bg-surface-mist border border-ink/10">
          <h3 className="text-xs font-medium mb-1">研究组匹配</h3>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
            尚未配置研究组要求
          </span>
        </div>
      )}

      {/* 评估历史 */}
      {evaluations.length > 1 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-2">
            评估历史 ({evaluations.length})
          </h3>
          {evaluations.map((e, i) => (
            <div key={i} className="text-xs py-1 text-ink-secondary">
              {e.overall_score ?? "—"} 分 · {e.one_liner}
            </div>
          ))}
        </div>
      )}

      {/* 舆情报告 */}
      {reputation.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-2">舆情报告</h3>
          {reputation.map((r, i) => (
            <div key={i} className="text-xs py-1">
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
                {r.review_status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
