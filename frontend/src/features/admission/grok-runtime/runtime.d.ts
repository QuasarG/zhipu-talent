export type Mood = 'idle' | 'listening' | 'searching' | 'working' | 'thinking' | 'happy' | 'confused';
export class GrokCharacter {
  constructor(svg: SVGSVGElement, options: {
    mode: 'hold'; shape: 'blob'; color: 'black'; state: Mood;
    loginWrap: boolean; followPointer: boolean; sizePx: number;
    reduceMotion: boolean; inkFlat: string; eyeColor: string;
  });
  setState(state: Mood, options?: { resetEyes?: boolean }): void;
  setGazeTarget(point: { x: number; y: number } | null): void;
  destroy(): void;
}
