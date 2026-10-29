import { describe, expect, it, vi } from "vitest";
import { AnswerSaveQueue } from "./answerSaveQueue";

describe("exam answer save queue", () => {
  it("keeps a failed answer dirty and retries it on the next flush", async () => {
    const save = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    const queue = new AnswerSaveQueue(save);
    queue.enqueue("question-1", "draft");

    await expect(queue.flush()).rejects.toThrow("offline");
    expect(queue.hasPending).toBe(true);

    await queue.flush();
    expect(save).toHaveBeenCalledTimes(2);
    expect(queue.hasPending).toBe(false);
  });

  it("saves the newest edit when an older save is already in flight", async () => {
    let finishFirst!: () => void;
    const save = vi.fn()
      .mockImplementationOnce(() => new Promise<void>((resolve) => { finishFirst = resolve; }))
      .mockResolvedValue(undefined);
    const queue = new AnswerSaveQueue(save);
    queue.enqueue("question-1", "older draft");

    const flush = queue.flush();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    queue.enqueue("question-1", "latest draft");
    finishFirst();
    await flush;

    expect(save.mock.calls.map(([questionId, answer]) => [questionId, answer])).toEqual([
      ["question-1", "older draft"],
      ["question-1", "latest draft"],
    ]);
    expect(queue.hasPending).toBe(false);
  });
});
