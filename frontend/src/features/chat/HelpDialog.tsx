import Card from "@/components/ui/Card";
import { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";

interface Props {
  onClose: () => void;
}

const SECTIONS: { icon: string; title: string; body: string[] }[] = [
  {
    icon: "psychology",
    title: "它是什么",
    body: [
      "面向人才库的问答 Agent：优先查库内（人才档案、评估报告、简历知识库），库内不足时自动联网调查（学者检索、论文、舆情）。",
      "事实性回答带来源角标（如 c1），点击可查看出处；外部新信息以「待核验」状态保存，不会污染已确认档案。",
      "它只基于工具查到的事实回答，查不到会明说「未查到」，不会硬编。",
    ],
  },
  {
    icon: "cycle",
    title: "Agent 如何工作",
    body: [
      "循环：理解问题 → 用一句话预告并调用工具（文字流中间弹出工具卡片）→ 阅读结果 → 继续调用或作答，最多 8 轮。",
      "工具卡片完成后自动折叠成一行摘要，点击可展开查看调用细节与原始返回。",
      "需要你来决定时会暂停并弹出卡片：人物多义选择 / 意图澄清 / 新人物入库确认 / 事实冲突裁定，你选定后它接着干。",
      "权限：只读为主；写入只有「加入人才库」和「事实裁定」两种，且必须经你确认才执行。",
    ],
  },
  {
    icon: "build",
    title: "可以调用的工具",
    body: [
      "库内：筛选人物 search_persons · 语义检索知识库 search_knowledge · 简历画像 get_person_profile · 评估报告 get_person_evaluation · 多版本简历对比 get_resume_versions · 统计排名 aggregate_persons。",
      "外部：AMiner 学者（引用数/单位）· AMiner 论文 · DBLP 发文核验 · 舆情与公开动态 search_web · GitHub 开源项目核验 · OpenAlex 精确被引（仅兜底）。",
    ],
  },
  {
    icon: "lightbulb",
    title: "常见用法（可直接抄）",
    body: [
      "「我们人才库里现在有哪些人？」",
      "「对比下 A 和 B 的实习经历和评估结果」",
      "「库里谁的顶会一作论文最多？按引用量排序」",
      "「对比张三两份简历，他这半年新增了哪些技能？」",
      "「帮我调查一下学者 XXX 的学术背景和最近动态」→ 调查完可一键加入人才库",
      "「检索一下 XXX 近三年有没有学术不端或负面舆情」",
      "「李四简历上说主导了某开源项目，Star 多少？最近三个月有提交吗？」",
    ],
  },
  {
    icon: "warning",
    title: "注意事项",
    body: [
      "舆情类信息请看角标状态：已确认 / 待核验 / 冲突，待核验内容建议人工复核后再采信。",
      "外部调查会串行调用多个数据源，回答可能需要 1-2 分钟；工具卡片在动就表示它还在干活。",
      "会话保存在本地数据库，刷新、换页面都不会丢；侧栏可重命名、删除（双击确认）。",
    ],
  },
];

/** 人才问答使用说明浮窗 */
export default function HelpDialog({ onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30 p-6" onClick={onClose}>
      <Card
        variant="elevated"
        className="w-full max-w-3xl max-h-[85vh] flex flex-col p-6 gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between shrink-0">
          <div>
            <p className="text-headline">人才问答 · 使用说明</p>
            <p className="text-body-sm text-on-surface-variant mt-0.5">库内优先 · 必要时联网调查 · 事实可溯源</p>
          </div>
          <IconButton icon="close" onClick={onClose} title="关闭" />
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-5 pr-1">
          {SECTIONS.map((sec) => (
            <section key={sec.title}>
              <p className="text-title flex items-center gap-2 text-on-surface">
                <Icon name={sec.icon} size={20} className="text-primary" />
                {sec.title}
              </p>
              <ul className="mt-2 flex flex-col gap-1.5">
                {sec.body.map((line) => (
                  <li key={line} className="text-body-sm text-on-surface-variant leading-relaxed pl-4 relative before:content-['•'] before:absolute before:left-0 before:text-primary">
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </Card>
    </div>
  );
}
