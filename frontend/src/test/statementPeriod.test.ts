import { describe, expect, it } from "vitest";

import {
  type PeriodLike,
  periodCoversRange,
  pickBestPeriod,
  statementRangeFromTxns,
  suggestPeriodName,
  toWholeMonths,
} from "../lib/statementPeriod";

function period(
  id: string,
  name: string,
  start_date: string,
  end_date: string,
  is_locked = false,
): PeriodLike {
  return { id, name, start_date, end_date, is_locked };
}

const YEAR_2025 = period("y25", "2025", "2025-01-01", "2025-12-31");
const JULY_2025 = period("j25", "Jul 2025", "2025-07-01", "2025-07-31");
const YEAR_2026 = period("y26", "2026", "2026-01-01", "2026-12-31");

describe("statementRangeFromTxns", () => {
  it("spans the earliest and latest transaction date", () => {
    const range = statementRangeFromTxns([
      { date: "2025-07-15", amount: "3.00" },
      { date: "2025-07-07", amount: "5.44" },
      { date: "2025-07-28", amount: "395.60" },
    ]);
    expect(range).toEqual({ start: "2025-07-07", end: "2025-07-28" });
  });

  it("ignores rows whose date the parser could not infer", () => {
    // The parser leaves `date` empty when the year is not derivable.
    const range = statementRangeFromTxns([
      { date: "", amount: "1.00" },
      { date: "2025-07-11", amount: "119.88" },
      { date: "07/21", amount: "100.00" },
      { amount: "10.88" },
    ]);
    expect(range).toEqual({ start: "2025-07-11", end: "2025-07-11" });
  });

  it("returns null when no usable date exists", () => {
    expect(statementRangeFromTxns([{ amount: "1.00" }, { date: "" }])).toBeNull();
    expect(statementRangeFromTxns([])).toBeNull();
  });
});

describe("periodCoversRange", () => {
  const range = { start: "2025-07-07", end: "2025-07-28" };

  it("accepts a period that contains the range", () => {
    expect(periodCoversRange(JULY_2025, range)).toBe(true);
    expect(periodCoversRange(YEAR_2025, range)).toBe(true);
  });

  it("rejects a period from the wrong year", () => {
    expect(periodCoversRange(YEAR_2026, range)).toBe(false);
  });

  it("is inclusive on both boundaries", () => {
    const exact = period("x", "exact", "2025-07-07", "2025-07-28");
    expect(periodCoversRange(exact, range)).toBe(true);
    const shortByOneDay = period("s", "short", "2025-07-07", "2025-07-27");
    expect(periodCoversRange(shortByOneDay, range)).toBe(false);
  });
});

describe("pickBestPeriod", () => {
  const range = { start: "2025-07-07", end: "2025-07-28" };

  it("prefers the narrowest covering period", () => {
    // Both cover July, but the monthly period is the better home.
    expect(pickBestPeriod([YEAR_2025, JULY_2025], range)?.id).toBe("j25");
  });

  it("returns null rather than a merely-overlapping period", () => {
    // This is the case the backend would silently clamp, so we force a
    // conscious choice instead of guessing.
    const partial = period("p", "H2 2025", "2025-07-20", "2025-12-31");
    expect(pickBestPeriod([partial], range)).toBeNull();
  });

  it("never returns a locked period", () => {
    const locked = period("l", "Jul 2025", "2025-07-01", "2025-07-31", true);
    expect(pickBestPeriod([locked], range)).toBeNull();
  });

  it("returns null when nothing matches", () => {
    expect(pickBestPeriod([YEAR_2026], range)).toBeNull();
    expect(pickBestPeriod([], range)).toBeNull();
  });
});

describe("suggestPeriodName", () => {
  it("names a single-month range by its month", () => {
    expect(suggestPeriodName({ start: "2025-07-07", end: "2025-07-28" })).toBe("Jul 2025");
  });

  it("names a multi-month range as a span", () => {
    expect(suggestPeriodName({ start: "2025-07-01", end: "2025-09-30" })).toBe(
      "Jul 2025 – Sep 2025",
    );
  });

  it("spans years correctly", () => {
    expect(suggestPeriodName({ start: "2025-12-01", end: "2026-01-31" })).toBe(
      "Dec 2025 – Jan 2026",
    );
  });
});

describe("toWholeMonths", () => {
  it("snaps to the first and last day of the months involved", () => {
    expect(toWholeMonths({ start: "2025-07-07", end: "2025-07-28" })).toEqual({
      start: "2025-07-01",
      end: "2025-07-31",
    });
  });

  it("handles 30-day months and February", () => {
    expect(toWholeMonths({ start: "2025-09-03", end: "2025-09-15" }).end).toBe("2025-09-30");
    expect(toWholeMonths({ start: "2025-02-03", end: "2025-02-15" }).end).toBe("2025-02-28");
    // 2024 is a leap year.
    expect(toWholeMonths({ start: "2024-02-03", end: "2024-02-15" }).end).toBe("2024-02-29");
  });
});
