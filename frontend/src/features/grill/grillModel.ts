export function canSubmitProfile(confirmed: number, total: number): boolean {
  return total > 0 && confirmed === total;
}
