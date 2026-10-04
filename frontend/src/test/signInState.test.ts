import { beforeEach, describe, expect, it } from "vitest";

import {
  clearSignInState,
  readAudience,
  readSelection,
  writeAudience,
  writeSelection,
} from "../auth/signInState";

describe("signInState", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("defaults to the firm desk", () => {
    expect(readAudience()).toBe("firm");
  });

  it("round-trips the chosen audience", () => {
    writeAudience("client");
    expect(readAudience()).toBe("client");
  });

  it("treats an unrecognised stored audience as firm", () => {
    window.sessionStorage.setItem("ctaa.audience", "administrator");
    expect(readAudience()).toBe("firm");
  });

  it("round-trips a tenant selection", () => {
    writeSelection({ firmId: "f-1", clientId: "c-1" });
    expect(readSelection()).toEqual({ firmId: "f-1", clientId: "c-1" });
  });

  it("returns null for corrupt stored selections rather than throwing", () => {
    window.sessionStorage.setItem("ctaa.context", "{not json");
    expect(readSelection()).toBeNull();
  });

  it("returns null when the stored selection has no firm", () => {
    window.sessionStorage.setItem("ctaa.context", JSON.stringify({ clientId: "c" }));
    expect(readSelection()).toBeNull();
  });

  it("clears both keys on sign-out", () => {
    writeAudience("client");
    writeSelection({ firmId: "f-1" });
    clearSignInState();
    expect(readSelection()).toBeNull();
    expect(readAudience()).toBe("firm");
  });
});
