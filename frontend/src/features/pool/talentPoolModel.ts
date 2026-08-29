export interface WeightedTrack {
  track: string;
  weight: number;
}

export const ENGAGEMENT_LIFECYCLE = [
  ["newly_admitted", "已投递", "inbox"],
  ["screening", "待初筛", "filter_alt"],
  ["interviewing", "面试中", "forum"],
  ["offer_pending", "待发 Offer", "approval"],
  ["offered", "已发 Offer", "send"],
  ["hired", "已入职", "badge"],
  ["departed", "已离职", "logout"],
  ["rejected", "已淘汰", "block"],
] as const;

export const ENGAGEMENT_LABELS: Record<string, string> = {
  ...Object.fromEntries(ENGAGEMENT_LIFECYCLE.map(([value, label]) => [value, label])),
  to_contact: "待初筛（旧）",
  contacted: "已联系（旧）",
  ongoing_follow: "人才储备（旧）",
  closed: "已结束（旧）",
};

export function dominantTrack(assignments: WeightedTrack[]): string {
  return assignments.reduce<WeightedTrack | null>(
    (best, item) => (!best || item.weight > best.weight ? item : best),
    null,
  )?.track || "";
}

export function transitionEngagementSelection(
  current: string,
  pending: string | null,
  clicked: string,
): { pending: string | null; commit: string | null } {
  if (clicked === current) return { pending: null, commit: null };
  if (clicked === pending) return { pending: null, commit: clicked };
  return { pending: clicked, commit: null };
}

export function validVisibleSelection(
  selectedId: string | null,
  visibleIds: readonly string[],
): string | null {
  if (!selectedId) return null;
  return visibleIds.includes(selectedId) ? selectedId : null;
}

export function visibleTalentGroupKeys(
  groupCounts: Readonly<Record<string, number>>,
  isFiltering: boolean,
): string[] {
  return Object.keys(groupCounts).filter((key) => !isFiltering || groupCounts[key] > 0);
}
