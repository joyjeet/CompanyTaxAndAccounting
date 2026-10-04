import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClient } from "../api/ApiClient";
import type { AuthClient } from "../auth/AuthClient";
import { writeSelection } from "../auth/signInState";

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

function headersOf(): Headers {
  const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
    .calls[0] as [string, RequestInit];
  return new Headers(init.headers);
}

describe("ApiClient tenant context headers", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("omits the context headers when nothing has been chosen", async () => {
    await new ApiClient(fakeAuth("t"), "/api").listDocuments();
    const headers = headersOf();
    expect(headers.get("X-CTAA-Firm")).toBeNull();
    expect(headers.get("X-CTAA-Client")).toBeNull();
  });

  it("sends the firm hint for a staff context", async () => {
    writeSelection({ firmId: "firm-1", clientId: null });
    await new ApiClient(fakeAuth("t"), "/api").listDocuments();
    const headers = headersOf();
    expect(headers.get("X-CTAA-Firm")).toBe("firm-1");
    expect(headers.get("X-CTAA-Client")).toBeNull();
  });

  it("sends both hints for a portal context", async () => {
    writeSelection({ firmId: "firm-1", clientId: "client-9" });
    await new ApiClient(fakeAuth("t"), "/api").listDocuments();
    const headers = headersOf();
    expect(headers.get("X-CTAA-Firm")).toBe("firm-1");
    expect(headers.get("X-CTAA-Client")).toBe("client-9");
  });
});
