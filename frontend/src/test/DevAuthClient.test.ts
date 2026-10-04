import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DevAuthClient } from "../auth/DevAuthClient";

function mkToken(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.sig`;
}

describe("DevAuthClient", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("can login without explicit firm/client ids", async () => {
    const token = mkToken({
      sub: "dev@example.com",
      exp: Math.floor(Date.now() / 1000) + 3600,
      roles: ["firm_staff"],
      firm_id: "11111111-1111-1111-1111-111111111111",
    });

    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ access_token: token }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const client = new DevAuthClient("/api");
    await client.login({ sub: "dev@example.com", role: "firm_staff" });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(init.body).toContain('"firm_id":null');
    expect(init.body).toContain('"client_id":null');
    expect(client.isAuthenticated()).toBe(true);
  });
});
