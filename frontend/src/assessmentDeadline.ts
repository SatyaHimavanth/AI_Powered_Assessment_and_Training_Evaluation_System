export function assessmentDeadlineEpoch(
  remainingSeconds: number,
  scheduledEndTime?: string | null,
  now = Date.now(),
): number {
  const durationDeadline = now + Math.max(0, remainingSeconds) * 1000;
  if (!scheduledEndTime) return durationDeadline;
  const scheduledDeadline = Date.parse(scheduledEndTime);
  return Number.isFinite(scheduledDeadline)
    ? Math.max(now, Math.min(durationDeadline, scheduledDeadline))
    : durationDeadline;
}
