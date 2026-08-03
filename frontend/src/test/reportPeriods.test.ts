import { describe, expect, it } from "vitest";

import { isWithinRange, resolveReportPeriod } from "../lib/reportPeriods";

describe("resolveReportPeriod", () => {
  it("spans everything for the 'all' preset", () => {
    const r = resolveReportPeriod({ preset: "all" });
    expect(r.startDate).toBe("1900-01-01");
    expect(r.endDate).toBe("2099-12-31");
    expect(r.label).toBe("All dates");
  });

  it("auto-populates a single day for 'today'", () => {
    const r = resolveReportPeriod({ preset: "today" });
    expect(r.startDate).toBe(r.endDate);
    expect(r.startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("starts 'this_month' on the first of the month", () => {
    const r = resolveReportPeriod({ preset: "this_month" });
    expect(r.startDate.endsWith("-01")).toBe(true);
    expect(r.startDate <= r.endDate).toBe(true);
  });

  it("starts 'this_quarter' on a quarter boundary month", () => {
    const r = resolveReportPeriod({ preset: "this_quarter" });
    const month = Number(r.startDate.slice(5, 7));
    expect([1, 4, 7, 10]).toContain(month);
  });

  it("covers 30 inclusive days for 'last_30_days'", () => {
    const r = resolveReportPeriod({ preset: "last_30_days" });
    const start = new Date(`${r.startDate}T00:00:00`);
    const end = new Date(`${r.endDate}T00:00:00`);
    const days = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
    expect(days).toBe(30);
  });

  it("uses the user-supplied dates for 'custom'", () => {
    const r = resolveReportPeriod({
      preset: "custom",
      customStart: "2026-02-01",
      customEnd: "2026-02-28",
    });
    expect(r.startDate).toBe("2026-02-01");
    expect(r.endDate).toBe("2026-02-28");
    expect(r.label).toBe("2026-02-01 to 2026-02-28");
  });
});

describe("isWithinRange", () => {
  const range = { startDate: "2026-06-01", endDate: "2026-06-30" };

  it("includes both bounds", () => {
    expect(isWithinRange("2026-06-01", range)).toBe(true);
    expect(isWithinRange("2026-06-30", range)).toBe(true);
  });

  it("excludes dates outside the range", () => {
    expect(isWithinRange("2026-05-31", range)).toBe(false);
    expect(isWithinRange("2026-07-01", range)).toBe(false);
  });

  it("compares only the date part of a timestamp", () => {
    expect(isWithinRange("2026-06-15T23:59:59.000Z", range)).toBe(true);
    expect(isWithinRange("2026-07-01T00:00:00.000Z", range)).toBe(false);
  });

  it("treats missing dates as outside the range", () => {
    expect(isWithinRange(null, range)).toBe(false);
    expect(isWithinRange(undefined, range)).toBe(false);
  });
});
