// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("../../api", () => ({ default: apiMock }));

import Practice from "./Practice";

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

describe("practice data recovery", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.resetAllMocks();
  });

  it("shows a retryable load error without presenting a false access denial", async () => {
    apiMock.get.mockRejectedValueOnce({ response: { data: { detail: "Temporary service failure" } } });
    apiMock.get.mockResolvedValueOnce({ data: { has_access: false, pending_request: false } });

    await act(async () => root.render(<Practice />));
    expect(container.textContent).toContain("Practice data could not be loaded");
    expect(container.textContent).toContain("Temporary service failure");
    expect(container.textContent).not.toContain("Practice Test Access Required");

    const retry = [...container.querySelectorAll("button")].find((button) => button.textContent === "Retry");
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());
    expect(apiMock.get).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Practice Test Access Required");
  });

  function mockOlderTest(status = "in_progress") {
    const older = {
      id: "older-test", job_title: "Yesterday's unfinished work", topics: "Databases",
      difficulty: "easy", question_count: 1, status, score: null,
      created_at: "2020-01-01T10:00:00Z", submitted_at: null,
    };
    apiMock.get.mockImplementation(async (path: string) => {
      if (path === "/practice/access") return { data: { has_access: true, expires_at: null, pending_request: false } };
      if (path === "/practice/today") return { data: null };
      if (path === "/practice/history") return { data: [older] };
      if (path === "/practice/older-test") return {
        data: {
          id: older.id,
          questions: [{ id: "question", type: "text", question: "Explain transactions", options: null }],
          saved_answers: { question: "My saved draft" },
        },
      };
      throw new Error(`Unexpected request: ${path}`);
    });
    apiMock.post.mockResolvedValue({ data: { message: "OK" } });
  }

  it("resumes a previous-day test and restores its saved answers with one start request", async () => {
    mockOlderTest();
    await act(async () => root.render(<Practice />));
    const resume = [...container.querySelectorAll("button")].find((button) => button.textContent === "Resume Test");
    expect(resume).toBeTruthy();
    await act(async () => { resume?.click(); resume?.click(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith("/practice/older-test/start");
    expect(container.querySelector("textarea")?.value).toBe("My saved draft");
  });

  it("allows retrying a failed generation from a previous day", async () => {
    mockOlderTest("failed");
    await act(async () => root.render(<Practice />));
    const retry = [...container.querySelectorAll("button")].find((button) => button.textContent === "Retry generation");
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());
    expect(apiMock.post).toHaveBeenCalledWith("/practice/older-test/retry-generation");
  });

  it("shows a submission failure in the test view without discarding restored answers", async () => {
    mockOlderTest();
    await act(async () => root.render(<Practice />));
    const resume = [...container.querySelectorAll("button")].find((button) => button.textContent === "Resume Test");
    await act(async () => resume?.click());
    apiMock.post.mockRejectedValueOnce({ response: { data: { detail: "Evaluation temporarily unavailable" } } });
    const submit = [...container.querySelectorAll("button")].find((button) => button.textContent === "Submit Test");
    await act(async () => submit?.click());
    expect(container.textContent).toContain("Evaluation temporarily unavailable");
    expect(container.querySelector("textarea")?.value).toBe("My saved draft");
  });
});
