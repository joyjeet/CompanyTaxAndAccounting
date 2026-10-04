import { Dropdown, Input, Option } from "@fluentui/react-components";
import { useMemo, useState } from "react";

import { todayIso } from "../lib/format";
import {
  REPORT_PERIOD_OPTIONS,
  type ReportPeriodPreset,
  type ReportPeriodRange,
  resolveReportPeriod,
} from "../lib/reportPeriods";

export interface ReportPeriodState {
  preset: ReportPeriodPreset;
  setPreset: (next: ReportPeriodPreset) => void;
  customStart: string;
  setCustomStart: (next: string) => void;
  customEnd: string;
  setCustomEnd: (next: string) => void;
  range: ReportPeriodRange;
  /** Ready to spread into the range-aware ApiClient report methods. */
  query: { periodStart: string; periodEnd: string };
}

/**
 * Shared date-range state for anything that filters by date. Presets
 * auto-populate start/end; "Custom dates" hands control to the two inputs.
 */
export function useReportPeriod(initial: ReportPeriodPreset = "all"): ReportPeriodState {
  const [preset, setPresetRaw] = useState<ReportPeriodPreset>(initial);
  const [customStart, setCustomStart] = useState(todayIso());
  const [customEnd, setCustomEnd] = useState(todayIso());

  const range = useMemo(
    () => resolveReportPeriod({ preset, customStart, customEnd }),
    [preset, customStart, customEnd],
  );

  const setPreset = (next: ReportPeriodPreset) => {
    setPresetRaw(next);
    // Seed the custom inputs from wherever the user just was, so switching to
    // "Custom dates" starts from a sensible window instead of an empty one.
    if (next === "custom") {
      setCustomStart(range.startDate === "1900-01-01" ? todayIso() : range.startDate);
      setCustomEnd(range.endDate === "2099-12-31" ? todayIso() : range.endDate);
    }
  };

  return {
    preset,
    setPreset,
    customStart,
    setCustomStart,
    customEnd,
    setCustomEnd,
    range,
    query: { periodStart: range.startDate, periodEnd: range.endDate },
  };
}

export default function ReportPeriodPicker({ state }: { state: ReportPeriodState }) {
  return (
    <>
      <Dropdown
        aria-label="Date range"
        value={state.range.label}
        selectedOptions={[state.preset]}
        onOptionSelect={(_, d) =>
          state.setPreset((d.optionValue as ReportPeriodPreset | undefined) ?? "all")
        }
      >
        {REPORT_PERIOD_OPTIONS.map((option) => (
          <Option key={option.value} value={option.value} text={option.label}>
            {option.label}
          </Option>
        ))}
      </Dropdown>
      {state.preset === "custom" && (
        <>
          <Input
            type="date"
            aria-label="From date"
            value={state.customStart}
            onChange={(_, d) => state.setCustomStart(d.value)}
          />
          <Input
            type="date"
            aria-label="To date"
            value={state.customEnd}
            onChange={(_, d) => state.setCustomEnd(d.value)}
          />
        </>
      )}
    </>
  );
}
