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
});
