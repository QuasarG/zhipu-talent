// 抛弃式原型：比较空间、内容、交接三种层级。只消费合成事件，不接业务 API。
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { BrowserRouter, useSearchParams } from 'react-router-dom';
import AssistantMessage from '@/features/chat/AssistantMessage';
import Icon from '@/components/ui/Icon';
import { scenarios, snapshot, type Agent, type Event } from '@/features/admission/prototype/scenarios';
import '@/features/admission/prototype/agent-space.css';

const variants = ['A', 'B', 'C'];
const variantNames = ['空间优先', '内容优先', '交接优先'];
const seconds = (ms: number) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

function Avatar({ agent, status, receiving, still }: { agent: Agent; status?: string; receiving?: boolean; still?: boolean }) {
  return <span className="asp-avatar" data-shape={agent.shape} data-status={status} data-receiving={receiving} data-still={still} style={{ '--agent-color': agent.color } as CSSProperties} aria-hidden="true">
    {agent.shape === -1 ? <Icon name="layers" size={30} /> : <span className="asp-body"><span className="asp-eyes"><i /><i /></span></span>}
  </span>;
}

export default function AgentSpacePrototype() {
  return <BrowserRouter><Prototype /></BrowserRouter>;
}

function Prototype() {
  const [params, setParams] = useSearchParams();
  const variant = variants.includes(params.get('variant') || '') ? params.get('variant')! : 'A';
  const [scenarioId, setScenarioId] = useState('panel');
  const scenario = scenarios.find(s => s.id === scenarioId)!;
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selected, setSelected] = useState('chair');
  const [autoSelect, setAutoSelect] = useState(true);
  const [follow, setFollow] = useState(true);
  const [still, setStill] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [pickedExchange, setPickedExchange] = useState<number | null>(null);
  const details = useRef<HTMLDivElement>(null);
  const state = useMemo(() => snapshot(scenario, time), [scenario, time]);
  const active = scenario.agents.filter(a => state.states.get(a.id)?.status === '工作中');
  const latestWork = [...state.passed].reverse().find(e => e.kind === 'work');
  const selectedId = autoSelect ? latestWork?.agent || scenario.agents[0].id : selected;
  const agent = scenario.agents.find(a => a.id === selectedId)!;
  const agentState = state.states.get(agent.id)!;
  const exchanges = state.passed.filter(e => e.kind === 'exchange');
  const exchange = pickedExchange === null ? state.exchange || exchanges.at(-1) : exchanges.find(e => e.at === pickedExchange);
  const messages = [...state.messages].filter(([key]) => key.startsWith(`${agent.id}:`));
  const currentTitle = state.exchange ? '信息正在交接' : active.length ? active.map(a => a.name).join('、') + '正在工作' : time >= scenario.duration ? '本次演示已结束' : '准备开始协作';

  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsed = Math.min(now - previous, 250) * speed;
      previous = now;
      setTime(t => Math.min(scenario.duration, t + elapsed));
    }, 50);
    return () => window.clearInterval(timer);
  }, [playing, speed, scenario.duration]);
  useEffect(() => { if (time >= scenario.duration) setPlaying(false); }, [time, scenario.duration]);
  useEffect(() => {
    if (follow && details.current) details.current.scrollTop = details.current.scrollHeight;
  }, [time, follow, selectedId, variant]);

  const switchVariant = (delta: number) => {
    setParams(p => { p.set('variant', variants[(variants.indexOf(variant) + delta + variants.length) % variants.length]); return p; }, { replace: true });
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, button, [contenteditable], [role="slider"]')) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        setParams(p => { p.set('variant', variants[(variants.indexOf(variant) + (event.key === 'ArrowRight' ? 1 : 2)) % 3]); return p; }, { replace: true });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [variant, setParams]);

  const chooseAgent = (id: string) => { setSelected(id); setAutoSelect(false); };
  const seek = (value: number) => { setTime(value); setPlaying(false); setPickedExchange(null); };
  const restart = () => { setTime(0); setPlaying(true); setPickedExchange(null); };
  const chooseExchange = (event: Event) => { setPickedExchange(event.at); setPlaying(false); chooseAgent(event.agent); };
  const name = (id?: string) => scenario.agents.find(a => a.id === id)?.name || '';

  const space = <section className="asp-space" aria-label="Agent 协作空间">
    <div className="asp-space-heading"><span>协作空间</span><span>{[...state.seen].filter(id => id !== 'system').length} 位 Agent 已加入</span></div>
    <div className="asp-stage" data-still={still}>
      <div className="asp-meeting-point"><span />信息交接区</div>
      {scenario.agents.filter(a => state.seen.has(a.id)).map(a => {
        const moving = state.exchange?.agent === a.id && a.id !== 'system' && !still;
        const target = scenario.agents.find(item => item.id === state.exchange?.target);
        const age = time - (state.exchange?.at || 0);
        const progress = moving ? age < 700 ? 1 - (1 - age / 700) ** 3 : age < 1350 ? 1 : (1 - (age - 1350) / 650) ** 3 : 0;
        const x = a.x + (target ? target.x - a.x : 0) * .62 * progress;
        const y = a.y + (target ? target.y - a.y : 0) * .62 * progress;
        const current = state.states.get(a.id)!;
        const receiving = state.exchange?.target === a.id;
        return <button type="button" key={a.id} className="asp-agent" style={{ left: `${x}%`, top: `${y}%` }} aria-pressed={selectedId === a.id} onClick={() => chooseAgent(a.id)}>
          <Avatar agent={a} status={current.status} receiving={receiving} still={still || !playing} />
          <strong>{a.name}</strong><span className="asp-agent-state">{receiving ? '接收信息' : moving ? '交接中' : current.status}</span>
          {current.status === '工作中' && <span className="asp-task-caption">{current.task}</span>}
          {current.round > 1 && <span className="asp-round">第 {current.round} 轮</span>}
        </button>;
      })}
    </div>
    <div className="asp-space-foot">
      {state.exchange ? <button type="button" className="asp-transfer-live" onClick={() => chooseExchange(state.exchange!)}><Icon name="arrow-right" size={18} /><span><strong>{name(state.exchange.agent)} → {name(state.exchange.target)}</strong>{state.exchange.text}</span><span>查看</span></button>
        : <p>{playing ? '点击任意 Agent，留在它的工作现场。' : '点击播放，观看合成事件驱动的工作与交接。'}</p>}
    </div>
  </section>;

  const detail = <section className="asp-detail" aria-label="Agent 工作详情">
    <header className="asp-detail-head"><Avatar agent={agent} status={agentState.status} still /><div><h2>{agent.name}<span>{agent.id === 'system' ? '系统' : 'Agent'}</span></h2><p>{agent.role} · 第 {agentState.round} 轮 · {agentState.status}</p></div></header>
    <div className="asp-detail-controls"><button type="button" aria-pressed={autoSelect} onClick={() => setAutoSelect(!autoSelect)}>{autoSelect ? '已跟随当前 Agent' : '已固定所选 Agent'}</button><button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? '暂停滚动跟随' : '跟随最新内容'}</button></div>
    <div ref={details} className="asp-detail-scroll" onWheel={() => setFollow(false)} onTouchMove={() => setFollow(false)}>
      <div className="asp-task"><span>当前任务</span><p>{agentState.task}</p></div>
      {messages.length ? messages.map(([key, message]) => <div className="asp-message" key={key}><p className="asp-message-label">第 {key.split(':')[1]} 轮 · 公开工作输出 / 合成演示</p><AssistantMessage message={message} busy={playing && message.status === 'running'} onDecide={() => {}} /></div>) : <p className="asp-empty">尚未产生工作输出。收到任务后，文字与工具操作将在这里依次出现。</p>}
      <div className="asp-records"><h3>交接记录</h3>{exchanges.filter(e => e.agent === agent.id || e.target === agent.id).map(e => <button type="button" key={e.at} aria-pressed={pickedExchange === e.at} onClick={() => chooseExchange(e)}><span>{seconds(e.at)} · {name(e.agent)} → {name(e.target)}</span><p>{e.text}</p></button>)}{!exchanges.some(e => e.agent === agent.id || e.target === agent.id) && <p>尚无交接。</p>}</div>
    </div>
  </section>;

  const transfer = <section className="asp-transfer" aria-label="交接内容">
    <div className="asp-space-heading"><span>{pickedExchange === null ? '最近一次交接' : '所选历史交接'}</span>{pickedExchange !== null && <button type="button" onClick={() => setPickedExchange(null)}>回到最新</button>}</div>
    {exchange ? <><div className="asp-transfer-pair">{[exchange.agent, exchange.target!].map((id, i) => <div key={id}><button type="button" onClick={() => chooseAgent(id)}><Avatar agent={scenario.agents.find(a => a.id === id)!} status={state.states.get(id)?.status} receiving={i === 1} still={still || !playing} /><strong>{name(id)}</strong><span>{i === 0 ? '发送方' : '接收方'}</span></button>{i === 0 && <Icon name="arrow-right" size={24} />}</div>)}</div><p className="asp-transfer-content">{exchange.text}</p><div className="asp-transfer-meta"><span>{seconds(exchange.at)} · 合成信息包</span><button type="button" onClick={() => seek(exchange.at)}>回看这次交接</button></div></> : <div className="asp-empty">任务尚未派发。播放后，交接双方与传递内容会出现在这里。</div>}
  </section>;

  return <main className="asp-root" data-variant={variant} data-paused={!playing}>
    <header className="asp-header"><div><div className="asp-title-row"><h1>协作现场</h1><span className="asp-demo-label">交互原型 · 合成演示</span></div><p>看见工作发生，也看清每一次交接。</p></div><label className="asp-scenario-label">演示链路<select aria-label="演示链路" value={scenarioId} onChange={e => { const s = scenarios.find(s => s.id === e.target.value)!; setScenarioId(s.id); setTime(0); setPlaying(false); setSelected(s.agents[0].id); setPickedExchange(null); }}>
      {scenarios.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label></header>
    <div className="asp-context"><div><span className="asp-status-dot" data-live={playing} /><strong>{currentTitle}</strong></div><p>{scenario.description}</p><label><input type="checkbox" checked={still} onChange={e => setStill(e.target.checked)} />减少动效</label></div>
    {variant === 'A' && <div className="asp-layout-a"><div className="asp-space-stack">{space}{pickedExchange !== null && transfer}</div>{detail}</div>}
    {variant === 'B' && <div className="asp-layout-b">{detail}<div className="asp-side-stack">{space}{transfer}</div></div>}
    {variant === 'C' && <div className="asp-layout-c"><div className="asp-exchange-stack">{transfer}<nav className="asp-team" aria-label="本次团队">{scenario.agents.filter(a => state.seen.has(a.id)).map(a => <button type="button" key={a.id} onClick={() => chooseAgent(a.id)} aria-pressed={selectedId === a.id}><Avatar agent={a} status={state.states.get(a.id)?.status} still /><span>{a.name}</span><small>{state.states.get(a.id)?.status}</small></button>)}</nav>{space}</div>{detail}</div>}
    <footer className="asp-player"><div className="asp-player-buttons"><button type="button" className="asp-play" onClick={() => time >= scenario.duration ? restart() : setPlaying(!playing)}><Icon name={playing ? 'pause' : 'play'} size={18} />{playing ? '暂停' : time >= scenario.duration ? '重播' : '播放演示'}</button><button type="button" onClick={restart}>从头播放</button><label>速度<select value={speed} onChange={e => setSpeed(Number(e.target.value))}><option value={.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option></select></label></div><input aria-label="演示时间定位" type="range" min={0} max={scenario.duration} step={50} value={time} onChange={e => seek(Number(e.target.value))} /><span className="asp-time">{seconds(time)} / {seconds(scenario.duration)}</span></footer>
    <details className="asp-debug"><summary>查看演示状态与边界 · {state.passed.length} 条事件</summary><p>所有文字增量、工具操作与材料均为预先编写的演示；不调用模型、不读取真实候选人、不产生评分。暂停会冻结演示时钟，拖动进度按事件重建状态。</p><pre>{JSON.stringify({ scenario: scenarioId, layout: variant, time: Math.round(time), playing, selected: selectedId, agents: Object.fromEntries(state.states) }, null, 2)}</pre></details>
    <nav className="asp-switcher" aria-label="原型布局切换"><button type="button" aria-label="上一个布局" onClick={() => switchVariant(-1)}><Icon name="chevron-left" size={20} /></button><span><strong>{variant}</strong> {variantNames[variants.indexOf(variant)]}</span><button type="button" aria-label="下一个布局" onClick={() => switchVariant(1)}><Icon name="chevron-right" size={20} /></button></nav>
  </main>;
}
