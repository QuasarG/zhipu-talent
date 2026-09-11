import type { ChatSegment } from "@/lib/types";

type SpawnSegment = Extract<ChatSegment, { type: "spawn" }>;

/** 后端存的是带 spawn_id 的扁平聊天段：把子段嵌回对应 spawn（无归属的保持顶层）。
 *  兼容 spawn 段自带 children 的情况（原位保留并继续填充）。 */
export function nestTraceSegments(segments: ChatSegment[]): ChatSegment[] {
  const out: ChatSegment[] = [];
  const spawnById = new Map<string, SpawnSegment>();

  for (const segment of segments) {
    if (segment.type === "spawn") {
      const nested: SpawnSegment = { ...segment, children: [...(segment.children ?? [])] };
      spawnById.set(nested.spawn_id, nested);
      out.push(nested);
      continue;
    }
    const spawnId = (segment as { spawn_id?: string }).spawn_id;
    const parent = (spawnId ? spawnById.get(spawnId) : null);
    if (parent) {
      parent.children = [...parent.children, segment];
      continue;
    }
    out.push(segment);
  }
  return out;
}
