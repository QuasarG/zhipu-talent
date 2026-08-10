# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-07-30
- Primary product surfaces: 简历评估工作台、人才知识问答、人才库结构化浏览与关系图。
- Evidence reviewed: `CONTEXT.md`、`docs/backend_use_case_decisions.md`、`.omx/plans/talent-platform-implementation-plan.md`、`docs/talent_platform_design.md`、`agi_talent_radar/web/templates/workbench.html`、`agi_talent_radar/web/templates/talent_pool.html`、`agi_talent_radar/web/static/workbench.css`、`docs/AGI talent.png`。
- Figma target: 三个 1440 x 1024 desktop frames，共享一个组件/变量页；移动版在后续前端实现阶段补充。

## Brand

- Personality: 冷静、可信、研究导向，像人才研究操作台，不像招聘营销页面。
- Trust signals: 原始证据、来源、时间、核验状态、Agent 实际调用链和不确定性始终可见。
- Avoid: 自动录取暗示、把分数当通过/不通过、无来源推断、整页高透明导致文本难读、纯蓝紫单色科技感。

## Product goals

- Goals: 让内部评审者完成简历能力评估、人才档案查询、已知人物调查和证据复核，并能快速在三种核心工作方式间切换。
- Non-goals: 自动录取、批量发现未知人才、代码仓库核验、多角色权限。
- Success signals: 用户能明确区分能力评分、Track 推荐、论文核验、外部事实状态和 HR 跟进状态；任一结论可以回到证据。

## Personas and jobs

- Primary personas: AI 研究团队负责人、技术面试官、HR/人才项目运营。
- User jobs: 导入并评估简历、复核论文、查询和比较人才、调查具体人物、查看来源关系、维护 HR 跟进状态。
- Key contexts of use: 桌面端长时间使用，数据密度高；一次处理多份简历或围绕一位人物连续追问。

## Information architecture

- Primary navigation: 左侧窄栏或浮动玻璃导航，包含“简历评估”“人才知识”“人才库”“待核验”“设置”；顶部保留当前页面标题、全局搜索、任务状态和用户菜单。
- Core routes/screens:
  1. Resume Evaluation Workspace：简历队列、原文/结构化内容、Agent 进度与评估结果。
  2. Talent Knowledge Chat：自由提示词、工具调用过程、答案、引用与人物上下文。
  3. Talent Pool & Graph：人才列表、来源筛选、详情摘要和关系图谱。
  4. Talent Profile：单个人才的完整结构化简历/PDF、评估结果与运行过程。
- Content hierarchy: 当前对象与任务状态 > 结论/回答 > 证据与核验状态 > 历史版本 > 次要元数据。

## Design principles

- Evidence first: 分数、Track 推荐、论文核验和知识回答都必须能定位来源。
- Separate dimensions: 能力评分、Track 推荐、论文核验和 HR 状态使用不同组件与文案，不共享一个“等级”视觉。
- Glass for chrome, clarity for content: Liquid Glass 用于导航、工具条、浮动控制和上下文切换；长文本、表格和证据正文使用更高不透明度表面。
- Dense but calm: 保持专业工具的信息密度，不制造营销式 Hero、大标题或装饰卡片墙。
- Honest state: pending、confirmed、conflict、partial、failed 和 retrying 必须明确显示，不用模糊动画掩盖失败。
- Tradeoffs: 视觉表现服务于证据阅读；当玻璃质感与对比度冲突时，优先可读性。

## Visual language

- Color: 背景使用冷白 `#EDF2F5` 和浅灰蓝 `#DDE7EC`，辅以青绿 `#2F7D73`、珊瑚红 `#D45D54`、琥珀 `#B7791F`；主文字 `#152126`。禁止以紫蓝渐变统治全屏。
- Glass material: 控制层填充 `rgba(255,255,255,0.54)`，背景模糊 28-36px，1px 高光边框 `rgba(255,255,255,0.72)`，内侧顶缘高光和轻柔环境阴影。深色浮层使用 `rgba(19,29,34,0.68)`。
- Typography: 中文优先 `SF Pro Display` / `SF Pro Text` 回退 `PingFang SC`、`Microsoft YaHei`；正文 14-16px，辅助 12-13px，紧凑面板标题 18-24px。等宽字体只用于分数、ID 和技术状态。
- Spacing/layout rhythm: 4px 基础网格；常规间距 8/12/16/24/32；工作区左右安全边距 24px。
- Shape/radius/elevation: 数据面板 8px 圆角；导航玻璃壳和 segmented control 可使用 18-24px 或胶囊形；避免卡片套卡片。阴影只用于浮动导航、菜单和工具条。
- Motion: 180-260ms spring-like ease；玻璃控件切换可有轻微折射位移，内容区不漂浮；支持 reduced motion。
- Imagery/iconography: 使用 Lucide/SF Symbols 对应图标；图标按钮必须有 tooltip。背景可使用克制的半透明色带和真实内容缩略图，不使用光球、bokeh 或装饰 SVG 插画。

