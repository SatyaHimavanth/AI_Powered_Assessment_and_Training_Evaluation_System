// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("../../api", () => ({ default: apiMock }));

import QuestionGeneration from "./QuestionGeneration";

const failedBatch = {
  id: "failed-batch", status: "failed", topic_id: "topic", topic_name: "SQL transactions",
  question_type: "multi_mcq", difficulty: "hard", requested_count: 25,
  filename: null, total_generated: 0, total_approved: 0, total_rejected: 0,
  active_saved_count: 0, archived_saved_count: 0, error_message: "Model returned invalid options",
  can_retry: true, retry_blocked_reason: null, created_at: "2026-01-01T10:00:00Z", completed_at: null,
};

describe("generation batch context and failed actions", () => {
  let container: HTMLDivElement;
  let root: Root;
  const setMessage = vi.fn();

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    apiMock.get.mockResolvedValue({ data: { items: [failedBatch], total: 1 } });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  async function render() {
    await act(async () => root.render(
      <QuestionGeneration topics={[{ id: "topic", name: "SQL transactions", description: null }]} setMessage={setMessage} />,
    ));
  }

  function button(text: string) {
    const found = [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
    expect(found).toBeTruthy();
    return found!;
  }

  it("shows topic, question type, requested count, difficulty and failure reason", async () => {
    await render();
    expect(container.textContent).toContain("SQL transactions · Multi MCQ · 25 questions");
    expect(container.textContent).toContain("Difficulty: hard");
    expect(container.textContent).toContain("0 / 25 generated");
    expect(container.textContent).toContain("Model returned invalid options");
    expect(button("Retry").disabled).toBe(false);
    expect(button("Delete").disabled).toBe(false);
  });

  it("confirms retry and suppresses rapid duplicate requests", async () => {
    await render();
    await act(async () => button("Retry").click());
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("partial staged questions");
    let finish: (value: unknown) => void = () => {};
    apiMock.post.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await act(async () => { button("Retry generation").click(); button("Retry generation").click(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith("/admin/questions/generation/batches/failed-batch/retry");
    const pending = { ...failedBatch, status: "pending", can_retry: false, error_message: null };
    apiMock.get.mockResolvedValue({ data: { items: [pending], total: 1 } });
    await act(async () => finish({ data: pending }));
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(setMessage).toHaveBeenCalledWith(expect.stringContaining("queued again"));
    expect(container.textContent).toContain("pending");
  });

  it("does not delete until confirmed and clears the selected staged review", async () => {
    apiMock.get.mockImplementation(async (path: string) => ({
      data: path.endsWith("/staged") ? { items: [], total: 0 } : { items: [failedBatch], total: 1 },
    }));
    await render();
    const title = [...container.querySelectorAll("p")].find((item) => item.textContent?.includes("SQL transactions · Multi MCQ"));
    await act(async () => title?.parentElement?.parentElement?.click());
    expect(container.textContent).toContain("Review Staged Questions");
    await act(async () => button("Delete").click());
    expect(apiMock.delete).not.toHaveBeenCalled();
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("will not be deleted");
    await act(async () => button("Cancel").click());
    expect(apiMock.delete).not.toHaveBeenCalled();
    await act(async () => button("Delete").click());
    apiMock.delete.mockResolvedValue({ data: { message: "Failed batch deleted; saved questions retained" } });
    apiMock.get.mockResolvedValue({ data: { items: [], total: 0 } });
    await act(async () => button("Delete batch").click());
    expect(apiMock.delete).toHaveBeenCalledWith("/admin/questions/generation/batches/failed-batch");
    expect(container.textContent).not.toContain("Review Staged Questions");
    expect(container.textContent).toContain("No batches yet");
  });

  it("keeps the dialog and surfaces server errors instead of claiming success", async () => {
    apiMock.post.mockRejectedValue({ response: { data: { detail: "Only failed generation batches can be retried" } } });
    await render();
    await act(async () => button("Retry").click());
    await act(async () => button("Retry generation").click());
    expect(setMessage).toHaveBeenCalledWith("Only failed generation batches can be retried");
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("explains why approved output cannot be retried while still allowing deletion", async () => {
    apiMock.get.mockResolvedValue({ data: {
      items: [{ ...failedBatch, can_retry: false, retry_blocked_reason: "This batch has approved questions." }],
      total: 1,
    } });
    await render();
    expect(button("Retry").disabled).toBe(true);
    expect(button("Delete").disabled).toBe(false);
    expect(container.textContent).toContain("This batch has approved questions.");
  });

  it("refreshes active batch context automatically without showing failed-only controls", async () => {
    vi.useFakeTimers();
    apiMock.get.mockResolvedValue({ data: { items: [{ ...failedBatch, status: "processing", can_retry: false }], total: 1 } });
    await render();
    expect(container.textContent).toContain("SQL transactions · Multi MCQ · 25 questions");
    expect([...container.querySelectorAll("button")].some((item) => item.textContent === "Retry")).toBe(false);
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });
});
