import { useState, useRef, useEffect } from "react";
import { api, parseSSE } from "@/lib/api";
import type { AgentEvent } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import GlassPanel from "@/components/glass/GlassPanel";
import { Send, Plus, CheckCircle, AlertTriangle, Clock } from "lucide-react";
import { cn } from "@/lib/cn";

interface Message {
  role: "user" | "agent";
  text: string;
  citations?: { source: string; verification_status: string }[];
}

interface TraceNode {
  name: string;
  status: "ok" | "running" | "warning";
  meta: string;
}

export default function KnowledgeAgent() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [traces, setTraces] = useState<TraceNode[]>([]);
  const [tab, setTab] = useState<"trace" | "citations">("trace");
  const convRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    convRef.current?.scrollTo(0, convRef.current.scrollHeight);
  }, [messages]);

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || asking) return;
    setAsking(true);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: prompt }]);
    setTraces([]);

    try {
      const resp = await api.knowledge.askSSE(prompt);
      if (!resp.ok) throw new Error("请求失败");
      for await (const event of parseSSE(resp)) {
        const e = event as AgentEvent;
        handleEvent(e);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: `⚠️ ${err instanceof Error ? err.message : "错误"}` },
      ]);
    } finally {
      setAsking(false);
    }
  };

  const handleEvent = (e: AgentEvent) => {
    switch (e.type) {
      case "intent": {
        const intent = e.payload.intent as string;
        const labels: Record<string, string> = {
          pool_query: "库内查询", known_person: "已知人物调查",
          talent_discovery: "人才发现（不支持）", unsupported: "不支持",
        };
        setTraces((p) => [...p, { name: "意图识别", status: "ok", meta: labels[intent] || intent }]);
        break;
      }
      case "local_facts":
        setTraces((p) => [
          ...p,
          {
            name: "MySQL 人才库检索",
            status: "ok",
            meta: `命中 ${e.payload.count} 条${e.payload.sufficient ? " · 库内足够" : ""}`,
          },
        ]);
        break;
      case "tool_plan":
        setTraces((p) => [
          ...p,
          {
            name: "工具规划",
            status: "ok",
            meta: (e.payload.tools as string[])?.[0] === "none" ? "库内足够" : `调用 ${(e.payload.tools as string[])?.join(", ")}`,
          },
        ]);
        break;
      case "external_fact":
        setTraces((p) => [...p, { name: "外部调查", status: "ok", meta: `新增 ${e.payload.count} 条事实` }]);
        break;
      case "tool_failure":
        setTraces((p) => [...p, { name: "部分链路失败", status: "warning", meta: `${(e.payload.failed_tools as string[])?.join(", ")} 不可用` }]);
        break;
      case "answer":
        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            text: e.payload.answer as string,
            citations: e.payload.citations as Message["citations"],
          },
        ]);
        break;
      case "clarification":
        setMessages((prev) => [...prev, { role: "agent", text: e.payload.message as string }]);
        break;
    }
  };

  const renderAnswer = (text: string) => {
    const lines = text.split("\n");
    const elements: React.ReactNode[] = [];
    let listItems: string[] = [];
    lines.forEach((line, i) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("- ") || trimmed.startsWith("• ")) {
        listItems.push(trimmed.slice(2));
      } else {
        if (listItems.length) {
          elements.push(<ul key={`ul-${i}`} className="my-1 ml-4">{listItems.map((li, j) => <li key={j} className="text-sm mb-1">{li}</li>)}</ul>);
          listItems = [];
        }
        if (trimmed) elements.push(<p key={i} className="text-sm mb-2 leading-relaxed">{trimmed}</p>);
      }
    });
    if (listItems.length) elements.push(<ul className="my-1 ml-4">{listItems.map((li, j) => <li key={j} className="text-sm mb-1">{li}</li>)}</ul>);
    return elements;
  };

  const traceIcon = (status: string) =>
    status === "ok" ? <CheckCircle size={12} className="text-teal" /> :
    status === "warning" ? <AlertTriangle size={12} className="text-amber-glow" /> :
    <Clock size={12} className="text-blue" />;

  return (
    <div>
      <PageToolbar
        title="人才知识"
        subtitle="库内优先 · 必要时联网调查"
        right={<span className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">业务操作只读</span>}
      />

      <div className="grid grid-cols-[280px_1fr_340px] gap-4 h-[calc(100vh-56px-60px-80px)] min-h-[400px]">
        {/* 左栏 */}
        <div className="flex flex-col gap-3 min-h-0">
          <GlassPanel className="flex items-center gap-2 px-3 py-2 rounded-[10px]">
            <Plus size={16} className="text-teal shrink-0" />
            <span className="text-sm text-teal">新建调查</span>
          </GlassPanel>
          <div className="flex-1 overflow-y-auto">
            <div className="px-3 py-2 rounded-[10px] bg-teal-soft text-sm">新对话<span className="text-xs text-ink-secondary block">刚刚</span></div>
          </div>
        </div>

        {/* 中栏：对话 */}
        <div ref={convRef} className="overflow-y-auto flex flex-col gap-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2 text-ink-secondary">
              <p className="text-base">询问人才、比较经历，或调查一个明确人物</p>
              <p className="text-xs text-ink-muted">可主动调用外部工具；新事实将以待核验状态保存</p>
            </div>
          ) : (
            messages.map((msg, i) =>
              msg.role === "user" ? (
                <div key={i} className="self-end max-w-[80%] px-4 py-3 rounded-[14px] bg-teal-soft text-sm leading-relaxed">
                  {msg.text}
                </div>
              ) : (
                <div key={i} className="self-start max-w-[92%]">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-full bg-teal flex items-center justify-center">
                      <CheckCircle size={14} className="text-white" />
                    </div>
                    <span className="text-sm font-medium">人才知识 Agent</span>
                  </div>
                  <div className="leading-relaxed">{renderAnswer(msg.text)}</div>
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      <span className="text-xs text-ink-secondary">引用：</span>
                      {msg.citations.map((c, j) => (
                        <span
                          key={j}
                          className={cn(
                            "text-[10px] px-2 py-0.5 rounded-full",
                            c.verification_status === "confirmed" ? "bg-teal-soft text-teal" :
                            c.verification_status === "conflict" ? "bg-coral-soft text-coral" :
                            "bg-amber-soft text-amber-glow"
                          )}
                        >
                          [{j + 1}] {c.source}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )
            )
          )}
        </div>

        {/* 右栏：Trace */}
        <div className="flex flex-col gap-3 min-h-0">
          <div className="flex gap-1 p-1 rounded-[10px] bg-white/35 shrink-0">
            {(["trace", "citations"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "flex-1 text-center text-xs px-2 py-1 rounded-full transition-colors",
                  tab === t ? "bg-teal-soft text-teal" : "text-ink-secondary"
                )}
              >
                {t === "trace" ? "Agent Trace" : "引用"}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto">
            {traces.length === 0 ? (
              <div className="text-center py-6 text-sm text-ink-secondary">执行链将在提问后显示</div>
            ) : (
              traces.map((node, i) => (
                <div key={i} className="flex items-start gap-2 py-2 border-b border-ink/10 last:border-0">
                  <div className="shrink-0 mt-0.5">{traceIcon(node.status)}</div>
                  <div>
                    <div className="text-sm font-medium">{node.name}</div>
                    <div className="text-xs text-ink-secondary">{node.meta}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 底部输入条 */}
      <div className="fixed bottom-4 left-[calc(72px+20px+16px)] right-[calc(340px+32px)] z-50">
        <GlassPanel variant="strong" className="flex items-center gap-2 px-3 py-2 rounded-[20px]">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            placeholder="询问人才、比较经历，或调查一个明确人物……"
            className="flex-1 border-none bg-transparent text-sm outline-none placeholder:text-ink-muted"
          />
          <button
            onClick={send}
            disabled={asking || !input.trim()}
            className="w-9 h-9 rounded-full bg-teal text-white flex items-center justify-center disabled:opacity-40 hover:bg-teal-light transition-colors shrink-0"
          >
            <Send size={18} />
          </button>
        </GlassPanel>
        <p className="text-center text-[10px] mt-1 text-ink-muted">可主动调用外部工具；新事实将以待核验状态保存</p>
      </div>
    </div>
  );
}
