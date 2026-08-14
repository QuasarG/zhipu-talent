export default {
  "选择目标人物": "Select Target Person",
  "新人物入库确认": "Confirm New Talent Entry",
  "事实冲突裁定": "Fact Conflict Resolution",
  "需要澄清": "Clarification Needed",
  "舆情人工核验": "Manual Reputation Review",
  "需要确认": "Confirmation Needed",
  "已选择：{name}": "Selected: {name}",
  "已加入人才库": "Added to Talent Pool",
  "已跳过入库": "Skipped",
  "已采信此条事实": "Fact Accepted",
  "已保持现状": "Kept As Is",
  "已回答：{answer}": "Answered: {answer}",
  "已核验：确认 {ok} 条 / 驳回 {dismissed} 条": "Verified: {ok} confirmed / {dismissed} dismissed",
  "已处理": "Handled",
  "命中多个同名人物，请选择要调查的目标：": "Multiple people share this name. Choose the one to investigate:",
  "未命名": "Unnamed",
  "确认选择": "Confirm Selection",
  "暂无机构与方向信息": "No organization or research direction available",
  "暂不入库": "Don't Add",
  "加入人才库": "Add to Talent Pool",
  "事实 #{id} 与现有记录冲突，Agent 建议采信以下内容：":
    "Fact #{id} conflicts with existing records. The Agent suggests accepting the following:",
  "{k}：": "{k}: ",
  "备注（可选）": "Note (optional)",
  "保持现状": "Keep As Is",
  "采信此条": "Accept This Fact",
  "输入你的回答": "Type your answer",
  "提交": "Submit",
  "以下舆情 Agent 无法确证{name}，请逐条核验；被驳回的条目不会进入最终总结：":
    "The Agent could not verify the following reputation items{name}. Review each one; dismissed items are excluded from the final summary:",
  "正面": "Positive",
  "负面": "Negative",
  "（无标题）": "(Untitled)",
  "已确认": "Confirmed",
  "已驳回": "Dismissed",
  "疑点：{concern}": "Concern: {concern}",
  "查看原文": "View Source",
  "驳回": "Dismiss",
  "确认": "Confirm",
  "提交核验结果": "Submit Verification Results",
  "未知动作类型：{kind}": "Unknown action type: {kind}",
  "正在思考": "Thinking",
  "正在思考…": "Thinking…",
  "请先完成上方选择": "Complete the selection above first",
  "询问人才、比较经历，或调查一个明确人物……": "Ask about talent, compare experience, or investigate a specific person…",
  "完成上方卡片的决策后，Agent 将继续回答": "The Agent will continue once you complete the decision above",
  "库内优先 · 必要时联网调查；新事实将以待核验状态保存":
    "Talent Pool first · Web research when needed; new facts are saved as pending verification",
  "刚刚": "Just now",
  "{n} 分钟前": "{n} min ago",
  "{n} 小时前": "{n} h ago",
  "{n} 天前": "{n} d ago",
  "新建对话": "New Chat",
  "还没有会话": "No sessions yet",
  "新对话": "New Chat",
  "再点一次确认删除": "Click again to confirm deletion",
  "确认删除": "Confirm Delete",
  "重命名": "Rename",
  "删除会话": "Delete Session",
  "使用说明": "User Guide",
  "冲突": "Conflict",
  "待核验": "Pending Verification",
  "未知": "Unknown",
  "嘉宾调查": "Guest Research",
  "简历人才": "Resume Talent",
  "评级 {level}": "Level {level}",
  "机构：": "Organization: ",
  "方向：": "Direction: ",
  "分组：": "Group: ",
  "教育：": "Education: ",
  "；": "; ",
  "最新评估：": "Latest Evaluation: ",
  "{score} 分{tier}": "{score} pts{tier}",
  "人才库定位": "Locate in Talent Pool",
  "完整档案": "Full Profile",
  "来源": "Source",
  "人才问答 · 使用说明": "Talent Q&A · User Guide",
  "库内优先 · 必要时联网调查 · 事实可溯源": "Talent Pool first · Web research when needed · Traceable facts",
  "关闭": "Close",
  "它是什么": "What It Is",
  "Agent 如何工作": "How the Agent Works",
  "可以调用的工具": "Available Tools",
  "常见用法（可直接抄）": "Common Prompts (Copy & Try)",
  "注意事项": "Things to Know",
  "面向人才库的问答 Agent：优先查库内（人才档案、评估报告、简历知识库），库内不足时自动联网调查（学者检索、论文、舆情）。":
    "A Q&A agent over your Talent Pool: it searches internal data first (talent profiles, evaluation reports, resume knowledge base), then automatically reaches out to the web (scholar search, papers, reputation) when needed.",
  "事实性回答带来源角标（如 c1），点击可查看出处；外部新信息以「待核验」状态保存，不会污染已确认档案。":
    "Factual answers carry citation markers (e.g. c1); click one to view its source. New external information is saved as pending verification and never contaminates confirmed profiles.",
  "它只基于工具查到的事实回答，查不到会明说「未查到」，不会硬编。":
    "It answers only with facts found via tools and says \"not found\" when nothing turns up — no fabricated answers.",
  "循环：理解问题 → 用一句话预告并调用工具（文字流中间弹出工具卡片）→ 阅读结果 → 继续调用或作答，最多 24 轮。":
    "Loop: understand the question → announce and call a tool in one line (tool cards pop up mid-stream) → read the result → call again or answer, up to 24 rounds.",
  "工具卡片完成后自动折叠成一行摘要，点击可展开查看调用细节与原始返回。":
    "Tool cards collapse into a one-line summary when done; click to expand for call details and raw output.",
  "需要你来决定时会暂停并弹出卡片：人物多义选择 / 意图澄清 / 新人物入库确认 / 事实冲突裁定，你选定后它接着干。":
    "It pauses with a card when it needs your call: person disambiguation / intent clarification / new talent confirmation / fact conflict resolution — then continues with your decision.",
  "权限：只读为主；写入只有「加入人才库」和「事实裁定」两种，且必须经你确认才执行。":
    "Permissions: mostly read-only; the only writes are \"add to Talent Pool\" and \"fact resolution\", both requiring your confirmation.",
  "库内：筛选人物 search_persons · 语义检索知识库 search_knowledge · 简历画像 get_person_profile · 评估报告 get_person_evaluation · 多版本简历对比 get_resume_versions · 统计排名 aggregate_persons。":
    "Internal: filter persons search_persons · semantic knowledge search search_knowledge · resume profile get_person_profile · evaluation report get_person_evaluation · multi-version resume diff get_resume_versions · stats and ranking aggregate_persons.",
  "外部：AMiner 学者（引用数/单位）· AMiner 论文 · DBLP 发文核验 · 舆情与公开动态 search_web · GitHub 开源项目核验 · OpenAlex 精确被引（仅兜底）。":
    "External: AMiner scholars (citations/affiliation) · AMiner papers · DBLP publication verification · reputation and public activity search_web · GitHub open-source verification · OpenAlex exact citations (fallback only).",
  "「我们人才库里现在有哪些人？」": "\"Who is currently in our Talent Pool?\"",
  "「对比下 A 和 B 的实习经历和评估结果」":
    "\"Compare the internship experience and evaluation results of A and B\"",
  "「库里谁的顶会一作论文最多？按引用量排序」":
    "\"Who in the pool has the most first-author top-conference papers? Sort by citations\"",
  "「对比张三两份简历，他这半年新增了哪些技能？」":
    "\"Compare Zhang San's two resumes — what skills did he gain in the past six months?\"",
  "「帮我调查一下学者 XXX 的学术背景和最近动态」→ 调查完可一键加入人才库":
    "\"Investigate scholar XXX's academic background and recent activity\" → add them to the Talent Pool in one click when done",
  "「检索一下 XXX 近三年有没有学术不端或负面舆情」":
    "\"Check whether XXX has any academic misconduct or negative reputation in the last three years\"",
  "「李四简历上说主导了某开源项目，Star 多少？最近三个月有提交吗？」":
    "\"Li Si's resume says he leads an open-source project — how many stars? Any commits in the last three months?\"",
  "舆情类信息请看角标状态：已确认 / 待核验 / 冲突，待核验内容建议人工复核后再采信。":
    "Check the citation status for reputation info: confirmed / pending verification / conflict. Review pending items manually before relying on them.",
  "外部调查会串行调用多个数据源，回答可能需要 1-2 分钟；工具卡片在动就表示它还在干活。":
    "External research queries multiple data sources in sequence and may take 1-2 minutes; as long as tool cards keep moving, it is still working.",
  "会话保存在本地数据库，刷新、换页面都不会丢；侧栏可重命名、删除（双击确认）。":
    "Sessions are stored in a local database and survive refreshes and navigation; rename or delete them in the sidebar (click twice to confirm).",
  "正在调用工具": "Calling tools",
  "失败 · {summary}": "Failed · {summary}",
  "请求失败": "Request failed",
  "人才问答": "Talent Q&A",
  "库内优先 · 必要时联网调查": "Talent Pool first · Web research when needed",
  "画像澄清": "Profile Clarification",
  "加载会话…": "Loading session…",
  "询问人才、比较经历，或调查一个明确人物": "Ask about talent, compare experience, or investigate a specific person",
  "Agent 会自主调用库内检索与外部工具；遇到歧义会请你决策":
    "The Agent autonomously calls internal search and external tools, and asks for your call on ambiguity",
  "导航栏": "Navigation Bar",
  "简历评估": "Resume Screening",
  "人才库": "Talent Pool",
  "问答输入框": "Q&A Input Box",
  "设置": "Settings",
  "开始使用": "Get Started",
  "这是主要功能入口，包含人才问答、简历评估、人才库和设置。下面逐一介绍每个模块。":
    "This is the main entry point, with Talent Q&A, Resume Screening, Talent Pool, and Settings. Let's walk through each module.",
  "输入姓名即可让 AI Agent 自动检索人才库、查论文、查舆情，生成调查报告。上下文取决于调用的模型（当前是 DeepSeek-V4-Flash[1M]）。":
    "Type a name and the AI agent automatically searches the Talent Pool, papers, and reputation to build an investigation report. Context length depends on the model in use (currently DeepSeek-V4-Flash[1M]).",
  "导入 PDF/图片简历，自动结构化解析、论文核验、AI 多维度评估打分。左侧导入，中间看简历，右侧看评估进度和结果。":
    "Import PDF/image resumes for automatic structured parsing, publication verification, and AI scoring across dimensions. Import on the left, view the resume in the center, track progress and results on the right.",
  "所有评估入库的人才都在这里。关系图谱可视化人才网络，列表视图查看评分排序，右侧详情栏看完整档案和简历版本对比。":
    "Every screened candidate lives here. The graph view visualizes your talent network, the list view sorts by score, and the detail pane shows full profiles and resume version diffs.",
  "回到问答页——在这里输入问题。Agent 会预告每一步操作，工具调用卡片实时弹出，回答带引用角标。":
    "Back to the Q&A page — type your question here. The Agent announces each step, tool cards pop up live, and answers carry citation markers.",
  "随时点击查看 Agent 工作原理、工具列表和权限说明。":
    "Click anytime to see how the Agent works, its tool list, and permission details.",
  "在这里可以查看后端服务的运行状态，以及配置相关外部服务的 API Key（只可修改，不可读取已保存的值）。首次使用前请确保各服务 Key 已配置。":
    "Check backend service status and configure API keys for external services (keys can be updated, but saved values cannot be read back). Make sure all keys are configured before first use.",
  "引导结束！有问题随时点左下角「使用说明」。祝使用愉快～":
    "That's the tour! Click \"User Guide\" at the bottom left anytime you need help. Enjoy!",
  "上一步": "Back",
  "跳过": "Skip",
  "完成": "Done",
  "下一步": "Next",
} as Record<string, string>;
