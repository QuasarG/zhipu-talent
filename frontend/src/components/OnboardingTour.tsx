import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";

const STORAGE_KEY = "zhipu_talent.onboarding.v1";

/** 引导步骤定义：selector 定位高亮元素，route 切换路由，title/desc 展示文案 */
interface TourStep {
  selector: string;
  route?: string;
  title: string;
  desc: string;
  placement?: "right" | "bottom" | "top" | "left";
}

const STEPS: TourStep[] = [
  {
    selector: '[data-tour="nav"]',
    title: "导航栏",
    desc: "这是主要功能入口，包含人才问答、简历评估、人才库和设置。下面逐一介绍每个模块。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-chat"]',
    route: "/",
    title: "人才问答",
    desc: "输入姓名即可让 AI Agent 自动检索人才库、查论文、查舆情，生成调查报告。上下文取决于调用的模型（当前是 DeepSeek-V4-Flash[1M]）。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-resume"]',
    route: "/resume-evaluate",
    title: "简历评估",
    desc: "导入 PDF/图片简历，自动结构化解析、论文核验、AI 多维度评估打分。左侧导入，中间看简历，右侧看评估进度和结果。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-pool"]',
    route: "/talent-pool",
    title: "人才库",
    desc: "所有评估入库的人才都在这里。关系图谱可视化人才网络，列表视图查看评分排序，右侧详情栏看完整档案和简历版本对比。",
    placement: "right",
  },
  {
    selector: "[data-chat-input]",
    route: "/",
    title: "问答输入框",
    desc: "回到问答页——在这里输入问题。Agent 会预告每一步操作，工具调用卡片实时弹出，回答带引用角标。",
    placement: "top",
  },
  {
    selector: '[data-tour="help-btn"]',
    route: "/",
    title: "使用说明",
    desc: "随时点击查看 Agent 工作原理、工具列表和权限说明。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-settings"]',
    route: "/settings",
    title: "设置",
    desc: "在这里可以查看后端服务的运行状态，以及配置相关外部服务的 API Key（只可修改，不可读取已保存的值）。首次使用前请确保各服务 Key 已配置。",
    placement: "right",
  },
  {
    selector: "",
    title: "开始使用",
    desc: "引导结束！有问题随时点左下角「使用说明」。祝使用愉快～",
    placement: "top",
  },
];

export function hasSeenOnboarding(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "done";
  } catch {
    return false;
  }
}

export function resetOnboarding(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export default function OnboardingTour() {
  const [active, setActive] = useState(false);
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [bubbleVisible, setBubbleVisible] = useState(false);
  const navigate = useNavigate();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const finish = useCallback(() => {
    setActive(false);
    setStep(0);
    setBubbleVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, "done");
    } catch {
      /* ignore */
    }
  }, []);

  // 首次访问自动启动
  useEffect(() => {
    if (!hasSeenOnboarding()) {
      timerRef.current = setTimeout(() => setActive(true), 600);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // 步骤变化时：切路由 + 先隐藏气泡 → 延迟定位高亮框 → 气泡淡入
  useEffect(() => {
    if (!active) return;
    const s = STEPS[step];

    // 1. 立即隐藏气泡（让高亮框先移动）
    setBubbleVisible(false);

    // 2. 切路由
    if (s.route) {
      navigate(s.route);
    }

    // 3. 延迟定位高亮框（等路由渲染完）
    timerRef.current = setTimeout(() => {
      if (!s.selector) {
        setRect(null);
        setBubbleVisible(true);
        return;
      }
      const el = document.querySelector(s.selector);
      if (el) {
        setRect(el.getBoundingClientRect());
      } else {
        setRect(null);
      }
      // 4. 再延迟一下让高亮框 transition 完成，然后气泡淡入
      timerRef.current = setTimeout(() => setBubbleVisible(true), 350);
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [step, active, navigate]);

  // 窗口大小变化时重新定位
  useEffect(() => {
    if (!active) return;
    const handler = () => {
      const s = STEPS[step];
      if (!s.selector) return;
      const el = document.querySelector(s.selector);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, [step, active]);

  if (!active) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;
  const hasTarget = rect !== null;

  // 气泡定位
  const bubbleStyle: React.CSSProperties = {};
  if (hasTarget && rect) {
    const placement = current.placement || "right";
    const spacing = 16;
    switch (placement) {
      case "right":
        bubbleStyle.left = rect.right + spacing;
        bubbleStyle.top = Math.max(16, Math.min(rect.top, window.innerHeight - 280));
        break;
      case "left":
        bubbleStyle.right = window.innerWidth - rect.left + spacing;
        bubbleStyle.top = Math.max(16, Math.min(rect.top, window.innerHeight - 280));
        break;
      case "bottom":
        bubbleStyle.left = Math.max(16, Math.min(rect.left, window.innerWidth - 380));
        bubbleStyle.top = rect.bottom + spacing;
        break;
      case "top":
        bubbleStyle.left = Math.max(16, Math.min(rect.left, window.innerWidth - 380));
        bubbleStyle.bottom = window.innerHeight - rect.top + spacing;
        break;
    }
  } else {
    // 无高亮目标（结束步骤）：居中
    bubbleStyle.left = "50%";
    bubbleStyle.top = "50%";
    bubbleStyle.transform = "translate(-50%, -50%)";
  }

  return (
    <>
      {/* 遮罩：有高亮时用 box-shadow 镂空（平滑过渡），无高亮时纯半透明 */}
      {hasTarget && rect ? (
        <div
          className="fixed z-[300] pointer-events-none"
          style={{
            left: rect.left - 4,
            top: rect.top - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            borderRadius: 12,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
            border: "2px solid var(--color-primary)",
            transition: "all 350ms cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />
      ) : (
        <div className="fixed inset-0 z-[300] bg-black/55 transition-opacity duration-300" />
      )}

      {/* 解释气泡：高亮框移动到位后才淡入 */}
      <div
        className="fixed z-[301] w-[340px] bg-surface rounded-lg shadow-2xl p-5 flex flex-col gap-3 transition-all duration-300"
        style={{
          ...bubbleStyle,
          opacity: bubbleVisible ? 1 : 0,
          transform: bubbleVisible
            ? (hasTarget ? "translateY(0)" : "translate(-50%, -50%)")
            : (hasTarget ? "translateY(8px)" : "translate(-50%, calc(-50% + 8px))"),
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-title font-bold text-on-surface">{current.title}</span>
          <span className="ml-auto text-label text-on-surface-variant">
            {step + 1} / {STEPS.length}
          </span>
        </div>
        <p className="text-body-sm text-on-surface-variant leading-relaxed">{current.desc}</p>
        <div className="flex items-center gap-2 mt-1">
          {step > 0 && (
            <button
              onClick={() => setStep((s) => s - 1)}
              className="state-layer px-3 py-1.5 rounded-full text-body-sm text-on-surface-variant hover:bg-surface-low cursor-pointer"
            >
              上一步
            </button>
          )}
          <button
            onClick={finish}
            className="state-layer ml-auto px-3 py-1.5 rounded-full text-body-sm text-on-surface-variant hover:bg-surface-low cursor-pointer"
          >
            跳过
          </button>
          <button
            onClick={() => (isLast ? finish() : setStep((s) => s + 1))}
            className="state-layer px-4 py-1.5 rounded-full text-body-sm font-semibold bg-primary text-on-primary hover:opacity-90 cursor-pointer"
          >
            {isLast ? "完成" : "下一步"}
          </button>
        </div>
      </div>
    </>
  );
}
