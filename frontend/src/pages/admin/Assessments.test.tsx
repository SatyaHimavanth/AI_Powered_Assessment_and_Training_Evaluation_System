// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../../api", () => ({ default: apiMock }));

import Assessments from "./Assessments";

describe("assessment creation requirements", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    apiMock.get.mockResolvedValue({ data: { items: [], total: 0 } });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(
      <Assessments
        topics={[{ id: "topic", name: "SQL", description: null }]}
        batches={[{ id: "batch", name: "Training", description: null, status: "current", user_count: 1 }]}
        users={[{
          id: "user", name: "Candidate", username: "candidate", email: "candidate@example.test",
          contact_email: "contact@example.test", account: null, role: "user",
          is_active: true, created_at: "2026-01-01T00:00:00Z",
        }]}
        setMessage={vi.fn()}
      />,
    ));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.resetAllMocks();
  });

  async function clickButton(text: string) {
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
    expect(button).toBeTruthy();
    await act(async () => button?.click());
  }

  function expectRequiredField(id: string) {
    expect(container.querySelector(`label[for="${id}"]`)?.textContent).toContain("*");
    expect(container.querySelector(`#${id}`)?.hasAttribute("required")).toBe(true);
  }

  it("removes the fake progress bar and identifies required and optional fields", () => {
    expect(container.querySelector('[aria-label="Assessment setup steps"]')).toBeNull();
    expect(container.textContent).not.toContain("1. Content");
    expect(container.textContent).toContain("Fields marked * are required.");
    expectRequiredField("assessment-title");
    expectRequiredField("assessment-duration");
    for (const id of ["assessment-start-time", "assessment-end-time"]) {
      expect(container.querySelector(`label[for="${id}"]`)?.textContent).toContain("(optional)");
      expect(container.querySelector(`#${id}`)?.hasAttribute("required")).toBe(false);
    }
    expect(container.textContent).toContain("Description (optional)");
  });

  it("marks the active audience selection without requiring text in the search box", async () => {
    expect(container.querySelector('label[for="assessment-batch-search"]')?.textContent).toContain("*");
    expect(container.textContent).toContain("Select at least one batch.");
    expect(container.querySelector("#assessment-batch-search")?.hasAttribute("required")).toBe(false);
    const usersTab = container.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1];
    await act(async () => usersTab.click());
    expect(container.querySelector('label[for="assessment-user-search"]')?.textContent).toContain("*");
    expect(container.textContent).toContain("Select at least one user.");
    expect(container.querySelector("#assessment-user-search")?.hasAttribute("required")).toBe(false);
    expect(container.querySelector("#assessment-batch-search")).toBeNull();
  });

  it("marks required question settings only for the selected source", async () => {
    expect(container.textContent).toContain("Sections * (at least one)");
    await clickButton("Add Section");
    for (const id of ["assessment-topic-0", "assessment-type-0", "assessment-difficulty-0", "assessment-count-0"]) {
      expectRequiredField(id);
    }
    await clickButton("Excel");
    expectRequiredField("assessment-import");
    expect(container.querySelector("#assessment-topic-0")).toBeNull();
    await clickButton("DB");
    expect(container.querySelector("#assessment-import")).toBeNull();
    expectRequiredField("assessment-topic-0");
  });
});
