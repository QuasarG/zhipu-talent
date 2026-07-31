export interface TextPart {
  kind: "text" | "evidence";
  text: string;
  evidenceId?: string;
}

export function resolveTrackWeightPercent(
  recommendationWeight?: number,
  fallbackWeight?: number,
): number {
  const raw = [recommendationWeight, fallbackWeight]
    .find((value) => Number.isFinite(value) && Number(value) > 0) || 0;
  const percent = raw <= 1 ? raw * 100 : raw;
  return Math.round(Math.min(100, Math.max(0, percent)));
}

export function tokenizeEvidenceReferences(text: string, validEvidenceIds: Set<string>): TextPart[] {
  if (!text) return [];
  const canonicalIds = new Map(
    [...validEvidenceIds].map((id) => [id.toLowerCase(), id]),
  );
  const parts: TextPart[] = [];
  const pattern = /\be\d+\b/gi;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ kind: "text", text: text.slice(cursor, index) });
    const matchedText = match[0];
    const evidenceId = canonicalIds.get(matchedText.toLowerCase());
    parts.push(evidenceId
      ? { kind: "evidence", text: matchedText, evidenceId }
      : { kind: "text", text: matchedText });
    cursor = index + matchedText.length;
  }

  if (cursor < text.length) parts.push({ kind: "text", text: text.slice(cursor) });
  return parts;
}
