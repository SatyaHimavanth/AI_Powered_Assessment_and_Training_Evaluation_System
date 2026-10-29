// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { assessmentDeadlineEpoch } from "./assessmentDeadline";
import {
  clearAssessmentDraft,
  clearOtherAssessmentDrafts,
  clearUserAssessmentDrafts,
  loadAssessmentDraft,
  saveAssessmentDraft,
  type AssessmentDraft,
} from "./assessmentOfflineDraft";

const firstDraft: AssessmentDraft<{ title: string }> = {
  userKey: "candidate-a",
  assessmentId: "assessment-1",
  attemptId: "attempt-1",
  updatedAt: 100,
  timeRemainingSeconds: 90,
  answers: { questionA: "option-1" },
  pendingSubmit: false,
  examData: { title: "Example assessment" },
};

describe("attempt-scoped offline assessment drafts", () => {
  beforeEach(() => localStorage.clear());

  it("restores only the exact user's attempt and never leaks its answers to another attempt", () => {
    saveAssessmentDraft(firstDraft);

    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-1"))
      .toEqual(firstDraft);
    expect(loadAssessmentDraft("candidate-b", "assessment-1", "attempt-1"))
      .toBeNull();
    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-2"))
      .toBeNull();
    expect(loadAssessmentDraft("candidate-a", "assessment-2", "attempt-1"))
      .toBeNull();
  });

  it("clears only the specified attempt draft", () => {
    saveAssessmentDraft(firstDraft);
    saveAssessmentDraft({ ...firstDraft, attemptId: "attempt-2" });

    clearAssessmentDraft("candidate-a", "assessment-1", "attempt-1");

    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-1")).toBeNull();
    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-2")).not.toBeNull();
  });

  it("clears superseded attempts and user drafts without deleting another user's draft", () => {
    saveAssessmentDraft(firstDraft);
    saveAssessmentDraft({ ...firstDraft, attemptId: "attempt-2" });
    saveAssessmentDraft({ ...firstDraft, userKey: "candidate-b", attemptId: "attempt-3" });

    clearOtherAssessmentDrafts("candidate-a", "assessment-1", "attempt-2");
    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-1")).toBeNull();
    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-2")).not.toBeNull();
    expect(loadAssessmentDraft("candidate-b", "assessment-1", "attempt-3")).not.toBeNull();

    clearUserAssessmentDrafts("candidate-a");
    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-2")).toBeNull();
    expect(loadAssessmentDraft("candidate-b", "assessment-1", "attempt-3")).not.toBeNull();
  });

  it("discards malformed or identity-mismatched records", () => {
    saveAssessmentDraft(firstDraft);
    const key = Object.keys(localStorage).find((item) => item.includes("attempt-1"));
    expect(key).toBeDefined();
    localStorage.setItem(key!, "{bad json");

    expect(loadAssessmentDraft("candidate-a", "assessment-1", "attempt-1")).toBeNull();
    expect(localStorage.getItem(key!)).toBeNull();
  });
});

describe("assessment deadline selection", () => {
  it("uses the earlier of remaining active duration and scheduled assessment close", () => {
    const now = Date.parse("2026-10-29T10:00:00Z");
    expect(assessmentDeadlineEpoch(30 * 60, "2026-10-29T10:10:00Z", now))
      .toBe(Date.parse("2026-10-29T10:10:00Z"));
    expect(assessmentDeadlineEpoch(5 * 60, "2026-10-29T10:10:00Z", now))
      .toBe(now + 5 * 60 * 1000);
  });

  it("ignores malformed scheduled-close values and never uses a stale deadline", () => {
    const now = Date.parse("2026-10-29T10:00:00Z");
    expect(assessmentDeadlineEpoch(60, "not-a-date", now)).toBe(now + 60_000);
    expect(assessmentDeadlineEpoch(60, "2026-10-29T09:59:00Z", now)).toBe(now);
  });
});
