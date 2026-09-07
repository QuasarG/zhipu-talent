// 独立原型：以下人物、材料、输出和时间均为合成示例，不连接评估服务。
import type { ChatEvent, ChatMessage, ChatSegment } from '@/lib/types';

export type Agent = { id: string; name: string; role: string; color: string; shape: number; x: number; y: number };
export type Event = { at: number; agent: string; kind: 'work' | 'exchange' | 'chat' | 'finish'; text?: string; target?: string; chat?: ChatEvent; round?: number };
export type Scenario = { id: string; title: string; description: string; agents: Agent[]; events: Event[]; duration: number };
const person = (id: string, name: string, role: string, color: string, shape: number, x: number, y: number): Agent => ({ id, name, role, color, shape, x, y });
const chair = person('chair', '主席', '调度与综合', '#384c68', 0, 50, 24);
const verify = person('verify-1', '查证', '核实材料来源', '#257466', 1, 23, 48);
const deep = person('deep-1', '深读', '理解工作细节', '#65579c', 2, 77, 48);
const jd = person('jd-1', '岗位对照', '对照岗位要求', '#956029', 3, 25, 78);
const cross = person('cross-1', '仲裁', '处理证据分歧', '#9b536b', 4, 50, 78);
const generic = person('general-1', '通用评审', '补充调查', '#426e8a', 5, 75, 78);

function script() {
  const events: Event[] = [];
  const work = (at: number, agent: string, text: string, round = 1) => events.push({ at, agent, kind: 'work', text, round });
  const exchange = (at: number, agent: string, target: string, text: string) => events.push({ at, agent, target, kind: 'exchange', text });
  const output = (at: number, agent: string, text: string) => {
    const chunks = text.match(/[\s\S]{1,4}/g) || [];
    chunks.forEach((text, i) => events.push({ at: at + i * 85, agent, kind: 'chat', chat: { type: 'answer_delta', payload: { text } } }));
  };
  const tool = (at: number, agent: string, file: string, summary: string, failed = false) => {
    const call_id = `${agent}-${at}`;
    events.push({ at, agent, kind: 'chat', chat: { type: 'tool_start', payload: { call_id, tool: 'read_material', label: '读取材料', args_summary: file } } });
    events.push({ at: at + 1500, agent, kind: 'chat', chat: { type: 'tool_end', payload: { call_id, tool: 'read_material', status: failed ? 'error' : 'ok', summary, detail: `示例材料：${file}\n${summary}` } } });
  };
  const finish = (at: number, agent: string, text: string) => events.push({ at, agent, kind: 'finish', text });
  return { events, work, exchange, output, tool, finish };
}

