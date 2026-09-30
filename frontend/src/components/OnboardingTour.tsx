import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "@/lib/i18n";

// v3：师生图谱升级为独立页面（/scholarship/graph，导航独立入口），
// 奖学金页视图收敛为三个，引导整体重写；存储键随之换版，两角色都重新看一遍。
// 按角色分键存储：管理员与评审账户各自记忆"已看过"，互不影响。
const STORAGE_KEY_PREFIX = "zhipu_talent.onboarding.v3";

const storageKey = (role: string) => `${STORAGE_KEY_PREFIX}.${role}`;

/** 引导步骤定义：selector 定位高亮元素，route 切换路由，title/desc 展示文案 */
interface TourStep {
  selector: string;
  route?: string;
  title: string;
  desc: string;
  placement?: "right" | "bottom" | "top" | "left";
}

/** 管理员引导：各模块按当前 UI 逐一介绍 */
const ADMIN_STEPS: TourStep[] = [
  {
    selector: '[data-tour="nav"]',
    title: "导航栏",
    desc: "平台共七个模块：人才库、人才评估、人才问答、JD 池、奖学金、师生图谱和设置。下面逐一介绍。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-pool"]',
    route: "/",
    title: "人才库",
    desc: "统一档案、来源追踪与关系发现。导入的简历评估入库后都在这里，可切换图谱/列表视图，右侧详情栏查看完整档案。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-talent-evaluation"]',
    route: "/talent-evaluation/admission",
    title: "人才评估",
    desc: "面试准入工作台：左侧是候选人文件夹，选中后展开岗位子项，查看该候选人×岗位配对的准入报告与 Agent 运行轨迹。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-chat"]',
    route: "/chat",
    title: "人才问答",
    desc: "输入姓名或问题，Agent 库内优先检索、必要时联网查论文与舆情，生成带引用的调查报告。",
    placement: "right",
  },
  {
    selector: "[data-chat-input]",
    route: "/chat",
    title: "问答输入框",
    desc: "在这里输入问题。Agent 会预告每一步操作，工具调用卡片实时弹出，回答带引用角标。",
    placement: "top",
  },
  {
    selector: '[data-tour="help-btn"]',
    route: "/chat",
    title: "使用说明",
    desc: "问答页左侧栏底部的「使用说明」：查看 Agent 工作原理、工具列表和权限说明。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-jd"]',
    route: "/jd-pool",
    title: "JD 池",
    desc: "JD 入池即生成岗位评估卡；是否参与评估由每次批次显式选择。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-scholarship"]',
    route: "/scholarship",
    title: "奖学金初筛",
    desc: "申请资料工作台：飞书问卷自动同步，左侧申请人列表，右侧「申请资料 / 材料预览 / 评估与核验」三个视图——评分圆环、论文核验（带 DOI 与原文直达）、亮点与异常点都在评估视图里。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-scholarship-graph"]',
    route: "/scholarship/graph",
    title: "师生图谱",
    desc: "学校-导师-学生关系网络：导师固定从属一所学校（逐封核验过推荐信原件），学生挂在就读学校；跨校推荐直接体现为跨越学校簇的师生连线。支持搜索与按类型筛选，点击节点查看关联。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-settings"]',
    route: "/settings",
    title: "设置",
    desc: "查看后端服务运行状态，配置外部服务 API Key（只可修改，不可读取已保存的值）。",
    placement: "right",
  },
  {
    selector: "",
    title: "开始使用",
    desc: "引导结束！祝使用愉快～",
    placement: "top",
  },
];

/** 评审账户引导：奖学金（三视图）+ 师生图谱 + 设置，围绕评审流程介绍 */
const REVIEWER_STEPS: TourStep[] = [
  {
    selector: '[data-tour="nav"]',
    title: "导航栏",
    desc: "评审账户的入口：奖学金、师生图谱和设置。下面逐一介绍。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-scholarship"]',
    route: "/scholarship",
    title: "奖学金初筛",
    desc: "评审主工作台：左侧是申请人列表，支持搜索与状态筛选；右侧查看选中申请人的详情。飞书问卷提交后会自动出现在列表里。",
    placement: "right",
  },
  {
    selector: '[data-tour="scholarship-views"]',
    route: "/scholarship",
    title: "三种视图",
    desc: "「申请资料」看档案与评分概览，「材料预览」阅读论文等原件，「评估与核验」查看评分圆环、论文核验（DOI 与原文直达）、亮点/异常点与 Agent 运行轨迹——异常点仅是 Agent 提出的疑点，判定由人工完成。",
    placement: "bottom",
  },
  {
    selector: '[data-tour="nav-scholarship-graph"]',
    route: "/scholarship/graph",
    title: "师生图谱",
    desc: "学校-导师-学生关系网络：导师固定从属一所学校，学生挂在本校；推荐人来自外校时，连线会跨越学校簇，一眼识别跨校推荐。支持搜索、按类型筛选，点击节点查看关联。",
    placement: "right",
  },
  {
    selector: '[data-tour="scholarship-list"]',
    route: "/scholarship",
    title: "申请人列表",
    desc: "按状态筛选要处理的申请：待评估 → 评分 → 定稿。点击任意申请人，在右侧开始评审。",
    placement: "right",
  },
  {
    selector: '[data-tour="nav-settings"]',
    route: "/settings",
    title: "设置",
    desc: "切换界面主题、查看各服务运行状态。",
    placement: "right",
  },
  {
    selector: "",
    title: "开始使用",
    desc: "引导结束！祝评审顺利～",
    placement: "top",
  },
];

