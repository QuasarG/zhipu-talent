import { useState } from "react";
import type { ChatSegment } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

type ActionSegment = Extract<ChatSegment, { type: "action" }>;
type Decision = Record<string, unknown>;

interface Props {
  segment: ActionSegment;
  busy: boolean;
  onDecide: (actionId: string, decision: Decision) => void;
}

interface PersonCandidate {
  person_id: string;
  name?: string;
  org?: string;
  direction?: string;
}

const KIND_META: Record<string, { icon: string; title: string }> = {
  select_person: { icon: "person_search", title: "选择目标人物" },
  propose_add_person: { icon: "person_add", title: "新人物入库确认" },
  resolve_fact_conflict: { icon: "difference", title: "事实冲突裁定" },
  clarify: { icon: "help", title: "需要澄清" },
};

const inputClass =
  "w-full px-3 py-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

/** 决策后的定格文案 */
function decidedText(segment: ActionSegment): string {
  const d = segment.decision || {};
  switch (segment.kind) {
    case "select_person": {
      const candidates = (segment.payload.candidates as PersonCandidate[]) || [];
      const picked = candidates.find((c) => c.person_id === d.choice);
      return `已选择：${picked?.name || d.choice || "—"}`;
    }
    case "propose_add_person":
      return d.approved ? "已加入人才库" : "已跳过入库";
    case "resolve_fact_conflict":
      return d.approved ? "已采信此条事实" : "已保持现状";
    case "clarify":
      return `已回答：${d.answer || "—"}`;
    default:
      return "已处理";
  }
}

/** HITL 决策卡片：四种门控动作，提交后定格显示决策结果 */
export default function ActionCard({ segment, busy, onDecide }: Props) {
  const meta = KIND_META[segment.kind] || { icon: "bolt", title: "需要确认" };
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");
  const [answer, setAnswer] = useState("");
  const decided = segment.decision != null;
  const payload = segment.payload;
  const submit = (decision: Decision) => onDecide(segment.action_id, decision);

  const renderBody = () => {
    switch (segment.kind) {
      case "select_person": {
        const candidates = (payload.candidates as PersonCandidate[]) || [];
        return (
          <>
            <p className="text-body-sm text-on-surface-variant">命中多个同名人物，请选择要调查的目标：</p>
            <div className="flex flex-col gap-1.5 mt-2">
              {candidates.map((c) => (
                <button
                  key={c.person_id}
                  type="button"
                  disabled={decided}
                  onClick={() => setChoice(c.person_id)}
                  className={cn(
                    "state-layer flex items-center gap-3 px-3 py-2 rounded-md border text-left cursor-pointer disabled:cursor-default",
                    choice === c.person_id
                      ? "border-primary bg-primary-container/40"
                      : "border-outline-variant bg-surface-lowest"
                  )}
                >
                  <Icon
                    name={choice === c.person_id ? "radio_button_checked" : "radio_button_unchecked"}
                    size={18}
                    className={choice === c.person_id ? "text-primary" : "text-on-surface-variant"}
                  />
                  <span className="text-body font-medium text-on-surface">{c.name || "未命名"}</span>
                  <span className="text-body-sm text-on-surface-variant truncate">
                    {[c.org, c.direction].filter(Boolean).join(" · ")}
                  </span>
                </button>
              ))}
            </div>
            {!decided && (
              <div className="flex justify-end mt-3">
                <Button variant="filled" icon="check" disabled={!choice || busy} onClick={() => submit({ choice })}>
                  确认选择
                </Button>
              </div>
            )}
          </>
        );
      }
      case "propose_add_person":
        return (
          <>
            <div className="text-body-sm">
              <p className="font-medium text-on-surface">{String(payload.name || "未命名")}</p>
              <p className="text-on-surface-variant mt-0.5">
                {[payload.org, payload.direction].filter(Boolean).map(String).join(" · ") || "暂无机构与方向信息"}
              </p>
              {Boolean(payload.note) && <p className="text-on-surface-variant mt-1">{String(payload.note)}</p>}
            </div>
            {!decided && (
              <div className="flex justify-end gap-2 mt-3">
                <Button variant="outlined" disabled={busy} onClick={() => submit({ approved: false })}>
                  暂不入库
                </Button>
                <Button variant="filled" icon="person_add" disabled={busy} onClick={() => submit({ approved: true })}>
                  加入人才库
                </Button>
              </div>
            )}
          </>
        );
      case "resolve_fact_conflict": {
        const chosen = (payload.chosen_payload as Record<string, unknown>) || {};
        return (
          <>
            <p className="text-body-sm text-on-surface-variant">
              事实 #{String(payload.fact_id ?? "—")} 与现有记录冲突，Agent 建议采信以下内容：
            </p>
            <div className="mt-2 px-3 py-2 rounded-md bg-surface-low text-body-sm text-on-surface">
              {Object.entries(chosen).map(([k, v]) => (
                <p key={k}>
                  <span className="text-on-surface-variant">{k}：</span>
                  {String(v)}
                </p>
              ))}
              {Boolean(payload.note) && <p className="text-on-surface-variant mt-1">{String(payload.note)}</p>}
            </div>
            {!decided && (
              <>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="备注（可选）"
                  rows={2}
                  className={cn(inputClass, "mt-2 resize-y")}
                />
                <div className="flex justify-end gap-2 mt-2">
                  <Button variant="outlined" disabled={busy} onClick={() => submit({ approved: false, note })}>
                    保持现状
                  </Button>
                  <Button variant="filled" icon="check" disabled={busy} onClick={() => submit({ approved: true, note })}>
                    采信此条
                  </Button>
                </div>
              </>
            )}
          </>
        );
      }
      case "clarify": {
        const options = (payload.options as string[]) || [];
        return (
          <>
            <p className="text-body text-on-surface">{String(payload.question || "")}</p>
            {!decided && (
              <>
                {options.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {options.map((opt) => (
                      <Chip key={opt} selected={answer === opt} onClick={() => setAnswer(opt)}>
                        {opt}
                      </Chip>
                    ))}
                  </div>
                )}
                <div className="flex items-end gap-2 mt-2">
                  <input
                    type="text"
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="输入你的回答"
                    className={inputClass}
                  />
                  <Button
                    variant="filled"
                    icon="send"
                    className="shrink-0"
                    disabled={!answer.trim() || busy}
                    onClick={() => submit({ answer: answer.trim() })}
                  >
                    提交
                  </Button>
                </div>
              </>
            )}
          </>
        );
      }
      default:
        return <p className="text-body-sm text-on-surface-variant">未知动作类型：{segment.kind}</p>;
    }
  };

  return (
    <Card variant="outlined" className="chat-enter my-2 p-4">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon name={meta.icon} size={20} className="text-primary" />
        <p className="text-title flex-1">{meta.title}</p>
        {decided && (
          <span className="inline-flex items-center gap-1 text-label text-success">
            <Icon name="check_circle" size={16} fill />
            {decidedText(segment)}
          </span>
        )}
      </div>
      {renderBody()}
    </Card>
  );
}
