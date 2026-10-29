// @vitest-environment jsdom
import axios, { AxiosError, type AxiosAdapter, type AxiosResponse } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api from "./api";

function response(config: Parameters<AxiosAdapter>[0], data: unknown): AxiosResponse {
  return { config, data, headers: {}, status: 200, statusText: "OK" };
}

function unauthorized(config: Parameters<AxiosAdapter>[0]): AxiosError {
  const responseData: AxiosResponse = {
    config,
    data: { detail: "Unauthorized" },
    headers: {},
    status: 401,
    statusText: "Unauthorized",
  };
  return new AxiosError("Unauthorized", "ERR_BAD_REQUEST", config, undefined, responseData);
}

describe("browser API authentication", () => {
  let adapter: AxiosAdapter;

  beforeEach(() => {
    localStorage.clear();
    adapter = vi.fn(async (config) => response(config, {}));
    api.defaults.adapter = adapter;
    axios.defaults.adapter = adapter;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses credentialed requests with a finite default timeout", () => {
    expect(api.defaults.withCredentials).toBe(true);
    expect(api.defaults.timeout).toBe(30_000);
  });

  it("uses HttpOnly-cookie credentials and refreshes once after an expired cookie", async () => {
    const requests: Parameters<AxiosAdapter>[0][] = [];
    const protectedRequestAuthorization: Array<string | undefined> = [];
    let refreshCalls = 0;
    adapter = vi.fn(async (config) => {
      requests.push(config);
      if (config.url === "/protected") {
        protectedRequestAuthorization.push(config.headers.get("Authorization"));
      }
      if (config.url?.includes("/auth/refresh")) {
        refreshCalls += 1;
        expect(config.withCredentials).toBe(true);
        return response(config, { role: "user" });
      }
      if (refreshCalls > 0) {
        return response(config, { ok: true });
      }
      throw unauthorized(config);
    });
    api.defaults.adapter = adapter;
    axios.defaults.adapter = adapter;
    await expect(api.get("/protected")).resolves.toMatchObject({ data: { ok: true } });

    expect(refreshCalls).toBe(1);
    expect(requests.filter((config) => config.url === "/protected")).toHaveLength(2);
    expect(protectedRequestAuthorization).toEqual([undefined, undefined]);
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
  });

  it("shares one refresh request across concurrent 401 responses", async () => {
    let refreshCalls = 0;
    adapter = vi.fn(async (config) => {
      if (config.url?.includes("/auth/refresh")) {
        refreshCalls += 1;
        await Promise.resolve();
        return response(config, { role: "user" });
      }
      if (refreshCalls > 0) {
        return response(config, { ok: true });
      }
      throw unauthorized(config);
    });
    api.defaults.adapter = adapter;
    axios.defaults.adapter = adapter;

    const results = await Promise.all([api.get("/one"), api.get("/two")]);

    expect(results.map((result) => result.data)).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
  });

  it("does not try refresh when a login request returns 401", async () => {
    const refreshCalls = vi.fn();
    adapter = vi.fn(async (config) => {
      if (config.url?.includes("/auth/refresh")) refreshCalls();
      throw unauthorized(config);
    });
    api.defaults.adapter = adapter;
    axios.defaults.adapter = adapter;

    await expect(api.post("/auth/login", { username: "candidate" })).rejects.toMatchObject({
      response: { status: 401 },
    });

    expect(refreshCalls).not.toHaveBeenCalled();
  });
});
