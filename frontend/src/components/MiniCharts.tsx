import { tokens } from "@fluentui/react-components";
import type { CSSProperties } from "react";

/**
 * Hand-rolled SVG mini-chart primitives. Kept dependency-free on purpose —
 * the dashboard only needs a few shapes and Recharts/Chart.js would
 * bloat the bundle.
 *
 * All components are responsive: width=100% of parent, height is a fixed
 * prop. Numbers use the page's CSS tokens for color so they blend with
 * Fluent UI.
 */

const PALETTE = [
  tokens.colorPaletteGreenForeground2,    // category 1 (income / good)
  tokens.colorPaletteRedForeground2,      // category 2 (expense / bad)
  tokens.colorPaletteBlueForeground2,
  tokens.colorPaletteYellowForeground2,
  tokens.colorPalettePurpleForeground2,
  tokens.colorPaletteTealForeground2,
  tokens.colorPaletteMarigoldForeground2,
];

// ============================================================================
// DonutChart — a single ring with N segments.
// ============================================================================

export interface DonutSegment {
  label: string;
  value: number;
  color?: string;
}

export function DonutChart({
  segments,
  size = 160,
  thickness = 24,
  centerLabel,
  centerSub,
}: {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerSub?: string;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;

  // If there are no nonzero values, draw a single muted ring.
  if (total <= 0) {
    return (
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={tokens.colorNeutralStroke2}
          strokeWidth={thickness}
        />
        {centerLabel && (
          <text
            x={cx}
            y={cy}
            textAnchor="middle"
            dominantBaseline="central"
            fill={tokens.colorNeutralForeground3}
            fontSize="12"
          >
            no data
          </text>
        )}
      </svg>
    );
  }

  let offset = 0;
  const arcs = segments
    .filter((s) => s.value > 0)
    .map((s, i) => {
      const len = (s.value / total) * circumference;
      const arc = (
        <circle
          key={s.label + i}
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={s.color ?? PALETTE[i % PALETTE.length]}
          strokeWidth={thickness}
          strokeDasharray={`${len} ${circumference}`}
          strokeDashoffset={-offset}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
      );
      offset += len;
      return arc;
    });

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={tokens.colorNeutralStroke2}
        strokeWidth={thickness}
      />
      {arcs}
      {centerLabel && (
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          fill={tokens.colorNeutralForeground1}
          fontSize="18"
          fontWeight="600"
        >
          {centerLabel}
        </text>
      )}
      {centerSub && (
        <text
          x={cx}
          y={cy + 14}
          textAnchor="middle"
          fill={tokens.colorNeutralForeground3}
          fontSize="11"
        >
          {centerSub}
        </text>
      )}
    </svg>
  );
}

// ============================================================================
// BarPair — two horizontal bars stacked vertically. Used for the
// "Income vs Expenses" mini-chart on the P&L card.
// ============================================================================

export function BarPair({
  rows,
  height = 12,
  style,
}: {
  rows: Array<{ label: string; value: number; color?: string; rightLabel?: string }>;
  height?: number;
  style?: CSSProperties;
}) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div style={{ display: "grid", rowGap: 10, ...(style ?? {}) }}>
      {rows.map((r, i) => {
        const pct = (Math.abs(r.value) / max) * 100;
        return (
          <div key={r.label + i} style={{ display: "grid", rowGap: 4 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                color: tokens.colorNeutralForeground2,
              }}
            >
              <span>{r.label}</span>
              <span style={{ fontFamily: tokens.fontFamilyMonospace }}>
                {r.rightLabel ?? fmtMoney(r.value)}
              </span>
            </div>
            <div
              style={{
                position: "relative",
                height,
                background: tokens.colorNeutralBackground3,
                borderRadius: 999,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  height: "100%",
                  width: `${pct}%`,
                  background: r.color ?? PALETTE[i % PALETTE.length],
                  borderRadius: 999,
                  transition: "width 200ms ease-out",
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================================
// AreaTrend — small filled area chart with a baseline. Used for cash flow.
// ============================================================================

export function AreaTrend({
  data,
  height = 140,
  strokeColor,
  fillColor,
  formatY,
  xLabels,
}: {
  data: number[];
  height?: number;
  strokeColor?: string;
  fillColor?: string;
  formatY?: (n: number) => string;
  xLabels?: string[];
}) {
  if (data.length < 2) {
    return (
      <div
        style={{
          height,
          display: "grid",
          placeItems: "center",
          color: tokens.colorNeutralForeground3,
          fontSize: 13,
        }}
      >
        Not enough data points yet.
      </div>
    );
  }
  const w = 600; // viewBox width — actual rendering scales
  const h = height;
  const padTop = 12;
  const padBottom = xLabels ? 22 : 8;
  const padLeft = 40;
  const padRight = 8;
  const innerW = w - padLeft - padRight;
  const innerH = h - padTop - padBottom;

  const min = Math.min(0, ...data);
  const max = Math.max(0, ...data);
  const range = max - min || 1;
  const xStep = innerW / (data.length - 1);
  const yFor = (v: number) => padTop + innerH - ((v - min) / range) * innerH;

  const pts = data.map((v, i) => `${padLeft + i * xStep},${yFor(v)}`);
  const linePath = "M " + pts.join(" L ");
  const areaPath =
    linePath +
    ` L ${padLeft + (data.length - 1) * xStep},${yFor(min)} L ${padLeft},${yFor(min)} Z`;

  const stroke = strokeColor ?? tokens.colorPaletteGreenForeground2;
  const fill = fillColor ?? "color-mix(in srgb, " + stroke + " 18%, transparent)";
  const zeroY = yFor(0);

  return (
    <svg
      width="100%"
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      {/* y-axis tick labels (min, 0, max) */}
      <text x={2} y={yFor(max) + 4} fontSize="10" fill={tokens.colorNeutralForeground3}>
        {formatY ? formatY(max) : Math.round(max).toLocaleString()}
      </text>
      <text x={2} y={zeroY + 4} fontSize="10" fill={tokens.colorNeutralForeground3}>
        0
      </text>
      {min < 0 && (
        <text x={2} y={yFor(min) + 4} fontSize="10" fill={tokens.colorNeutralForeground3}>
          {formatY ? formatY(min) : Math.round(min).toLocaleString()}
        </text>
      )}

      {/* zero baseline */}
      <line
        x1={padLeft}
        x2={padLeft + innerW}
        y1={zeroY}
        y2={zeroY}
        stroke={tokens.colorNeutralStroke2}
        strokeDasharray="3 3"
      />

      {/* filled area */}
      <path d={areaPath} fill={fill} />
      {/* trend line */}
      <path d={linePath} fill="none" stroke={stroke} strokeWidth={2} />

      {/* x-axis labels */}
      {xLabels &&
        xLabels.map((lab, i) => {
          // Show every Nth label to avoid clutter — target ~8 visible labels.
          const stride = Math.max(1, Math.floor(xLabels.length / 8));
          if (i % stride !== 0 && i !== xLabels.length - 1) return null;
          return (
            <text
              key={i}
              x={padLeft + i * xStep}
              y={h - 4}
              textAnchor="middle"
              fontSize="10"
              fill={tokens.colorNeutralForeground3}
            >
              {lab}
            </text>
          );
        })}
    </svg>
  );
}

// ============================================================================
// Tiny shared formatter used by BarPair fallback labels.
// ============================================================================

function fmtMoney(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}
