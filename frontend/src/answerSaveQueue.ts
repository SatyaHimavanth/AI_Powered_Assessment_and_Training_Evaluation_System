type SaveAnswer = (questionId: string, answer: string) => Promise<unknown>;

/** Keeps exam answer drafts retryable until the server confirms each save. */
export class AnswerSaveQueue {
  private readonly dirty = new Map<string, string>();
  private readonly inFlight = new Map<string, Promise<void>>();
  private readonly saveAnswer: SaveAnswer;

  constructor(saveAnswer: SaveAnswer) {
    this.saveAnswer = saveAnswer;
  }

  get hasPending(): boolean {
    return this.dirty.size > 0;
  }

  enqueue(questionId: string, answer: string): void {
    this.dirty.set(questionId, answer);
  }

  async flush(): Promise<void> {
    while (this.dirty.size > 0) {
      let failure: unknown;
      const batch = [...this.dirty.entries()];

      await Promise.all(batch.map(async ([questionId]) => {
        const pendingSave = this.inFlight.get(questionId);
        if (pendingSave) {
          try {
            await pendingSave;
          } catch (error) {
            failure ??= error;
            return;
          }
        }

        const latestAnswer = this.dirty.get(questionId);
        if (latestAnswer === undefined) return;

        try {
          await this.save(questionId, latestAnswer);
        } catch (error) {
          failure ??= error;
        }
      }));

      if (failure) throw failure;
    }
  }

  private save(questionId: string, answer: string): Promise<void> {
    const existingSave = this.inFlight.get(questionId);
    if (existingSave) return existingSave;

    const savePromise = Promise.resolve()
      .then(() => this.saveAnswer(questionId, answer))
      .then(() => {
        if (this.dirty.get(questionId) === answer) this.dirty.delete(questionId);
      })
      .finally(() => {
        if (this.inFlight.get(questionId) === savePromise) {
          this.inFlight.delete(questionId);
        }
      });
    this.inFlight.set(questionId, savePromise);
    return savePromise;
  }
}