export function hasSeenOnboarding(role: string): boolean {
  try {
    return localStorage.getItem(storageKey(role)) === "done";
  } catch {
    return false;
  }
}

export function resetOnboarding(role: string): void {
  try {
    localStorage.removeItem(storageKey(role));
  } catch {
    /* ignore */
  }
}

export default function OnboardingTour({ role }: { role: string }) {
  const [active, setActive] = useState(false);
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [bubbleVisible, setBubbleVisible] = useState(false);
  const navigate = useNavigate();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { t } = useI18n();
  const steps = useMemo(() => (role === "reviewer" ? REVIEWER_STEPS : ADMIN_STEPS), [role]);

  const finish = useCallback(() => {
    setActive(false);
    setStep(0);
    setBubbleVisible(false);
    try {
      localStorage.setItem(storageKey(role), "done");
    } catch {
      /* ignore */
    }
  }, [role]);

  // 首次访问（本角色）自动启动
  useEffect(() => {
    if (!hasSeenOnboarding(role)) {
      timerRef.current = setTimeout(() => setActive(true), 600);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [role]);

  // 步骤变化时：切路由 + 先隐藏气泡 → 延迟定位高亮框 → 气泡淡入
  useEffect(() => {
    if (!active) return;
    const s = steps[step];

    // 1. 立即隐藏气泡（让高亮框先移动）
    setBubbleVisible(false);

    // 2. 切路由
    if (s.route) {
      navigate(s.route);
    }

    // 3. 等目标真实挂载后再定位。路由懒加载和接口回填速度不同，固定延时会
    // 把引导气泡定位到短暂空态；最多等待 4 秒，再安全降级为居中说明。
    const startedAt = Date.now();
    const locateTarget = () => {
      if (!s.selector) {
        setRect(null);
        setBubbleVisible(true);
        return;
      }
      const el = document.querySelector(s.selector);
      if (el) {
        setRect(el.getBoundingClientRect());
        timerRef.current = setTimeout(() => setBubbleVisible(true), 350);
        return;
      }
      if (Date.now() - startedAt < 4000) {
        timerRef.current = setTimeout(locateTarget, 100);
      } else {
        setRect(null);
        setBubbleVisible(true);
      }
    };
    timerRef.current = setTimeout(locateTarget, 100);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [step, active, navigate, steps]);

  // 窗口大小变化时重新定位
  useEffect(() => {
    if (!active) return;
    const handler = () => {
      const s = steps[step];
      if (!s.selector) return;
      const el = document.querySelector(s.selector);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, [step, active, steps]);

  if (!active) return null;

  const current = steps[step];
  const isLast = step === steps.length - 1;
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
          <span className="text-title font-bold text-on-surface">{t(current.title)}</span>
          <span className="ml-auto text-label text-on-surface-variant">
            {step + 1} / {steps.length}
          </span>
        </div>
        <p className="text-body-sm text-on-surface-variant leading-relaxed">{t(current.desc)}</p>
        <div className="flex items-center gap-2 mt-1">
          {step > 0 && (
            <button
              onClick={() => setStep((s) => s - 1)}
              className="state-layer px-3 py-1.5 rounded-full text-body-sm text-on-surface-variant hover:bg-surface-low cursor-pointer"
            >
              {t("上一步")}
            </button>
          )}
          <button
            onClick={finish}
            className="state-layer ml-auto px-3 py-1.5 rounded-full text-body-sm text-on-surface-variant hover:bg-surface-low cursor-pointer"
          >
            {t("跳过")}
          </button>
          <button
            onClick={() => (isLast ? finish() : setStep((s) => s + 1))}
            className="state-layer px-4 py-1.5 rounded-full text-body-sm font-semibold bg-primary text-on-primary hover:opacity-90 cursor-pointer"
          >
            {isLast ? t("完成") : t("下一步")}
          </button>
        </div>
      </div>
    </>
  );
}
