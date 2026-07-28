# AGI Talent Radar 前端

React 19 + Vite + TypeScript + Tailwind CSS v4，视觉体系为 **Material Design 3**（seed teal `#006A6B`）。

## 开发

```bash
npm run dev    # vite dev server（代理 /api 到 127.0.0.1:8502）
npm run build  # tsc -b && vite build，产物输出到 ../agi_talent_radar/web/static/dist（由 Flask 挂载在 /static/dist/ 下，需重启 Flask 刷新资产清单）
npm run lint   # oxlint
```

## 设计系统约定

- **Token 唯一来源**：`src/index.css` 的 `@theme` 块。标准 MD3 角色命名（`primary`/`secondary-container`/`surface-low`/`on-surface-variant`/`outline-variant`…），另有 `success`/`warning` 扩展色与 `track-agent` 等 Track 语义色。**禁止硬编码 hex/rgb，禁止 `bg-white/xx` 透明度 hack。**
- **共享 CSS 类**：`.md3-card` / `.md3-card-outlined` / `.md3-card-elevated`（tonal surface，不用阴影表达层级）、`.state-layer`（可点击元素必加）、`.text-display` ~ `.text-label`（MD3 typescale 紧凑密度）、`.md-icon`。
- **组件库** `src/components/ui/`：`Icon`（Material Symbols，自托管 woff2 于 `src/assets/fonts/`，勿改回 Google CDN）、`Button`/`IconButton`、`Card`、`Chip`/`StatusChip`、`Progress`、`SegmentedButtons`、`Tabs`、`SearchField`。
- **布局**：App Shell = `NavRail`（70px MD3 Navigation Rail）+ `main.flex-1.min-w-0`；grid 弹性列一律写 `minmax(0,1fr)`，防止 min-content 撑破容器。
- **CSS 层级**：自定义全局样式必须放入 Tailwind layer 或接受其低于 utilities 的优先级——**严禁**在非 layer 环境写 `* { margin:0; padding:0 }` 这类 reset（preflight 已覆盖）。

## 页面

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 简历评估 | 三栏：候选人队列 / 简历内容 / 评估结果 |
| `/knowledge` | 人才知识 | Agent 对话 + Agent Trace + 引用 |
| `/talent-pool` | 人才库 | 人才列表 + `RelationGraph` Canvas 力导向关系图谱 + 人物详情 |
| `/review` | 待核验 | 舆情报告核验（通过/驳回） |
| `/settings` | 设置 | 服务健康 + 脱敏配置 |