## Components

- Existing components to reuse: 简历队列、候选人条目、证据定位、Agent 节点进度、确认 Dialog、Toast、论文状态卡、分数条。
- New/changed components:
  - Glass Navigation Rail：全局页面切换和当前任务状态。
  - Context Switcher：当前候选人/人物切换胶囊。
  - Evidence Citation：来源、时间、核验状态和点击定位。
  - Verification Badge：confirmed / pending / conflict，不能只靠颜色。
  - Track Recommendation：宽泛方向、理由和置信度。
  - Agent Trace：展示实际节点和工具调用，支持部分失败。
  - Talent Source Filter：全部、简历评估、人物调查；双来源去重。
  - Relationship Graph Legend：颜色表示学校，形状表示主要推荐方向，线型表示关系核验状态。
- Variants and states: ready, queued, running, done, partial, pending, confirmed, conflict, warning, error, cancelled, retrying, not_configured。
- Token/component ownership: Figma Variables 与未来 CSS tokens 使用相同语义命名；现有 `workbench.css` 在实现阶段迁移，不引入第二套冲突 token。

## Core screen specifications

### 1. Resume Evaluation Workspace

- Layout: 72px 全局导航；左侧 280px 简历提交队列；中间 520px 原文/结构化双视图；右侧弹性评估区。
- Header: 当前候选人、评估版本、任务状态、重新评估和更多菜单。
- Main result: 总分只作为能力概览；下方分开呈现通用潜力、Track 评分、推荐 Track、论文自述/外部核验和培养建议。
- Paper review: 每篇论文同时显示自述状态、外部核验状态、作者顺序、原文证据和重试按钮。

#### Structured resume record layout

- 中栏所有模块使用固定记录行，不使用自由流式标签堆叠，也不在模块卡内嵌套子卡片。
- 记录层级固定为：序号/类型标识 > 主标题 > 具名元数据字段 > 证据或说明；主标题使用 600-700 字重，字段名使用 500，正文使用 400。
- 教育、经历和项目的机构、岗位、时间、页码使用固定网格列；字段缺失时保留结构但隐藏空值，不让相邻内容跳位。
- 论文记录固定为四段：论文标题；简历自述事实；外部数据库事实；核验结论、差异与来源链接。
- 右侧评估区使用“评估结果 / 运行过程”两个同级子页面；切换发生在固定 Tab 中，不改变三栏工作台宽度。
- 运行过程由后端下发完整图谱目录，按准备、路由、并行评估、汇总输出四阶段展示；节点即使未运行也必须可见。
- 并行阶段显式拆分通用评分链与专业 Track 组。阶段和 Track 组都可展开收拢，默认展开当前运行阶段。
- 节点状态只使用待运行、运行中、已完成、已跳过、失败五类；动效仅用于运行中状态和 Tab/折叠过渡，并遵守 reduced-motion。
- 论文核验 JSON 应分别提供 `claim`、`external_record`、`checks`、`verdict`，前端不得从说明文本反推作者、venue、年份或来源。
- `checks` 至少拆分标题、作者身份、作者位次和发表状态；状态必须同时使用文字、图标和颜色，verified / mismatch / unverifiable 视觉强度明显不同。

### 2. Talent Knowledge Chat

- Layout: 72px 导航；左侧 280px 会话/人物上下文；中间对话主区；右侧 360px 引用与 Agent Trace 抽屉。
- Composer: 底部浮动玻璃输入条，支持自然语言，不展示固定人物调查表单。
- Response: 先给结论摘要，再给结构化研究范围、关键论文、舆情或比较结果；每段带 citation chip。
- Trace: MySQL/Qdrant/AMiner/OpenAlex/Web Search 的调用状态分开显示；部分失败保留已有答案并明确警告。
- Fact status: 本次联网新事实标记“待核验”，冲突来源并列；Agent 不提供业务修改按钮。

### 3. Talent Pool & Relationship Graph

