/**
 * Helpers for aligning an accounting period with a parsed bank statement.
 *
 * Why this exists: `promote_statement_draft` in the backend CLAMPS every
 * transaction date into the selected period's range (see
 * `app/domain/promotion.py::_clamp`). Posting a July statement into a
 * full-year "2026" period is therefore silent data corruption — the entries
 * land on the period's start date instead of the real transaction dates.
 *
 * These helpers let the UI derive the statement's own range, pre-select the
 * period that actually covers it, and warn when the chosen period doesn't.
 */

/** Inclusive ISO (yyyy-mm-dd) date range. */
export interface DateRange {
  start: string;
  end: string;
}

/** Minimal shape of an accounting period needed for matching. */
export interface PeriodLike {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  is_locked: boolean;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * Derive the statement's date span from its parsed transactions.
 *
 * We use the per-transaction ISO dates rather than the `statement_period`
 * header string because the header is free text scraped by regex
 * (`"Jul 01 2025-Jul 31 2025"`) and is often absent, whereas the transaction
 * dates are already normalised to ISO by the parser. Rows with an empty or
 * malformed date are ignored — the parser leaves `date` blank when it cannot
 * infer the year.
 *
 * Returns `null` when no usable date is present.
 */
export function statementRangeFromTxns(
  txns: ReadonlyArray<Record<string, unknown>>,
): DateRange | null {
  const dates: string[] = [];
  for (const txn of txns) {
    const raw = txn.date;
    if (typeof raw === "string" && ISO_DATE.test(raw)) dates.push(raw);
  }
  if (dates.length === 0) return null;
  // ISO dates sort lexicographically, so string compare is safe here.
  dates.sort();
  return { start: dates[0], end: dates[dates.length - 1] };
}

/** True when `period` fully contains `range` (inclusive on both ends). */
export function periodCoversRange(period: PeriodLike, range: DateRange): boolean {
  return period.start_date <= range.start && period.end_date >= range.end;
}

/**
 * Pick the period that best fits the statement.
 *
 * Preference order:
 *   1. Unlocked periods that fully cover the range, narrowest first — a
 *      "Jul 2025" period is a better home for a July statement than a
 *      whole-year one, because it makes an out-of-range row obvious.
 *   2. Nothing. We deliberately do NOT fall back to a merely-overlapping
 *      period: that is exactly the case where clamping would corrupt dates,
 *      so the user must choose consciously.
 *
 * Locked periods are never returned — the backend rejects them anyway.
 */
export function pickBestPeriod<T extends PeriodLike>(
  periods: ReadonlyArray<T>,
  range: DateRange,
): T | null {
  const covering = periods
    .filter((p) => !p.is_locked && periodCoversRange(p, range))
    .sort((a, b) => spanDays(a) - spanDays(b));
  return covering[0] ?? null;
}

function spanDays(p: PeriodLike): number {
  return Date.parse(p.end_date) - Date.parse(p.start_date);
}

/**
 * Human-friendly name for a period created from a statement range.
 * A range covering exactly one calendar month becomes "Jul 2025";
 * anything else becomes "Jul 2025 – Sep 2025".
 */
export function suggestPeriodName(range: DateRange): string {
  const [sy, sm] = splitIso(range.start);
  const [ey, em] = splitIso(range.end);
  const startLabel = `${MONTH_NAMES[sm - 1]} ${sy}`;
  if (sy === ey && sm === em) return startLabel;
  return `${startLabel} – ${MONTH_NAMES[em - 1]} ${ey}`;
}

/**
 * Widen a statement range to whole calendar months.
 *
 * A statement rarely starts on the 1st or ends on the last day, but an
 * accounting period normally should. Snapping avoids creating a period that
 * silently excludes a late-month transaction added later.
 */
export function toWholeMonths(range: DateRange): DateRange {
  const [sy, sm] = splitIso(range.start);
  const [ey, em] = splitIso(range.end);
  const lastDay = new Date(Date.UTC(ey, em, 0)).getUTCDate();
  return {
    start: `${pad4(sy)}-${pad2(sm)}-01`,
    end: `${pad4(ey)}-${pad2(em)}-${pad2(lastDay)}`,
  };
}

function splitIso(iso: string): [number, number, number] {
  const [y, m, d] = iso.split("-");
  return [Number(y), Number(m), Number(d)];
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function pad4(n: number): string {
  return String(n).padStart(4, "0");
}
