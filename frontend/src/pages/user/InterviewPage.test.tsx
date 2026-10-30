// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../../api", () => ({ default: apiMock }));

import InterviewPage from "./InterviewPage";

const template = {
  id: "template", title: "Recovery interview", role: "Engineer", experience_level: "junior",
  difficulty: "easy", duration_minutes: 1, question_count: 2, focus_areas: [],
  default_questions_or_topics: [], max_pauses_allowed: 3,
};
const opening = { role: "assistant", content: "Explain transactions", timestamp: "2026-01-01T00:00:00Z" };
const answer = { role: "user", content: "An atomic unit of work", timestamp: "2026-01-01T00:00:01Z" };

describe("database-backed interview recovery", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    apiMock.put.mockResolvedValue({ data: { message: "Draft saved" } });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  function button(text: string) {
    const found = [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
    expect(found).toBeTruthy();
    return found!;
  }

  it("restores a pending answer after remount and freezes the timer until AI succeeds", async () => {
    let recovered = false;
    apiMock.get.mockImplementation(async (path: string) => ({
      data: path === "/interviews/templates" ? [template] : {
        id: "session", status: recovered ? "in_progress" : "paused",
        started_at: new Date().toISOString(), remaining_seconds: recovered ? 49 : 50, pause_count: 0,
        feedback: recovered ? {} : { pending_evaluation: true },
        transcript: recovered ? [opening, answer, { ...opening, content: "Next question" }] : [opening, answer],
      },
    }));
    apiMock.post.mockImplementation(async () => {
      recovered = true;
      return { data: { score: 8 } };
    });
    await act(async () => root.render(<InterviewPage templateId="template" sessionId="session" onExit={vi.fn()} />));
    expect(container.querySelector("textarea")?.value).toBe(answer.content);
    expect(container.querySelector("textarea")?.disabled).toBe(true);
    expect(container.textContent).toContain("saved in the database");
    expect(apiMock.post).not.toHaveBeenCalled();
    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(container.textContent).toContain("0:50");
    expect(apiMock.post).not.toHaveBeenCalled();
    await act(async () => button("Retry AI and continue").click());
    expect(apiMock.post).toHaveBeenCalledWith(
      "/interviews/session/message", { response_text: answer.content }, { timeout: 180_000 },
    );
    expect(container.textContent).toContain("Next question");
    expect(container.querySelector("textarea")?.disabled).toBe(false);
    expect(container.querySelector("textarea")?.value).toBe("");
  });

  it.each(["503", "timeout"])("keeps a failed %s retry paused with a visible try-later message", async (failure) => {
    apiMock.get.mockImplementation(async (path: string) => ({
      data: path === "/interviews/templates" ? [template] : {
        id: "session", status: "paused", started_at: new Date().toISOString(),
        remaining_seconds: 50, feedback: { pending_evaluation: true }, transcript: [opening, answer],
      },
    }));
    apiMock.post.mockRejectedValue(failure === "503" ? {
      response: { status: 503, data: { detail: "AI unavailable. Your answers are saved. Please try again after some time." } },
    } : { message: "Request timed out" });
    await act(async () => root.render(<InterviewPage templateId="template" sessionId="session" onExit={vi.fn()} />));
    await act(async () => button("Retry AI and continue").click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("try again after some time");
    expect(container.querySelector("textarea")?.value).toBe(answer.content);
    expect(container.querySelector("textarea")?.disabled).toBe(true);
    expect(button("Return to interviews").disabled).toBe(false);
  });

  it("recognizes a completed server turn when its success response is lost", async () => {
    let completed = false;
    apiMock.get.mockImplementation(async (path: string) => ({
      data: path === "/interviews/templates" ? [template] : {
        id: "session", status: completed ? "in_progress" : "paused",
        started_at: new Date().toISOString(), remaining_seconds: 50,
        feedback: completed ? {} : { pending_evaluation: true },
        transcript: completed ? [opening, answer, { ...opening, content: "Recovered next question" }] : [opening, answer],
      },
    }));
    apiMock.post.mockImplementation(async () => {
      completed = true;
      throw new Error("Response connection lost");
    });
    await act(async () => root.render(<InterviewPage templateId="template" sessionId="session" onExit={vi.fn()} />));
    await act(async () => button("Retry AI and continue").click());
    expect(container.textContent).toContain("Recovered next question");
    expect(container.querySelector("textarea")?.value).toBe("");
    expect(container.querySelector("textarea")?.disabled).toBe(false);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("restores an unsubmitted draft from the server with no local answer storage", async () => {
    apiMock.get.mockImplementation(async (path: string) => ({
      data: path === "/interviews/templates" ? [template] : {
        id: "session", status: "in_progress", started_at: new Date().toISOString(), remaining_seconds: 50,
        feedback: { draft_answer: "Server-persisted unsent draft" }, transcript: [opening],
      },
    }));
    await act(async () => root.render(<InterviewPage templateId="template" sessionId="session" onExit={vi.fn()} />));
    expect(container.querySelector("textarea")?.value).toBe("Server-persisted unsent draft");
    expect(container.textContent).toContain("Draft restored from the database.");
    expect(localStorage.getItem("interview_interrupt_session")).toBe("1");
    expect(localStorage.length).toBe(1);
  });
});
