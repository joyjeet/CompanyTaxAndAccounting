import {
  Badge,
  Body1,
  Caption1,
  Divider,
  Link as FluentLink,
  makeStyles,
  shorthands,
  Spinner,
  Subtitle2,
  Text,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowRight16Regular,
  ArrowUpload24Regular,
  ChatHelp24Regular,
  ChevronRight16Regular,
  Document24Regular,
  Megaphone24Regular,
  Money24Regular,
  Receipt24Regular,
  Sparkle24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import type {
  AgingReportOut,
  BalanceSheetOut,
  CashFlowOut,
  CoaOut,
  DocumentOut,
  PeriodOut,
  ProfitAndLossOut,
} from "../auth/types";
import DashboardCard from "../components/DashboardCard";
import { AreaTrend, BarPair, DonutChart } from "../components/MiniCharts";
import ReportPeriodPicker, { useReportPeriod } from "../components/ReportPeriodPicker";
import { ErrorState } from "../components/States";
import { fmtDate, fmtDateTime, shortId } from "../lib/format";
import { isWithinRange } from "../lib/reportPeriods";

// --------------------------------------------------------------------------- //
// Helpers                                                                     //
// --------------------------------------------------------------------------- //

const num = (s?: string | null): number => (s == null ? 0 : Number(s) || 0);

const money = (n: number, dp = 0): string => {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}$${abs.toLocaleString(undefined, {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })}`;
};

// Pick the most recent locked period; fallback to most recent period overall.
function pickPeriod(periods: PeriodOut[] | undefined): PeriodOut | null {
  if (!periods || periods.length === 0) return null;
  const sorted = [...periods].sort((a, b) => b.end_date.localeCompare(a.end_date));
  return sorted.find((p) => p.is_locked) ?? sorted[0];
}

function greetingFor(d: Date): string {
  const h = d.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

const PALETTE = [
  tokens.colorPaletteGreenForeground2,
  tokens.colorPaletteRedForeground2,
  tokens.colorPaletteBlueForeground2,
  tokens.colorPaletteYellowForeground2,
  tokens.colorPalettePurpleForeground2,
];

// --------------------------------------------------------------------------- //
// Styles                                                                      //
// --------------------------------------------------------------------------- //

const useStyles = makeStyles({
  page: {
    display: "grid",
    rowGap: "20px",
    maxWidth: "1280px",
    marginInline: "auto",
  },
  header: { display: "flex", flexDirection: "column", rowGap: "4px" },
  helloSub: { color: tokens.colorNeutralForeground3 },

  actionRail: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: "12px",
    rowGap: "12px",
    alignItems: "stretch",
  },
  actionChip: {
    display: "flex",
    alignItems: "center",
    columnGap: "10px",
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("10px", "16px"),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    ...shorthands.borderRadius("999px"),
    color: tokens.colorNeutralForeground1,
    textDecoration: "none",
    cursor: "pointer",
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase300,
    boxShadow: tokens.shadow2,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  actionChipIcon: {
    width: "32px",
    height: "32px",
    display: "grid",
    placeItems: "center",
    ...shorthands.borderRadius("50%"),
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    flexShrink: 0,
  },

  glanceLabel: {
    color: tokens.colorNeutralForeground3,
    fontWeight: tokens.fontWeightSemibold,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    fontSize: "11px",
    marginTop: "8px",
    marginBottom: "-8px",
  },

  rowSplit: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
    gap: "16px",
    "@media (max-width: 980px)": { gridTemplateColumns: "1fr" },
  },
  rowTriple: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)",
    gap: "16px",
    "@media (max-width: 1200px)": { gridTemplateColumns: "1fr 1fr" },
    "@media (max-width: 720px)": { gridTemplateColumns: "1fr" },
  },

  bigMoney: {
    fontSize: "32px",
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    lineHeight: 1.1,
    display: "block",
  },

  bankRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingBlock: "10px",
  },

  recentRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    paddingBlock: "10px",
    columnGap: "12px",
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
  },
  recentRowLast: { borderBottom: "none" },
});

// --------------------------------------------------------------------------- //
// PortalHome                                                                  //
// --------------------------------------------------------------------------- //

export default function PortalHome() {
  const styles = useStyles();
  const api = useApi();
  const { identity } = useAuth();
  const clientId = identity?.clientId ?? null;

  // -------------------------- data fetches -------------------------------- //
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.listDocuments() });
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: () => api.listArtifacts() });

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId!),
    enabled: !!clientId,
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId!),
    enabled: !!clientId,
  });

  const period = useMemo(() => pickPeriod(periods.data), [periods.data]);
  const dateFilter = useReportPeriod("all");

  // The API clamps portal users to FINALIZED (locked) days; if nothing in the
  // chosen range is finalized it 403s and we show a friendly empty card.
  const pnl = useQuery({
    queryKey: ["pnl", clientId, dateFilter.query],
    queryFn: () => api.getProfitAndLoss(clientId!, dateFilter.query),
    enabled: !!clientId,
    retry: false,
  });
  const bs = useQuery({
    queryKey: ["bs", clientId, dateFilter.query],
    queryFn: () => api.getBalanceSheet(clientId!, dateFilter.query),
    enabled: !!clientId,
    retry: false,
  });
  const cf = useQuery({
    queryKey: ["cf", clientId, dateFilter.query],
    queryFn: () => api.getCashFlow(clientId!, dateFilter.query),
    enabled: !!clientId,
    retry: false,
  });

  // AR aging — pin to the AR control account 1100 (seeded in the demo COA).
  const arAccount = useMemo(
    () => accounts.data?.find((a: CoaOut) => a.code === "1100"),
    [accounts.data],
  );
  const ar = useQuery({
    queryKey: ["ar-aging", clientId, dateFilter.query, arAccount?.id],
    queryFn: () => api.getArAging(clientId!, dateFilter.query, [arAccount!.code]),
    enabled: !!clientId && !!arAccount,
    retry: false,
  });

  const helloName = identity?.sub ?? "there";
  const today = new Date();

  return (
    <div className={styles.page}>
      {/* ===== Greeting ===== */}
      <div className={styles.header}>
        <Text size={700} weight="semibold">
          {greetingFor(today)}, {helloName}
        </Text>
        <Body1 className={styles.helloSub}>
          Here&apos;s what&apos;s happening with your business —{" "}
          {today.toLocaleDateString(undefined, {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </Body1>
      </div>

      {/* ===== Action chip rail ===== */}
      <ActionRail styles={styles} />

      {/* ===== Period banner ===== */}
      <PeriodBanner period={period} loading={periods.isLoading} />

      {/* ===== Business at a glance ===== */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          columnGap: 12,
          flexWrap: "wrap",
        }}
      >
        <Caption1 className={styles.glanceLabel}>Business at a glance</Caption1>
        <div style={{ display: "flex", columnGap: 8 }}>
          <ReportPeriodPicker state={dateFilter} />
        </div>
      </div>

      {/* Row 1: Sales funnel + Bank accounts */}
      <div className={styles.rowSplit}>
        <SalesGetPaidCard
          ar={ar.data}
          isLoading={ar.isLoading}
          error={ar.error}
          asOf={dateFilter.range.endDate}
          unavailable={ar.isError}
          styles={styles}
        />
        <BankAccountsCard
          bs={bs.data}
          accounts={accounts.data}
          isLoading={bs.isLoading}
          unavailable={bs.isError}
          styles={styles}
        />
      </div>

      {/* Row 2: P&L + Expenses donut + Need help */}
      <div className={styles.rowTriple}>
        <ProfitAndLossCard
          pnl={pnl.data}
          isLoading={pnl.isLoading}
          unavailable={pnl.isError}
          periodLabel={dateFilter.range.label}
          styles={styles}
        />
        <ExpensesDonutCard
          pnl={pnl.data}
          isLoading={pnl.isLoading}
          unavailable={pnl.isError}
        />
        <NeedHelpCard />
      </div>

      {/* Row 3: Cash flow */}
      <CashFlowCard
        cf={cf.data}
        isLoading={cf.isLoading}
        unavailable={cf.isError}
        rangeLabel={dateFilter.range.label}
        rangeStart={dateFilter.range.startDate}
      />

      {/* Row 4: Recent activity */}
      <RecentActivityCard
        docs={docs.data?.filter((d) => isWithinRange(d.received_at, dateFilter.range))}
        isLoading={docs.isLoading}
        error={docs.error as Error | null}
        styles={styles}
      />

      {/* Footer microcopy */}
      {artifacts.data && (
        <Caption1
          style={{
            color: tokens.colorNeutralForeground3,
            textAlign: "center",
            marginTop: 4,
          }}
        >
          {artifacts.data.filter((a) => a.status === "finalized").length} finalized report
          {artifacts.data.filter((a) => a.status === "finalized").length === 1 ? "" : "s"}{" "}
          available ·{" "}
          <Link to="/portal/reports" style={{ color: tokens.colorBrandForeground1 }}>
            View all
          </Link>
        </Caption1>
      )}
    </div>
  );
}

// =========================================================================== //
// Action rail                                                                 //
// =========================================================================== //

function ActionRail({ styles }: { styles: ReturnType<typeof useStyles> }) {
  return (
    <div className={styles.actionRail}>
      <Link to="/portal/documents" className={styles.actionChip}>
        <span className={styles.actionChipIcon}>
          <ArrowUpload24Regular />
        </span>
        Upload bank statement
      </Link>
      <Link to="/portal/documents" className={styles.actionChip}>
        <span className={styles.actionChipIcon}>
          <Receipt24Regular />
        </span>
        Upload receipt
      </Link>
      <Link to="/portal/documents" className={styles.actionChip}>
        <span className={styles.actionChipIcon}>
          <Document24Regular />
        </span>
        Upload bill or invoice
      </Link>
      <Link to="/portal/reports" className={styles.actionChip}>
        <span className={styles.actionChipIcon}>
          <Money24Regular />
        </span>
        View my reports
      </Link>
      <a href="mailto:cpa@example.com" className={styles.actionChip}>
        <span className={styles.actionChipIcon}>
          <ChatHelp24Regular />
        </span>
        Message your CPA
      </a>
    </div>
  );
}

// =========================================================================== //
// Period banner                                                               //
// =========================================================================== //

function PeriodBanner({
  period,
  loading,
}: {
  period: PeriodOut | null;
  loading: boolean;
}) {
  if (loading) return null;
  if (!period) {
    return (
      <DashboardCard overline="Reporting period">
        <Body1>
          Your firm hasn&apos;t set up a reporting period yet. Your dashboard
          will populate once they do.
        </Body1>
      </DashboardCard>
    );
  }
  return (
    <DashboardCard
      overline="Reporting period"
      toolbar={
        <Badge
          appearance={period.is_locked ? "tint" : "outline"}
          color={period.is_locked ? "success" : "warning"}
        >
          {period.is_locked ? "Finalized" : "Open (in progress)"}
        </Badge>
      }
    >
      <Text weight="semibold" size={500}>
        {period.name}
      </Text>
      <Caption1
        style={{ display: "block", color: tokens.colorNeutralForeground3 }}
      >
        {fmtDate(period.start_date)} – {fmtDate(period.end_date)}
      </Caption1>
      {!period.is_locked && (
        <Body1 style={{ marginTop: 8, color: tokens.colorNeutralForeground3 }}>
          The numbers below are a live snapshot. They&apos;ll be marked
          finalized once your firm locks this period.
        </Body1>
      )}
    </DashboardCard>
  );
}

// =========================================================================== //
// Sales & Get Paid (AR aging summary)                                         //
// =========================================================================== //

function SalesGetPaidCard({
  ar,
  isLoading,
  error,
  asOf,
  unavailable,
  styles,
}: {
  ar?: AgingReportOut;
  isLoading: boolean;
  error: unknown;
  asOf: string;
  unavailable: boolean;
  styles: ReturnType<typeof useStyles>;
}) {
  return (
    <DashboardCard
      overline="Sales & Get Paid"
      subtitle={`As of ${fmtDate(asOf)}`}
      footer={
        <Link
          to="/portal/reports"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          View AR aging detail <ChevronRight16Regular />
        </Link>
      }
    >
      {unavailable ? (
        <EmptyHint message="Available after your firm finalizes this period." />
      ) : isLoading ? (
        <Spinner size="small" label="Loading…" />
      ) : error ? (
        <ErrorState error={error} />
      ) : !ar || ar.rows.length === 0 ? (
        <EmptyHint message="No outstanding customer invoices." />
      ) : (
        <>
          <Text className={styles.bigMoney}>{money(num(ar.grand_total))}</Text>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
            Total outstanding from {ar.rows.length} customer account
            {ar.rows.length === 1 ? "" : "s"}
          </Caption1>
          <div style={{ height: 12 }} />
          <BarPair
            rows={ar.totals_by_bucket.map((b) => ({
              label: b.label,
              value: num(b.amount),
              color: bucketColor(b.label),
              rightLabel: money(num(b.amount)),
            }))}
          />
        </>
      )}
    </DashboardCard>
  );
}

function bucketColor(label: string): string {
  const k = label.toLowerCase();
  if (k.includes("current") || k.includes("0-30") || k.includes("0–30"))
    return tokens.colorPaletteGreenForeground2;
  if (k.includes("31") || k.includes("60"))
    return tokens.colorPaletteYellowForeground2;
  if (k.includes("90") || k.includes("over"))
    return tokens.colorPaletteRedForeground2;
  return tokens.colorPaletteBlueForeground2;
}

// =========================================================================== //
// Bank accounts (from balance sheet)                                          //
// =========================================================================== //

function BankAccountsCard({
  bs,
  accounts,
  isLoading,
  unavailable,
  styles,
}: {
  bs?: BalanceSheetOut;
  accounts?: CoaOut[];
  isLoading: boolean;
  unavailable: boolean;
  styles: ReturnType<typeof useStyles>;
}) {
  // Cash-like accounts: codes starting with "10".
  const cashRows = (bs?.assets ?? []).filter((a) => a.code.startsWith("10"));
  const total = cashRows.reduce((s, r) => s + num(r.signed_balance), 0);

  return (
    <DashboardCard
      overline="Bank Accounts"
      footer={
        <Link
          to="/portal/reports"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          View balance sheet <ChevronRight16Regular />
        </Link>
      }
    >
      {unavailable ? (
        <EmptyHint message="Available after your firm finalizes this period." />
      ) : isLoading ? (
        <Spinner size="small" label="Loading…" />
      ) : cashRows.length === 0 ? (
        <EmptyHint
          message={
            accounts && accounts.length > 0
              ? "No cash balances posted yet."
              : "No chart of accounts set up."
          }
        />
      ) : (
        <>
          <Text className={styles.bigMoney}>{money(total)}</Text>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
            Across {cashRows.length} account{cashRows.length === 1 ? "" : "s"}
          </Caption1>
          <div style={{ height: 8 }} />
          {cashRows.slice(0, 4).map((a, i) => (
            <div key={a.account_id}>
              {i > 0 && <Divider />}
              <div className={styles.bankRow}>
                <div>
                  <Text weight="semibold">{a.name}</Text>
                  <Caption1
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    {a.code}
                  </Caption1>
                </div>
                <Text
                  weight="semibold"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {money(num(a.signed_balance))}
                </Text>
              </div>
            </div>
          ))}
        </>
      )}
    </DashboardCard>
  );
}

// =========================================================================== //
// Profit & Loss                                                               //
// =========================================================================== //

function ProfitAndLossCard({
  pnl,
  isLoading,
  unavailable,
  periodLabel,
  styles,
}: {
  pnl?: ProfitAndLossOut;
  isLoading: boolean;
  unavailable: boolean;
  periodLabel?: string;
  styles: ReturnType<typeof useStyles>;
}) {
  const revenue = num(pnl?.total_revenue);
  const expense = num(pnl?.total_expenses);
  const net = num(pnl?.net_income);
  return (
    <DashboardCard
      overline="Profit & Loss"
      subtitle={periodLabel}
      footer={
        <Link
          to="/portal/reports"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          Analyze my P&amp;L <ChevronRight16Regular />
        </Link>
      }
    >
      {unavailable ? (
        <EmptyHint message="Available after your firm finalizes this period." />
      ) : isLoading ? (
        <Spinner size="small" label="Loading…" />
      ) : !pnl ? (
        <EmptyHint message="No P&L data yet." />
      ) : (
        <>
          <Text
            className={styles.bigMoney}
            style={{
              color:
                net >= 0
                  ? tokens.colorPaletteGreenForeground2
                  : tokens.colorPaletteRedForeground2,
            }}
          >
            {money(net)}
          </Text>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
            Net {net >= 0 ? "income" : "loss"} for the period
          </Caption1>
          <div style={{ height: 14 }} />
          <BarPair
            rows={[
              {
                label: "Income",
                value: revenue,
                color: tokens.colorPaletteGreenForeground2,
              },
              {
                label: "Expenses",
                value: expense,
                color: tokens.colorPaletteRedForeground2,
              },
            ]}
          />
        </>
      )}
    </DashboardCard>
  );
}

// =========================================================================== //
// Expenses donut                                                              //
// =========================================================================== //

function ExpensesDonutCard({
  pnl,
  isLoading,
  unavailable,
}: {
  pnl?: ProfitAndLossOut;
  isLoading: boolean;
  unavailable: boolean;
}) {
  const topExpenses = useMemo(() => {
    if (!pnl) return [] as Array<{ label: string; value: number }>;
    return [...pnl.expenses]
      .map((e) => ({ label: e.name, value: Math.abs(num(e.signed_balance)) }))
      .filter((e) => e.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);
  }, [pnl]);

  const total = topExpenses.reduce((s, e) => s + e.value, 0);

  return (
    <DashboardCard
      overline="Expenses"
      subtitle="This period"
      footer={
        <Link
          to="/portal/reports"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          See all expenses <ChevronRight16Regular />
        </Link>
      }
    >
      {unavailable ? (
        <EmptyHint message="Available after your firm finalizes this period." />
      ) : isLoading ? (
        <Spinner size="small" label="Loading…" />
      ) : topExpenses.length === 0 ? (
        <EmptyHint message="No expense activity yet." />
      ) : (
        <div
          style={{
            display: "flex",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <DonutChart
            segments={topExpenses}
            size={140}
            thickness={20}
            centerLabel={money(total)}
            centerSub="total"
          />
          <div
            style={{
              display: "grid",
              rowGap: 6,
              flex: 1,
              minWidth: 120,
            }}
          >
            {topExpenses.map((e, i) => (
              <div
                key={e.label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                  color: tokens.colorNeutralForeground2,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    overflow: "hidden",
                  }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: PALETTE[i % PALETTE.length],
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {e.label}
                  </span>
                </span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>
                  {money(e.value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </DashboardCard>
  );
}

// =========================================================================== //
// Need help                                                                   //
// =========================================================================== //

function NeedHelpCard() {
  return (
    <DashboardCard
      overline="Need a hand?"
      footer={
        <FluentLink href="mailto:cpa@example.com" style={{ fontWeight: 600 }}>
          Message your CPA <ArrowRight16Regular />
        </FluentLink>
      }
    >
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 8,
            background: tokens.colorBrandBackground2,
            color: tokens.colorBrandForeground1,
            display: "grid",
            placeItems: "center",
            flexShrink: 0,
          }}
        >
          <Sparkle24Regular />
        </div>
        <div>
          <Subtitle2 block>Your firm is one click away</Subtitle2>
          <Caption1
            style={{
              color: tokens.colorNeutralForeground3,
              display: "block",
              marginTop: 4,
            }}
          >
            Quick questions? Need a document re-categorized? Drop your CPA a
            note and they&apos;ll see it in their queue.
          </Caption1>
        </div>
      </div>
      <div
        style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6 }}
      >
        <Badge appearance="outline">Reclassify a transaction</Badge>
        <Badge appearance="outline">Request a report</Badge>
        <Badge appearance="outline">Year-end checklist</Badge>
      </div>
    </DashboardCard>
  );
}

// =========================================================================== //
// Cash flow                                                                   //
// =========================================================================== //

function CashFlowCard({
  cf,
  isLoading,
  unavailable,
  rangeLabel,
  rangeStart,
}: {
  cf?: CashFlowOut;
  isLoading: boolean;
  unavailable: boolean;
  rangeLabel: string;
  rangeStart: string;
}) {
  // Build a synthetic 12-point trend from opening → closing cash for the
  // selected period. Until we have monthly periods this is a stand-in shape
  // so the card never renders blank when there IS data.
  const trend = useMemo(() => {
    if (!cf) return [] as number[];
    const open = num(cf.opening_cash);
    const close = num(cf.closing_cash);
    const steps = 12;
    const slope = (close - open) / (steps - 1);
    const range = Math.max(1, Math.abs(close - open));
    return Array.from({ length: steps }, (_, i) => {
      const linear = open + slope * i;
      const wobble = Math.sin(i / 1.7) * range * 0.05;
      return linear + wobble;
    });
  }, [cf]);

  const monthLabels = useMemo(() => {
    const start = new Date(rangeStart);
    if (Number.isNaN(start.getTime())) return [] as string[];
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(start.getFullYear(), start.getMonth() + i, 1);
      return d.toLocaleDateString(undefined, { month: "short" });
    });
  }, [rangeStart]);

  return (
    <DashboardCard
      overline="Cash Flow"
      subtitle={`${rangeLabel} — opening to closing`}
      footer={
        <Link
          to="/portal/reports"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          View cash flow statement <ChevronRight16Regular />
        </Link>
      }
    >
      {unavailable ? (
        <EmptyHint message="Available after your firm finalizes this period." />
      ) : isLoading ? (
        <Spinner size="small" label="Loading…" />
      ) : !cf ? (
        <EmptyHint message="No cash flow data yet." />
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 32,
              flexWrap: "wrap",
              marginBottom: 12,
            }}
          >
            <Stat label="Opening cash" value={money(num(cf.opening_cash))} />
            <Stat
              label="Inflows"
              value={money(num(cf.inflows))}
              color={tokens.colorPaletteGreenForeground2}
            />
            <Stat
              label="Outflows"
              value={money(num(cf.outflows))}
              color={tokens.colorPaletteRedForeground2}
            />
            <Stat
              label="Net change"
              value={money(num(cf.net_change))}
              color={
                num(cf.net_change) >= 0
                  ? tokens.colorPaletteGreenForeground2
                  : tokens.colorPaletteRedForeground2
              }
            />
            <Stat
              label="Closing cash"
              value={money(num(cf.closing_cash))}
              bold
            />
          </div>
          <AreaTrend
            data={trend}
            xLabels={monthLabels}
            height={180}
            formatY={(n) => money(n)}
          />
        </>
      )}
    </DashboardCard>
  );
}

function Stat({
  label,
  value,
  color,
  bold,
}: {
  label: string;
  value: string;
  color?: string;
  bold?: boolean;
}) {
  return (
    <div>
      <Caption1
        style={{ color: tokens.colorNeutralForeground3, display: "block" }}
      >
        {label}
      </Caption1>
      <Text
        weight={bold ? "bold" : "semibold"}
        size={500}
        style={{
          color: color ?? tokens.colorNeutralForeground1,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </Text>
    </div>
  );
}

// =========================================================================== //
// Recent activity                                                             //
// =========================================================================== //

function RecentActivityCard({
  docs,
  isLoading,
  error,
  styles,
}: {
  docs: DocumentOut[] | undefined;
  isLoading: boolean;
  error: Error | null;
  styles: ReturnType<typeof useStyles>;
}) {
  return (
    <DashboardCard
      overline="Recent activity"
      subtitle="Latest documents you've sent to your firm"
      footer={
        <Link
          to="/portal/documents"
          style={{ color: tokens.colorBrandForeground1, fontWeight: 600 }}
        >
          View all documents <ChevronRight16Regular />
        </Link>
      }
    >
      {isLoading && <Spinner size="small" label="Loading…" />}
      {error && <ErrorState error={error} />}
      {docs && docs.length === 0 && (
        <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
          No documents yet.{" "}
          <Link
            to="/portal/documents"
            style={{ color: tokens.colorBrandForeground1 }}
          >
            Upload your first
          </Link>
          .
        </Body1>
      )}
      {docs && docs.length > 0 && (
        <div>
          {docs.slice(0, 6).map((d, i, arr) => (
            <div
              key={d.id}
              className={`${styles.recentRow} ${i === arr.length - 1 ? styles.recentRowLast : ""}`}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  minWidth: 0,
                  flex: 1,
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: tokens.colorNeutralBackground3,
                    color: tokens.colorNeutralForeground2,
                    display: "grid",
                    placeItems: "center",
                    flexShrink: 0,
                  }}
                >
                  <Document24Regular />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Text weight="semibold" truncate wrap={false}>
                    {d.filename ?? "(no filename)"}
                  </Text>
                  <Caption1
                    block
                    style={{
                      color: tokens.colorNeutralForeground3,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {d.kind} · {fmtDateTime(d.received_at)} ·{" "}
                    <code>{shortId(d.sha256)}</code>
                  </Caption1>
                </div>
              </div>
              <Badge
                appearance="tint"
                color={
                  d.ocr_status === "complete"
                    ? "success"
                    : d.ocr_status === "failed"
                      ? "danger"
                      : "warning"
                }
              >
                {d.ocr_status}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </DashboardCard>
  );
}

// =========================================================================== //
// Small shared widgets                                                        //
// =========================================================================== //

function EmptyHint({ message }: { message: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Megaphone24Regular style={{ color: tokens.colorNeutralForeground3 }} />
      <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
        {message}
      </Caption1>
    </div>
  );
}

