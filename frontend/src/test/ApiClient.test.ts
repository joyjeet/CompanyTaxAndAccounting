import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { ApiClient, ApiError } from "../api/ApiClient";
import type { AuthClient } from "../auth/AuthClient";

function fakeAuth(token: string | null): AuthClient {
  return {
    getAccessToken: async () => token,
    getIdentity: () => null,
    isAuthenticated: () => token !== null,
    login: async () => {},
    logout: async () => {},
    onChange: () => () => {},
  };
}

describe("ApiClient", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("attaches the bearer token from the auth client", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })
    );
    const api = new ApiClient(fakeAuth("tok-123"), "/api");
    await api.listDocuments();
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const [url, init] = call as [string, RequestInit];
    expect(url).toBe("/api/documents");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-123");
  });

  it("omits Authorization when no token is held", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })
    );
    const api = new ApiClient(fakeAuth(null), "/api");
    await api.listDrafts();
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBeNull();
  });

  it("throws ApiError with parsed detail on non-2xx", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      () =>
        new Response(JSON.stringify({ detail: "nope" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        })
    );
    const api = new ApiClient(fakeAuth("t"), "/api");
    await expect(api.listDocuments()).rejects.toMatchObject({
      status: 403,
      message: "nope",
    });
    await expect(api.listDocuments()).rejects.toBeInstanceOf(ApiError);
  });
});
