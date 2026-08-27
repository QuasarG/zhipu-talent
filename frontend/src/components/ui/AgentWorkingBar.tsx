import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useI18n } from "@/lib/i18n";

const BAR_COUNT = 72;
const WAVE_SHAPE = [5, 8, 12, 17, 11, 20, 15, 9, 14, 22, 18, 10];

type WaveStyle = CSSProperties & {
  "--wave-height": string;
  "--wave-delay": string;
  "--wave-duration": string;
};

/** 当前 Agent 仍在工作：始终跟随在消息链底部的横向音纹状态条。 */
export default function AgentWorkingBar() {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  const intersectingRef = useRef(true);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const updateVisibility = () => setVisible(intersectingRef.current && !document.hidden);
    const observer = new IntersectionObserver(
      ([entry]) => {
        intersectingRef.current = entry.isIntersecting;
        updateVisibility();
      },
      { threshold: 0.01 }
    );
    observer.observe(root);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);

  return (
    <div
      ref={rootRef}
      className="agent-working-bar mt-4"
      role="status"
      aria-live="polite"
      aria-label={t("AI 正在工作")}
    >
      <div className="agent-working-wave" data-playing={visible ? "true" : "false"} aria-hidden="true">
        {Array.from({ length: BAR_COUNT }, (_, index) => {
          const height = WAVE_SHAPE[index % WAVE_SHAPE.length];
          const style: WaveStyle = {
            "--wave-height": `${height}px`,
            "--wave-delay": `${-(index % 18) * 58}ms`,
            "--wave-duration": `${760 + (index % 7) * 55}ms`,
          };
          return <span key={index} style={style} />;
        })}
      </div>
      <span className="agent-working-label">{t("AI 正在工作")}</span>
    </div>
  );
}