const p = script();
p.work(0, 'chair', '盘点材料，拆分本次评估任务');
p.output(350, 'chair', '本次先确认项目贡献，再判断岗位匹配。材料包括简历、项目说明和岗位要求。');
p.exchange(3200, 'chair', 'verify-1', '请核实项目说明中的贡献归属，标出原文依据。');
p.work(5200, 'verify-1', '核实项目贡献的原始证据');
p.tool(5500, 'verify-1', '项目说明.pdf · 第 3 页', '找到评测模块负责人说明');
p.output(7200, 'verify-1', '### 查证发现\n材料确认其负责评测模块，但不足以支持“整体架构负责人”。\n\n> 本人负责评测集构建及回归测试模块。\n\n需要进一步区分模块负责与整体负责。');
p.exchange(11600, 'verify-1', 'chair', '已确认评测模块贡献；整体架构负责人的表述缺少支持。');
p.work(13600, 'chair', '根据查证发现追加深读');
p.exchange(14900, 'chair', 'deep-1', '请深读项目技术细节，判断模块工作是否体现独立交付。');
p.work(16900, 'deep-1', '检查方法、实验与交付边界');
p.tool(17200, 'deep-1', '技术附录.pdf', '示例文件读取超时', true);
p.work(19100, 'deep-1', '原材料读取失败，改读项目说明');
p.tool(19200, 'deep-1', '项目说明.pdf · 第 4 页', '定位到基线实验和回归测试记录');
p.output(21000, 'deep-1', '找到基线对比、失败案例归因和回归记录，可以支持评测模块的独立交付。\n\n**仍待核实：** 实验设计是否完全由本人完成。');
p.exchange(24800, 'deep-1', 'chair', '模块具备完整交付闭环；实验设计归属仍需补充证据。');
p.work(26800, 'chair', '将结论交给岗位对照评审');
p.exchange(27800, 'chair', 'jd-1', '对照岗位核心任务，区分直接经验与可迁移能力。');
p.work(29800, 'jd-1', '对照评测平台岗位要求');
p.output(30200, 'jd-1', '评测数据闭环与岗位核心任务直接相关。平台整体架构能力暂不能据此确认，建议在面试中验证。');
p.exchange(33800, 'jd-1', 'chair', '核心评测任务有直接证据，平台架构能力仍存在证据缺口。');
p.work(35800, 'chair', '对证据边界发起仲裁');
p.exchange(36800, 'chair', 'cross-1', '对“整体负责”和“模块负责”的分歧给出一致表述。');
p.work(38800, 'cross-1', '比对简历主张与项目原文');
p.output(39200, 'cross-1', '统一采用“独立负责评测模块”。保留整体架构能力待验证项，不把缺少证据直接视为没有能力。');
p.exchange(42500, 'cross-1', 'chair', '分歧已收敛：模块负责成立，整体架构负责待验证。');
p.work(44500, 'chair', '安排补充面试问题');
p.exchange(45500, 'chair', 'general-1', '围绕实验设计归属，整理两条可验证的面试问题。');
p.work(47500, 'general-1', '整理针对性的验证问题');
p.output(47900, 'general-1', '1. 请复述一个由你提出的基线实验，以及它改变了什么决策。\n2. 评测模块与整体架构的接口由谁设计？你做了哪些取舍？');
p.exchange(51500, 'general-1', 'chair', '已生成两条针对实验归属与架构边界的面试问题。');
p.work(53500, 'chair', '整理最终意见前，再向查证员确认边界');
p.exchange(54500, 'chair', 'verify-1', '续派：确认没有把待验证主张写成已确认事实。');
p.work(56500, 'verify-1', '沿用已有材料完成边界复核', 2);
p.output(56900, 'verify-1', '\n\n### 第 2 轮 · 边界复核\n已确认结论仅覆盖评测模块；架构负责与实验归属均保留为面试验证项。');
p.exchange(60600, 'verify-1', 'chair', '复核完成，确认事实与待验证事项已分开。');
p.work(62600, 'chair', '汇总各评审结论');
p.output(63000, 'chair', '\n\n### 综合意见\n评测模块经验有证据支持。将架构边界与实验归属交给面试验证。以上为合成演示，不产生真实评估分数。');
p.finish(67000, 'chair', '综合意见已就绪 · 演示结束');

const a = script();
a.work(0, 'mapper', '将候选人经历映射到岗位任务');
a.output(300, 'mapper', '已识别两项可评估任务：评测集构建与失败分析。接下来由系统分发独立任务。');
a.exchange(3500, 'mapper', 'system', '能力映射已完成，交给系统分发。');
a.exchange(5700, 'system', 'scorer-a', '评估任务一：评测集构建。');
a.work(7700, 'scorer-a', '评估任务一：评测集构建');
a.exchange(7900, 'system', 'scorer-b', '评估任务二：失败案例分析。');
a.work(9900, 'scorer-b', '评估任务二：失败案例分析');
a.tool(10000, 'scorer-a', '项目说明.pdf · 评测集', '找到构建与维护记录');
a.tool(10400, 'scorer-b', '技术附录.pdf · 失败案例', '找到分类归因与改进记录');
a.output(12000, 'scorer-a', '### 评测集构建\n存在持续维护和数据去重记录，支持独立完成任务。仍需面试核验样本选择标准。');
a.output(12500, 'scorer-b', '### 失败案例分析\n有分类归因和回归闭环记录。改进效果的统计口径尚未说明，应保留验证项。');
a.exchange(16000, 'scorer-a', 'system', '任务一评估完成，附样本选择标准验证项。');
a.exchange(18400, 'scorer-b', 'system', '任务二评估完成，附效果统计口径验证项。');
a.exchange(20800, 'system', 'reviewer', '汇总两项任务评分与证据，请独立复核。');
a.work(22800, 'reviewer', '复核证据边界与评分尺度');
a.output(23200, 'reviewer', '两项任务结论均有材料支撑。不能将模块交付扩大为整体系统能力；面试重点保留两处证据缺口。');
a.exchange(27200, 'reviewer', 'system', '总审完成，确认保留证据边界和面试验证项。');
a.finish(29800, 'system', '系统接收总审结果 · 演示结束');

