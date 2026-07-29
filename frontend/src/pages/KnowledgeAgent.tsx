import { useState, useRef, useEffect } from "react";
import { api, parseSSE } from "@/lib/api";
import type { AgentEvent } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Icon from "@/components/ui/Icon";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import Tabs from "@/components/ui/Tabs";
import SearchField from "@/components/ui/SearchField";
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

const citationTone = (status: string): { tone: "success" | "error" | "warning"; label: string } =>
  status === "confirmed" ? { tone: "success", label: "已确认" }
  : status === "conflict" ? { tone: "error", label: "冲突" }
  : { tone: "warning", label: "待核验" };

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

  const resetConversation = () => {
    setMessages([]);
    setTraces([]);
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
          elements.push(<ul key={`ul-${i}`} className="my-1 ml-4 list-disc">{listItems.map((li, j) => <li key={j} className="text-body mb-1">{li}</li>)}</ul>);
          listItems = [];
        }
        if (trimmed) elements.push(<p key={i} className="text-body mb-2">{trimmed}</p>);
      }
    });
    if (listItems.length) elements.push(<ul className="my-1 ml-4 list-disc">{listItems.map((li, j) => <li key={j} className="text-body mb-1">{li}</li>)}</ul>);
    return elements;
  };

  const traceStatusIcon = (status: TraceNode["status"]) =>
    status === "ok" ? <Icon name="check_circle" size={18} fill className="text-success" /> :
    status === "warning" ? <Icon name="warning" size={18} fill className="text-warning" /> :
    <LoadingIndicator size={18} color="text-primary" />;

  const traceStatusLabel = (status: TraceNode["status"]) =>
    status === "ok" ? <span className="text-label text-success">完成</span> :
    status === "warning" ? <span className="text-label text-warning">警告</span> :
    <span className="text-label text-primary">进行中</span>;

  const allCitations = messages.flatMap((m) => m.citations ?? []);
  const pendingFacts = allCitations.filter((c) => c.verification_status !== "confirmed");

  return (
    <div className="flex flex-col h-[calc(100vh-24px)]">
      <PageToolbar
        title="人才知识"
        subtitle="库内优先 · 必要时联网调查"
        center={
          <span className="inline-flex items-center gap-2 h-10 px-4 rounded-full bg-surface-high text-on-surface-variant text-body-sm">
            <Icon name="person" size={18} />
            未选择人物
            <Icon name="expand_more" size={18} />
          </span>
        }
        right={
          <>
            <Button variant="tonal" icon="add" onClick={resetConversation}>新建对话</Button>
          </>
        }
      />

      <div className="grid grid-cols-[280px_minmax(0,1fr)_360px] gap-4 flex-1 min-h-0">
        {/* 左栏：会话 + 人物上下文 */}
        <div className="flex flex-col gap-4 min-h-0 overflow-y-auto">
          <Card variant="outlined" className="p-3 flex flex-col gap-3 shrink-0">
            <SearchField placeholder="搜索对话或人物" />
            <Button variant="filled" icon="add" className="w-full" onClick={resetConversation}>新建调查</Button>
            <div>
              <p className="text-label text-on-surface-variant px-2 py-1">最近会话</p>
              <div className="text-center py-6 text-body-sm text-on-surface-variant">还没有会话</div>
            </div>
          </Card>

          <div className="shrink-0">
            <p className="text-label text-on-surface-variant px-2 pb-1">人物上下文</p>
            <Card variant="outlined" className="p-4">
              <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
                <Icon name="person_search" size={32} className="text-on-surface-variant" />
                <p className="text-body text-on-surface">未选择人物</p>
                <p className="text-body-sm text-on-surface-variant">提问或选择一个人物后，上下文将显示在此</p>
              </div>
            </Card>
          </div>
        </div>

        {/* 中栏：对话流 + 输入条 */}
        <div className="flex flex-col gap-4 min-h-0">
          <div ref={convRef} className="flex-1 overflow-y-auto flex flex-col gap-4 pr-1">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center gap-3">
                <Icon name="psychology" size={40} className="text-on-surface-variant" />
                <p className="text-title">询问人才、比较经历，或调查一个明确人物</p>
                <p className="text-body-sm text-on-surface-variant">可主动调用外部工具；新事实将以待核验状态保存</p>
              </div>
            ) : (
              messages.map((msg, i) =>
                msg.role === "user" ? (
                  <div key={i} className="self-end max-w-[80%] px-4 py-3 rounded-lg bg-primary-container text-on-primary-container text-body">
                    {msg.text}
                  </div>
                ) : (
                  <Card key={i} variant="outlined" className="self-start max-w-[92%] p-4">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0">
                        Z
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-title">人才知识 Agent</p>
                        {msg.citations && msg.citations.length > 0 && (
                          <p className="text-body-sm text-on-surface-variant">引用 {msg.citations.length} 条来源</p>
                        )}
                      </div>
                      <Icon name="expand_less" size={20} className="text-on-surface-variant" />
                    </div>
                    <div>{renderAnswer(msg.text)}</div>
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 mt-2">
                        <span className="text-label text-on-surface-variant">引用：</span>
                        {msg.citations.map((c, j) => (
                          <StatusChip key={j} tone={citationTone(c.verification_status).tone}>
                            [{j + 1}] {c.source}
                          </StatusChip>
                        ))}
                      </div>
                    )}
                    <div className="flex flex-wrap gap-1 mt-3 pt-2 border-t border-outline-variant">
                      <Button
                        variant="text"
                        icon="content_copy"
                        className="h-8 px-3 text-xs"
                        onClick={() => navigator.clipboard.writeText(msg.text)}
                      >
                        复制回答
                      </Button>
                      <Button variant="text" icon="verified" className="h-8 px-3 text-xs">仅看已确认信息</Button>
                      <Button variant="text" icon="refresh" className="h-8 px-3 text-xs">重新尝试失败来源</Button>
                    </div>
                  </Card>
                )
              )
            )}
          </div>

          {/* 输入条 */}
          <div className="shrink-0">
            <div className="flex items-center gap-2 h-12 pl-4 pr-2 rounded-full bg-surface-lowest border border-outline-variant focus-within:outline-2 focus-within:outline-primary">
              <Icon name="attach_file" size={18} className="text-on-surface-variant shrink-0" />
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
                placeholder="询问人才、比较经历，或调查一个明确人物……"
                className="flex-1 min-w-0 bg-transparent border-none outline-none text-body text-on-surface placeholder:text-on-surface-variant"
              />
              <button
                type="button"
                className="state-layer inline-flex items-center gap-1 h-8 px-3 rounded-full text-label text-on-surface-variant cursor-pointer shrink-0"
              >
                工具范围：自动<Icon name="expand_more" size={16} />
              </button>
              <IconButton
                icon="send"
                variant="filled"
                onClick={send}
                disabled={asking || !input.trim()}
              />
            </div>
            <p className="text-center text-label text-on-surface-variant mt-2">可主动调用外部工具；新事实将以待核验状态保存</p>
          </div>
        </div>

        {/* 右栏：引用 / Agent Trace */}
        <Card variant="outlined" className="flex flex-col min-h-0 overflow-hidden">
          <Tabs
            items={[
              { value: "citations" as const, label: "引用", ...(allCitations.length > 0 ? { badge: allCitations.length } : {}) },
              { value: "trace" as const, label: "Agent Trace" },
            ]}
            value={tab}
            onChange={setTab}
            className="shrink-0"
          />
          <div className="flex-1 overflow-y-auto p-3 min-h-0">
            {tab === "trace" ? (
              traces.length === 0 ? (
                <div className="text-center py-6 text-body-sm text-on-surface-variant">执行链将在提问后显示</div>
              ) : (
                <>
                  <p className="text-title px-1 pb-2">LangGraph 执行链路</p>
                  {traces.map((node, i) => (
                    <div key={i} className="flex items-start gap-2.5 py-2.5 px-1 border-b border-outline-variant last:border-0">
                      <div className="shrink-0 mt-0.5">{traceStatusIcon(node.status)}</div>
                      <div className="flex-1 min-w-0">
                        <div className="text-body font-medium">{node.name}</div>
                        <div className="text-body-sm text-on-surface-variant">{node.meta}</div>
                      </div>
                      <div className="shrink-0">{traceStatusLabel(node.status)}</div>
                    </div>
                  ))}
                </>
              )
            ) : allCitations.length === 0 ? (
              <div className="text-center py-6 text-body-sm text-on-surface-variant">回答生成后显示引用来源</div>
            ) : (
              allCitations.map((c, i) => {
                const { tone, label } = citationTone(c.verification_status);
                return (
                  <div key={i} className="flex items-center gap-2.5 py-2.5 px-1 border-b border-outline-variant last:border-0">
                    <Icon name="source" size={18} className="text-on-surface-variant shrink-0" />
                    <span className="flex-1 min-w-0 text-body truncate">[{i + 1}] {c.source}</span>
                    <StatusChip tone={tone}>{label}</StatusChip>
                  </div>
                );
              })
            )}
          </div>
          {pendingFacts.length > 0 && (
            <div className="shrink-0 border-t border-outline-variant p-3 max-h-44 overflow-y-auto">
              <p className="text-title px-1 pb-2">
                本次新增事实<span className="ml-2 text-label text-on-surface-variant">{pendingFacts.length}</span>
              </p>
              {pendingFacts.map((c, i) => (
                <div key={i} className={cn("flex items-center gap-2.5 py-2 px-1", i > 0 && "border-t border-outline-variant")}>
                  <Icon name="description" size={18} className="text-on-surface-variant shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-body-sm truncate">{c.source}</div>
                  </div>
                  <StatusChip tone="warning">待核验</StatusChip>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
