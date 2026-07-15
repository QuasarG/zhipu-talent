# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-07-15
- Primary product surfaces: Flask 面试评审工作台、候选人库、PDF 简历视图、多 Track 评估结果。
- Evidence reviewed: `README.md`、`agi_talent_radar/web/templates/workbench.html`、`agi_talent_radar/web/static/workbench.css`、`agi_talent_radar/web/static/workbench.js`、`agi_talent_radar/web/workbench.py`、`agi_talent_radar/core/graph.py`。

## Brand

- Personality: 冷静、严谨、研究导向，像面试评审台而不是招聘营销页。
- Trust signals: 原始证据、页码定位、权重公式、路由理由、风险和不确定性可见。
- Avoid: 过度营销化、大面积装饰渐变、悬浮页面卡片、只展示总分不展示证据、用学校或公司 Logo 暗示候选人质量。

## Product goals

- Goals: 让评审者快速导入简历、理解 Track 分流、监控并行 Agent、核验原文证据并得到可面试的结论。
- Non-goals: 自动录用决策、单纯简历排名、把视觉排版当作核心能力、展示无法追溯的模型推断。
- Success signals: 用户能在一个屏幕内回答“走哪些 Track、为什么、得分如何、证据在哪、面试追问什么”。

## Personas and jobs

- Primary personas: AI 研究和工程团队面试官、人才项目评审者、技术负责人。
- User jobs: 批量初筛、单人深评、跨候选人比较、证据核验、生成面谈问题。
- Key contexts of use: 桌面端长时间工作，一次可能同时评估多位候选人。

## Information architecture

- Primary navigation: 顶栏提供导入和系统状态；左侧人才库；中间简历和原文；右侧 Agent 运行与评估。
- Core routes/screens: 工作台单页、候选人详情、PDF/结构化双视图、多 Track 结果。
- Content hierarchy: 结论和当前状态 > Track 权重与分数组成 > 维度和风险 > 原始证据。

## Design principles

- Evidence first: 所有评分、路由和风险都应能回到原始简历证据。
- Honest state: 并行、跳过、失败、重试和低置信度必须如实表达，不用假线性进度。
- Dense but calm: 优先扫读、对比和重复操作，避免装饰性大标题和卡片嵌套。
- Low-weight visual quality: 简历表达质量始终明示为最多 3 分的辅助信号。
- Tradeoffs: 桌面信息密度优先于移动端功能完整性；保留原生 Flask + JavaScript，优先模块化而不做框架迁移。

## Visual language

- Color: 中性黑白灰为主，用蓝、绿、琥珀、红区分信息、成功、警告和错误；Track 可有稳定的辅助色，不依赖颜色单独传达状态。
- Typography: 正文优先高可读的系统无衬线字体；等宽字体只用于分数、状态和技术标识。
- Spacing/layout rhythm: 4px 基础网格，密集操作使用 8-12px，主区块使用 16-24px。
- Shape/radius/elevation: 圆角不超过 8px；优先边框和底色分层，少用阴影。
- Motion: 120-200ms 状态过渡；并行节点可用轻量脉冲，支持 `prefers-reduced-motion`。
- Imagery/iconography: 界面不需要装饰插画；操作按钮优先熟悉图标和工具提示，候选人证据优先使用原始 PDF 图像。

## Components

- Existing components to reuse: 顶栏、人才库抽屉、候选人条目、证据 Popover、确认 Dialog、Toast、分数条。
- New/changed components: 批量导入队列（每份简历一行、真实阶段进度线、单条失败隔离）、PDF/结构化 Tab、并行 Agent 阶段图、Track 权重条、Track 详情 Tab、简历表达评估、视觉解析警告。
- Variants and states: ready, queued, running, done, skipped, warning, error, cancelled, retrying。
- Token/component ownership: 设计 token 继续存放在 `workbench.css :root`；JavaScript 组件按领域拆分，不引入第二套设计系统。

## Accessibility

- Target standard: WCAG 2.1 AA 的对比度、键盘操作和语义化基线。
- Keyboard/focus behavior: 所有 Tab、抽屉、证据链接和操作可键盘访问；对话框维护焦点；显示 `:focus-visible`。
- Contrast/readability: 小字不使用低对比灰；分数和警告同时有文字标签。
- Screen-reader semantics: 导入和 Agent 进度通过 `aria-live`通知；Tab 和并行节点使用正确 role 和状态。
- Reduced motion and sensory considerations: 禁用闪烁；降低动画模式下取消脉冲和位移。

## Responsive behavior

- Supported breakpoints/devices: 1280px 及以上桌面为主；768-1279px 可用；小于 768px 保证基本查看和操作。
- Layout adaptations: 宽屏三栏；中等宽度折叠人才库；小屏将人才库和 Agent 面板改为独立抽屉。
- Touch/hover differences: 不依赖 hover 才能看到的关键内容；触摸目标最小 40px。

## Interaction states

- Loading: 显示当前真实阶段、页码或节点，不伪造精确剩余时间。批量导入时每份简历独立显示进度线与错误阶段，最多并行处理 5 份，其他记录等待槽位且不因单份失败中断。
- Empty: 说明当前可执行的唯一主操作。
- Error: 区分文件校验、PDF 渲染、MCP 启动、鉴权、模型、数据库和节点错误，并提供局部重试。
- Success: 保留成功结果和耗时，将候选人自动聚焦到可审查状态。
- Disabled: 说明禁用原因，不只降低透明度。
- Offline/slow network, if applicable: 保留已完成页和节点结果，允许重试未完成部分。

## Content voice

- Tone: 专业、简洁、可核验，不对候选人做夸张或侮辱性表述。
- Terminology: 统一使用“Track”、“通用潜力”、“专业分”、“简历表达”、“路由置信度”和“待验证”。
- Microcopy rules: 状态文案说明对象和动作；错误文案说明失败阶段和可执行的下一步。

## Implementation constraints

- Framework/styling system: Flask/Jinja + 原生 JavaScript + 原生 CSS；本阶段不引入 React、Tailwind 或新构建链。
- Design-token constraints: 复用和扩展现有 CSS 变量；卡片圆角不超过 8px；不使用负 letter-spacing。
- Performance constraints: PDF 预览和节点流转按需渲染；候选人切换不应重新启动评估或重载已缓存详情。
- Compatibility constraints: Windows 本地开发，现代 Chromium/Edge 为主，保留 Flask SSE 协议。
- Test/screenshot expectations: 每次节点图、三栏布局或 PDF 视图修改都要通过单元测试、JavaScript 语法检查和桌面/移动 Playwright 截图。

## Open questions

- [ ] 人工修改 Track 权重是否在第一版开放，以及是否需要修改审计记录。
- [ ] PDF 原文是持久化保存还是只在导入期间使用，这决定证据 bbox 高亮的后端存储方案。
- [ ] 候选人横向比较的最大同屏人数和导出格式待确定。