- Layout: 72px 导航；顶部搜索和来源 segmented control；左侧 400px 人才列表；右侧列表详情或关系图两种 view tab。
- List: 姓名、当前机构/学校、主要推荐 Track、来源标签、HR 状态、最近更新时间；不显示自动等级。
- Detail: 简历版本、评估历史、论文、外部事实、舆情、HR 状态和审核历史使用同一档案 ID。
- Graph: Person、School、Organization、Direction 为实体节点；共享实体形成聚类，不做人才两两全连接。
- Visual encoding: 人才颜色表示学校；形状表示主要推荐方向；confirmed 实线、pending 虚线、disproved 当前隐藏；所有边可打开证据。
- Primary Track: 人才列表和图谱必须使用最新完成评估中权重最大的 `track_assignment`；人物研究方向文本仅作无评估数据时的回退，不得覆盖评估结果。
- HR status: 招聘生命周期使用 MD3 胶囊组展示：已投递 → 待初筛 → 面试中 → 待发 Offer → 已发 Offer → 已入职 / 已离职 / 已淘汰。第一次点击进入带勾的待确认态，第二次点击同一项才提交并写审计；人才储备是标签，不混入生命周期。
- Graph integrity: 只展示人物与学校、机构、主要 Track 等有来源实体的关系；不得根据同校、同 Track 自动伪造人物间合作关系。布局必须确定性稳定，筛选或返回页面不应随机跳位。

### 4. Talent Profile

- Route: `/talent-pool/:personId`，从人才库的“查看完整档案”进入，浏览器返回后保留人才库筛选、视图和选中项。
- Layout: 顶部为人物身份、主要 Track、来源与可换行的 HR 生命周期胶囊；主体为左右双栏。左栏放大版结构化简历/简历原文 PDF，右栏为评估结果/运行过程两个子页面。
- Data ownership: 路由使用稳定 `person_id`，人物详情接口必须同时返回关联 `candidate_id`；简历、PDF、HR 审计使用 `candidate_id`，人物主档与历史评估使用 `person_id`。
- Empty cases: 人物调查来源且尚无简历时，左栏显示无简历状态，右栏仍可展示人物调查和舆情；不得请求不存在的 PDF。

## Accessibility

- Target standard: WCAG 2.1 AA。
- Keyboard/focus behavior: 导航、segmented control、tabs、引用、图谱节点和 Dialog 均可键盘操作；焦点在玻璃背景上仍有清晰轮廓。
- Contrast/readability: 玻璃层上的正文必须有足够局部对比；长文本面板提高不透明度；状态同时使用文字、图标和颜色。
- Screen-reader semantics: Agent 进度和 SSE 结果使用 `aria-live`；图谱提供列表等价视图。
- Reduced motion and sensory considerations: 减弱玻璃折射和弹性位移，禁用持续漂浮与闪烁。

## Responsive behavior

- Supported breakpoints/devices: 1440px Figma 首稿；1280px 以上完整桌面；768-1279px 折叠辅助栏；小于 768px 提供基本查看和关键操作。
- Layout adaptations: 中等宽度将左侧队列/会话变成抽屉；右侧引用或详情改为 bottom sheet；三栏不强行压缩。
- Touch/hover differences: 关键内容不依赖 hover；触摸目标最小 44px；图标 tooltip 在触摸设备提供长按替代。

## Interaction states

- Loading: 展示真实节点、工具或索引阶段，不伪造剩余时间。
- Empty: 每屏只强调一个主操作，例如“导入简历”“开始提问”“添加首位人才”。
- Error: 区分核心失败与外部服务部分失败，并提供局部重试。
- Success: 保留结果、耗时、来源和版本；不以大面积绿色庆祝。
- Disabled: 显示禁用原因。
- Offline/slow network: 已完成内容保留，外部调查和向量同步显示延迟/待重试。

## Content voice

- Tone: 专业、克制、可核验，不替 HR 做最终决定。
- Terminology: 统一使用“简历评估”“Track 推荐”“论文自述状态”“论文核验状态”“人才知识 Agent”“待核验外部事实”。
- Microcopy rules: 状态文案必须说明对象和下一步；禁止使用“通过”“淘汰”“S/A/B/C 人才”等自动分类文案。

## Implementation constraints

- Framework/styling system: 当前 Flask API + React/Vite + Tailwind CSS；优先复用现有 `ResumeContent`、`EvaluationWorkspace`、MD3 UI 组件与语义 token，不引入第二套组件库。
- Design-token constraints: Material Design 3 的信息架构和可访问状态规范与 Liquid Glass 视觉材料结合；数据面板圆角保持 8px，胶囊只用于导航和模式切换。
- Performance constraints: backdrop blur 层级受控；大列表和图谱虚拟化；PDF 与 Agent Trace 按需渲染。
- Compatibility constraints: Windows 本地开发，现代 Chromium/Edge；保留 Flask SSE。
- Privacy constraints: 浏览器不直接读取 `.env`；Key 只显示已配置或掩码状态。
- Test/screenshot expectations: 三个核心界面均需 1440x1024 和 390x844 截图检查；无溢出、重叠、低对比玻璃正文或不可追溯状态。

## Open questions

- [ ] 次要 Track 在关系图节点中的视觉表达，在图谱开发阶段确认。
- [ ] Figma 组件命名和变量 collection 在创建目标文件后冻结。
- [ ] 当前会话未提供 Windows/Figma 控制入口，三张 Frame 尚未实际绘制到 Figma。
