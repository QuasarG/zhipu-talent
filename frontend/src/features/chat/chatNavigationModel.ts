export interface ChatHeading {
  id: string;
  label: string;
  level: 1 | 2 | 3;
}

function plainHeadingLabel(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .replace(/\s+#+\s*$/, "")
    .trim();
}

export function markdownHeadings(markdown: string, prefix: string): ChatHeading[] {
  const headings: ChatHeading[] = [];
  for (const line of markdown.split(/\r?\n/)) {
    const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
    if (!match) continue;
    const label = plainHeadingLabel(match[2]);
    if (!label) continue;
    headings.push({
      id: `${prefix}-heading-${headings.length}`,
      label,
      level: match[1].length as 1 | 2 | 3,
    });
  }
  return headings;
}
