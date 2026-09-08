import { useEffect, useRef, useState } from 'react';
import Icon from '@/components/ui/Icon';
import type { GrokCharacter, Mood } from './grok-runtime/runtime.js';

type State = 'working' | 'done' | 'failed' | 'waiting' | 'stopped';
const loadRuntime = () => import('./grok-runtime/runtime.js');

export default function GrokAgentAvatar({ state, role = '', gaze = 0, system = false, small = false, still = false }: {
  state: State; role?: string; gaze?: number; system?: boolean; small?: boolean; still?: boolean;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const instance = useRef<GrokCharacter | null>(null);
  const [onScreen, setOnScreen] = useState(true);
  const [hidden, setHidden] = useState(document.hidden);
  const [failed, setFailed] = useState(false);
  const [systemReduced, setSystemReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const staticFrame = still || small || systemReduced || state === 'stopped';
  const mood: Mood = gaze ? 'listening' : state === 'failed' ? 'confused' : state === 'done' ? 'happy'
    : state !== 'working' ? 'idle' : ['verify', 'cross_check'].includes(role) ? 'searching'
      : ['chair', 'reviewer'].includes(role) ? 'thinking' : 'working';
  const latest = useRef({ mood, gaze });
  latest.current = { mood, gaze };
  const staticMood = staticFrame ? mood : null;

  useEffect(() => {
    const handleVisibility = () => setHidden(document.hidden);
    const query = matchMedia('(prefers-reduced-motion: reduce)');
    const handleMotion = () => setSystemReduced(query.matches);
    document.addEventListener('visibilitychange', handleVisibility);
    query.addEventListener('change', handleMotion);
    const observer = new IntersectionObserver(entries => setOnScreen(entries[0]?.isIntersecting ?? false));
    if (svg.current) observer.observe(svg.current);
    return () => { document.removeEventListener('visibilitychange', handleVisibility); query.removeEventListener('change', handleMotion); observer.disconnect(); };
  }, []);

  useEffect(() => {
    if (system || !svg.current || hidden || !onScreen) return;
    let cancelled = false;
    let engine: GrokCharacter | null = null;
    loadRuntime().then(({ GrokCharacter }) => {
      if (cancelled || !svg.current) return;
      engine = new GrokCharacter(svg.current, { mode: 'hold', shape: 'blob', color: 'black',
        state: latest.current.mood, loginWrap: true, followPointer: false, sizePx: small ? 34 : 64,
        reduceMotion: staticFrame, inkFlat: 'var(--color-on-surface)', eyeColor: 'var(--color-surface-lowest)' });
      setFailed(false);
      if (staticFrame) { engine.destroy(); engine = null; }
      else {
        instance.current = engine;
        if (latest.current.gaze) {
          const bounds = svg.current.getBoundingClientRect();
          engine.setGazeTarget({ x: bounds.x + bounds.width / 2 + Math.sign(latest.current.gaze) * 100, y: bounds.y + bounds.height / 2 });
        }
      }
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; engine?.destroy(); instance.current = null; };
  }, [system, hidden, onScreen, staticFrame, staticMood, small]);

  useEffect(() => { instance.current?.setState(mood); }, [mood]);
  useEffect(() => {
    if (!instance.current || !svg.current) return;
    const bounds = svg.current.getBoundingClientRect();
    instance.current.setGazeTarget(gaze ? { x: bounds.x + bounds.width / 2 + Math.sign(gaze) * 100, y: bounds.y + bounds.height / 2 } : null);
  }, [gaze]);

  return <span className="acs-avatar acs-grok-avatar" data-small={small} aria-hidden="true">
    {system ? <Icon name="layers" size={small ? 18 : 26} /> : <>
      <svg ref={svg} className="acs-grok-svg" style={{ visibility: failed ? 'hidden' : 'visible' }} />
      {failed && <Icon name="error" size={24} />}
    </>}
  </span>;
}
