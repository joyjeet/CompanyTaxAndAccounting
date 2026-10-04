export type ReportPeriodPreset =
  | "all"
  | "today"
  | "this_week"
  | "this_month"
  | "this_quarter"
  | "this_year"
  | "last_30_days"
  | "last_90_days"
  | "last_12_months"
  | "custom";

export interface ReportPeriodRange {
  preset: ReportPeriodPreset;
  startDate: string;
  endDate: string;
  label: string;
}

export interface ReportPeriodInput {
  preset: ReportPeriodPreset;
  customStart?: string;
  customEnd?: string;
}

export const REPORT_PERIOD_OPTIONS: Array<{
  value: ReportPeriodPreset;
  label: string;
}> = [
  { value: "all", label: "All dates" },
  { value: "today", label: "Today" },
  { value: "this_week", label: "This week" },
  { value: "this_month", label: "This month" },
  { value: "this_quarter", label: "This quarter" },
  { value: "this_year", label: "This year" },
  { value: "last_30_days", label: "Last 30 days" },
  { value: "last_90_days", label: "Last 90 days" },
  { value: "last_12_months", label: "Last 12 months" },
  { value: "custom", label: "Custom dates" },
];

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function addDays(d: Date, days: number): Date {
  const next = new Date(d);
  next.setDate(next.getDate() + days);
  return next;
}

function startOfWeek(d: Date): Date {
  const current = startOfDay(d);
  const dow = current.getDay(); // Sunday = 0.
  return addDays(current, -dow);
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function startOfQuarter(d: Date): Date {
  const quarterMonth = Math.floor(d.getMonth() / 3) * 3;
  return new Date(d.getFullYear(), quarterMonth, 1);
}

function startOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 0, 1);
}

export function resolveReportPeriod(input: ReportPeriodInput): ReportPeriodRange {
  const now = new Date();
  const today = startOfDay(now);

  switch (input.preset) {
    case "all":
      return {
        preset: input.preset,
        startDate: "1900-01-01",
        endDate: "2099-12-31",
        label: "All dates",
      };
    case "today":
      return { preset: input.preset, startDate: iso(today), endDate: iso(today), label: "Today" };
    case "this_week":
      return {
        preset: input.preset,
        startDate: iso(startOfWeek(now)),
        endDate: iso(today),
        label: "This week",
      };
    case "this_month":
      return {
        preset: input.preset,
        startDate: iso(startOfMonth(now)),
        endDate: iso(today),
        label: "This month",
      };
    case "this_quarter":
      return {
        preset: input.preset,
        startDate: iso(startOfQuarter(now)),
        endDate: iso(today),
        label: "This quarter",
      };
    case "this_year":
      return {
        preset: input.preset,
        startDate: iso(startOfYear(now)),
        endDate: iso(today),
        label: "This year",
      };
    case "last_30_days":
      return {
        preset: input.preset,
        startDate: iso(addDays(today, -29)),
        endDate: iso(today),
        label: "Last 30 days",
      };
    case "last_90_days":
      return {
        preset: input.preset,
        startDate: iso(addDays(today, -89)),
        endDate: iso(today),
        label: "Last 90 days",
      };
    case "last_12_months":
      return {
        preset: input.preset,
        startDate: iso(new Date(now.getFullYear() - 1, now.getMonth(), now.getDate())),
        endDate: iso(today),
        label: "Last 12 months",
      };
    case "custom": {
      const startDate = input.customStart || iso(today);
      const endDate = input.customEnd || iso(today);
      return {
        preset: input.preset,
        startDate,
        endDate,
        label: startDate === endDate ? startDate : `${startDate} to ${endDate}`,
      };
    }
  }
}

/**
 * Client-side counterpart to the server's date filtering, for lists that are
 * fetched whole (documents, artifacts). `value` may be a plain `YYYY-MM-DD`
 * or an ISO timestamp — only the date part is compared, so string comparison
 * is safe and timezone-free.
 */
export function isWithinRange(
  value: string | null | undefined,
  range: { startDate: string; endDate: string },
): boolean {
  if (!value) return false;
  const day = value.slice(0, 10);
  return day >= range.startDate && day <= range.endDate;
}
