import { useEffect, useRef, useState } from "react";

interface Props {
  /** 要逐 token 流式显式的完整文本 */
  text: string;
  /** 是否启用流式效果（导入预览态启用，日常查看禁用） */
  enabled?: boolean;
  className?: string;
}

/**
 * 逐 token 流式显式：按词/标点逐步跳出，间隔回真实 LLM token 流的抖动感，
 * 而非匀速逐字。enabled=false 时直接显示全文。
 */
export default function TypewriterText({ text, enabled = true, className }: Props) {
  const [count, setCount] = useState(enabled ? 0 : text.length);
  const [done, setDone] = useState(!enabled);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 切换文本/启用态时重置
  useEffect(() => {
    if (!enabled) { setCount(text.length); setDone(true); return; }
    setCount(0); setDone(false);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [text, enabled]);

  useEffect(() => {
    if (!enabled || done) return;
    if (count >= text.length) { setDone(true); return; }

    // 按中文逐字、英文按词/空格为块推进，更贴合 token 流
    const rest = text.slice(count);
    let step = 1;
    const ch = rest[0];
    // 英文单词：一次性蹦出整个词（下一个非字母/数字字符为止）
    if (/[A-Za-z0-9]/.test(ch)) {
      const m = rest.match(/^[A-Za-z0-9]+/);
      if (m) step = m[0].length;
    }
    // 数字+单位/标点紧跟也连跳，避免逐字碎裂
    const nextCh = rest[step] || "";
    if (/[.,;:!?)\]}/，。；：！？、）】》"'`]/.test(nextCh)) step += 1;

    // 抖动间隔：词间停顿略长（模拟思考），句末停顿更明显，整体 25-120ms
    const isPunct = /[。.!！?？\n]/.test(ch);
    const gap = isPunct ? 90 + Math.random() * 90 : 18 + Math.random() * 45;

    timer.current = setTimeout(() => setCount((c) => c + step), gap);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [count, text, enabled, done]);

  return (
    <span className={className}>
      {text.slice(0, count)}
      {enabled && !done && <span className="tw-cursor" />}
    </span>
  );
}
