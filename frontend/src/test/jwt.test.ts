import { describe, expect, it } from "vitest";

import { tokenIsExpired, tokenToIdentity } from "../auth/jwt";

/**
 * HS256-signed token minted by hand. Payload:
 *   sub: alice, exp: far future, firm_id: <uuid>, roles: ["firm_staff"]
 * Signature is meaningless because we never verify on the frontend; the
 * backend re-validates. This test exercises ONLY the unsafe claim parse.
 */
const FAR_FUTURE_TOKEN =
  // header { alg: HS256, typ: JWT }
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
  // payload { sub: alice, exp: 32503680000, firm_id: 11111111-2222-3333-4444-555555555555, roles: [firm_staff] }
  "eyJzdWIiOiJhbGljZSIsImV4cCI6MzI1MDM2ODAwMDAsImZpcm1faWQiOiIxMTExMTExMS0yMjIyLTMzMzMtNDQ0NC01NTU1NTU1NTU1NTUiLCJyb2xlcyI6WyJmaXJtX3N0YWZmIl19." +
  "fake-signature";

const EXPIRED_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
  // exp: 1
  "eyJzdWIiOiJhbGljZSIsImV4cCI6MSwiZmlybV9pZCI6IjExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NSIsInJvbGVzIjpbImZpcm1fc3RhZmYiXX0." +
  "fake";

describe("jwt", () => {
  it("parses claims for a well-formed token", () => {
    const ident = tokenToIdentity(FAR_FUTURE_TOKEN);
    expect(ident).not.toBeNull();
    expect(ident!.sub).toBe("alice");
    expect(ident!.firmId).toBe("11111111-2222-3333-4444-555555555555");
    expect(ident!.role).toBe("firm_staff");
    expect(tokenIsExpired(FAR_FUTURE_TOKEN)).toBe(false);
  });

  it("flags expired token", () => {
    expect(tokenIsExpired(EXPIRED_TOKEN)).toBe(true);
  });

  it("rejects malformed input", () => {
    expect(tokenToIdentity("not-a-jwt")).toBeNull();
    expect(tokenToIdentity("a.b")).toBeNull();
  });
});
