export interface AssessmentDraft<TExamData = unknown> {
  userKey: string;
  assessmentId: string;
  attemptId: string;
  updatedAt: number;
  timeRemainingSeconds: number;
  answers: Record<string, string>;
  pendingSubmit?: boolean;
  examData: TExamData;
}

const PREFIX = "assessment-draft:v1:";

function storageKey(userKey: string, assessmentId: string, attemptId: string): string {
  return PREFIX + [userKey, assessmentId, attemptId].map(encodeURIComponent).join(":");
}

function isDraft(value: unknown): value is AssessmentDraft {
  if (!value || typeof value !== "object") return false;
  const draft = value as Partial<AssessmentDraft>;
  return typeof draft.userKey === "string"
    && typeof draft.assessmentId === "string"
    && typeof draft.attemptId === "string"
    && typeof draft.updatedAt === "number"
    && Number.isFinite(draft.updatedAt)
    && typeof draft.timeRemainingSeconds === "number"
    && Number.isFinite(draft.timeRemainingSeconds)
    && (draft.pendingSubmit === undefined || typeof draft.pendingSubmit === "boolean")
    && !!draft.answers
    && typeof draft.answers === "object"
    && !Array.isArray(draft.answers)
    && Object.values(draft.answers).every((answer) => typeof answer === "string");
}

export function saveAssessmentDraft<T>(draft: AssessmentDraft<T>): boolean {
  try {
    localStorage.setItem(storageKey(draft.userKey, draft.assessmentId, draft.attemptId), JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function loadAssessmentDraft<T>(
  userKey: string,
  assessmentId: string,
  attemptId: string,
): AssessmentDraft<T> | null {
  const key = storageKey(userKey, assessmentId, attemptId);
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isDraft(parsed)
      || parsed.userKey !== userKey
      || parsed.assessmentId !== assessmentId
      || parsed.attemptId !== attemptId) {
      localStorage.removeItem(key);
      return null;
    }
    return parsed as AssessmentDraft<T>;
  } catch {
    try { localStorage.removeItem(key); } catch { /* Storage can be unavailable. */ }
    return null;
  }
}

export function clearAssessmentDraft(userKey: string, assessmentId: string, attemptId: string): void {
  try {
    localStorage.removeItem(storageKey(userKey, assessmentId, attemptId));
  } catch {
    // Storage can be unavailable or cleared by the browser.
  }
}

export function clearOtherAssessmentDrafts(
  userKey: string,
  assessmentId: string,
  currentAttemptId: string,
): void {
  const assessmentPrefix = PREFIX + [userKey, assessmentId].map(encodeURIComponent).join(":") + ":";
  try {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(assessmentPrefix)) continue;
      if (key !== storageKey(userKey, assessmentId, currentAttemptId)) localStorage.removeItem(key);
    }
  } catch {
    // Draft persistence is best effort when browser storage is unavailable.
  }
}

export function clearUserAssessmentDrafts(userKey: string): void {
  const userPrefix = PREFIX + encodeURIComponent(userKey) + ":";
  try {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(userPrefix)) localStorage.removeItem(key);
    }
  } catch {
    // Drafts may already have been cleared by browser policy.
  }
}