export const scenarios: Scenario[] = [
  { id: 'panel', title: '评审团 · 动态派工', description: '1 位主席 + 5 类评审员 · 逐个执行 · 同一实例续派', agents: [chair, verify, deep, jd, cross, generic], events: p.events.sort((a, b) => a.at - b.at), duration: 68000 },
  { id: 'admission', title: '准入评估 · 并行协作', description: '能力映射 → 多任务并行评分 → 独立总审 · 系统不是 Agent', agents: [person('system', '系统任务台', '确定性调度', '#54616b', -1, 50, 45), person('mapper', '能力映射', '关联经历与任务', '#257466', 1, 22, 23), person('scorer-a', '任务评分 A', '评测集构建', '#65579c', 2, 23, 75), person('scorer-b', '任务评分 B', '失败案例分析', '#956029', 3, 77, 75), person('reviewer', '评分总审', '独立复核', '#9b536b', 4, 78, 23)], events: a.events.sort((a, b) => a.at - b.at), duration: 31000 },
];

export function snapshot(scenario: Scenario, time: number) {
  const states = new Map(scenario.agents.map(agent => [agent.id, { status: '未加入', task: agent.role, round: 1 }]));
  const messages = new Map<string, ChatMessage>();
  const seen = new Set<string>();
  const passed = scenario.events.filter(e => e.at <= time);
  for (const event of passed) {
    seen.add(event.agent);
    const state = states.get(event.agent)!;
    if (event.kind === 'work') { state.status = '工作中'; state.task = event.text!; state.round = event.round || 1; }
    if (event.kind === 'exchange') {
      seen.add(event.target!);
      state.status = '已交接';
      const target = states.get(event.target!)!;
      target.status = '收到信息'; target.task = event.text!;
    }
    if (event.kind === 'finish') { state.status = '已完成'; state.task = event.text!; }
    if (event.chat?.type === 'tool_start') state.task = `读取 ${event.chat.payload.args_summary}`;
    if (event.chat?.type === 'tool_end') state.task = event.chat.payload.status === 'error' ? '读取失败，准备切换材料' : '材料已返回，正在整理发现';
    if (event.kind !== 'chat') continue;
    const messageKey = `${event.agent}:${state.round}`;
    const message = messages.get(messageKey) || { id: messageKey, conversation_id: 'prototype', role: 'assistant', content: { segments: [] }, citations: [], status: 'running', created_at: '' };
    const segments: ChatSegment[] = message.content.segments;
    const chat = event.chat!;
    if (chat.type === 'answer_delta') {
      const last = segments.at(-1);
      if (last?.type === 'text') last.text += chat.payload.text;
      else segments.push({ type: 'text', text: chat.payload.text });
    }
    if (chat.type === 'tool_start') segments.push({ type: 'tool', ...chat.payload });
    if (chat.type === 'tool_end') {
      const segment = segments.find(s => s.type === 'tool' && s.call_id === chat.payload.call_id);
      if (segment?.type === 'tool') Object.assign(segment, chat.payload);
    }
    messages.set(messageKey, message);
  }
  for (const [key, msg] of messages) {
    const [id, round] = key.split(':');
    const state = states.get(id)!;
    msg.status = state.status === '工作中' && state.round === Number(round) ? 'running' : 'completed';
  }
  const exchange = [...passed].reverse().find(e => e.kind === 'exchange' && time - e.at < 2000);
  return { states, messages, seen, passed, exchange };
}
