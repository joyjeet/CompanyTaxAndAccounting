import {
  Badge,
  Body1,
  Button,
  Caption1,
  makeStyles,
  shorthands,
  tokens,
  Text,
} from "@fluentui/react-components";
import {
  ArrowUpload24Regular,
  BookContacts24Regular,
  Document24Regular,
  Money24Regular,
  Receipt24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useApi } from "../../api/useApi";
import type { AccountBalanceOut, CoaOut, PeriodOut } from "../../auth/types";
import Section from "../../components/Section";
import { ErrorState, LoadingState } from "../../components/States";
import { fmtDate, fmtDateTime, shortId } from "../../lib/format";

const useStyles = makeStyles({
  page: {
    display: "grid",
    rowGap: "16px",
  },
  shortcuts: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
    gap: "12px",
  },
  shortcut: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.padding("14px", "10px"),
    display: "grid",
    justifyItems: "center",
    rowGap: "8px",
    textDecoration: "none",
    color: tokens.colorNeutralForeground1,
    boxShadow: tokens.shadow2,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
    },
  },
  shortcutIcon: {
    width: "44px",
    height: "44px",
    display: "grid",
    placeItems: "center",
    color: tokens.colorBrandForeground1,
    backgroundColor: tokens.colorBrandBackground2,
    ...shorthands.borderRadius("50%"),
  },
  cards: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
    gap: "16px",
  },
  card: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.padding("14px"),
    boxShadow: tokens.shadow2,
    minHeight: "210px",
    display: "grid",
    alignContent: "start",
    rowGap: "10px",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  cardTitle: {
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
  },
  listRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    ...shorthands.padding("6px", "0"),
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
  },
  donut: {
    width: "92px",
    height: "92px",
    borderRadius: "50%",
    backgroundImage: `conic-gradient(${tokens.colorBrandBackground} 0deg 310deg, ${tokens.colorNeutralBackground4} 310deg 360deg)`,
    display: "grid",
    placeItems: "center",
    marginBottom: "6px",
  },
  donutInner: {
    width: "44px",
    height: "44px",
    borderRadius: "50%",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  moneyBig: {
    fontSize: tokens.fontSizeHero800,
    fontWeight: tokens.fontWeightSemibold,
    lineHeight: tokens.lineHeightHero800,
  },
});

function money(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function num(v: string | undefined | null): number {
  if (!v) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function pickLatestPeriod(periods: PeriodOut[]): PeriodOut | null {
  if (!periods.length) return null;
  const sorted = [...periods].sort((a, b) => b.end_date.localeCompare(a.end_date));
  return sorted[0] ?? null;
}

function looksLikeBankAccount(row: AccountBalanceOut): boolean {
  const t = `${row.code} ${row.name}`.toLowerCase();
  return t.includes("cash") || t.includes("bank") || t.includes("checking") || t.includes("savings");
}

export default function OverviewTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });
  const entries = useQuery({
    queryKey: ["entries", clientId],
    queryFn: () => api.listJournalEntries(clientId),
  });
  const docs = useQuery({
    queryKey: ["documents", clientId],
    queryFn: () => api.listDocuments(),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts"],
    queryFn: () => api.listArtifacts(),
  });

  const periodRows = periods.data ?? [];
  const latestPeriod = pickLatestPeriod(periodRows);
  const periodId = latestPeriod?.id ?? null;

  const pnl = useQuery({
    queryKey: ["pnl", clientId, periodId],
    queryFn: () => api.getProfitAndLoss(clientId, periodId!),
    enabled: !!periodId,
    retry: false,
  });
  const bs = useQuery({
    queryKey: ["bs", clientId, periodId],
    queryFn: () => api.getBalanceSheet(clientId, periodId!),
    enabled: !!periodId,
    retry: false,
  });
  const ar = useQuery({
    queryKey: ["ar", clientId, periodId],
    queryFn: () => api.getArAging(clientId, periodId!),
    enabled: !!periodId,
    retry: false,
  });

  const err = periods.error || accounts.error || entries.error || docs.error;
  if (err) return <ErrorState error={err} />;
  const loading =
    periods.isLoading || accounts.isLoading || entries.isLoading || artifacts.isLoading || docs.isLoading;
  if (loading) return <LoadingState />;

  const clientArtifacts = (artifacts.data ?? []).filter((a) => a.client_id === clientId);
  const clientDocs = (docs.data ?? []).filter((d) => d.client_id === clientId);
  const accountRows = accounts.data ?? [];
  const journalRows = entries.data ?? [];

  const netIncome = num(pnl.data?.net_income);
  const totalRevenue = num(pnl.data?.total_revenue);
  const totalExpenses = num(pnl.data?.total_expenses);
  const arTotal = num(ar.data?.grand_total);

  const assetRows = bs.data?.assets ?? [];
  const bankRows = assetRows.filter(looksLikeBankAccount).slice(0, 4);
  const fallbackBank = accountRows
    .filter((a: CoaOut) => a.account_type === "asset" && a.is_active)
    .slice(0, 4)
    .map((a: CoaOut) => ({ code: a.code, name: a.name, signed_balance: "0" }));

  const recentDocs = [...clientDocs]
    .sort((a, b) => b.received_at.localeCompare(a.received_at))
    .slice(0, 4);

  return (
    <div className={styles.page}>
      <Section
        title="Client dashboard"
        subtitle="Quick accounting snapshot and actions"
      >
        <div className={styles.shortcuts}>
          <Link to={`/clients/${clientId}/documents`} className={styles.shortcut}>
            <div className={styles.shortcutIcon}><ArrowUpload24Regular /></div>
            <Text weight="semibold">Upload file</Text>
          </Link>
          <Link to={`/clients/${clientId}/entries`} className={styles.shortcut}>
            <div className={styles.shortcutIcon}><Receipt24Regular /></div>
            <Text weight="semibold">Record expense</Text>
          </Link>
          <Link to={`/clients/${clientId}/statements`} className={styles.shortcut}>
            <div className={styles.shortcutIcon}><Money24Regular /></div>
            <Text weight="semibold">Bank statements</Text>
          </Link>
          <Link to={`/clients/${clientId}/reports`} className={styles.shortcut}>
            <div className={styles.shortcutIcon}><Document24Regular /></div>
            <Text weight="semibold">Reports</Text>
          </Link>
        </div>
      </Section>

      <div className={styles.cards}>
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Bank accounts</Text>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>As of {latestPeriod?.end_date ?? "-"}</Caption1>
          </div>
          {(bankRows.length > 0 ? bankRows : fallbackBank).map((r) => (
            <div className={styles.listRow} key={`${r.code}-${r.name}`}>
              <div>
                <Text weight="semibold">{r.name}</Text>
                <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>{r.code}</Caption1>
              </div>
              <Text weight="semibold">{money(num(r.signed_balance))}</Text>
            </div>
          ))}
          {(bankRows.length === 0 && fallbackBank.length === 0) && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>No bank or cash accounts found.</Body1>
          )}
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Profit and loss</Text>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>{latestPeriod?.name ?? "Current"}</Caption1>
          </div>
          <Text className={styles.moneyBig}>{money(netIncome)}</Text>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Net profit to date</Caption1>
          <div className={styles.listRow}>
            <Text>Income</Text>
            <Badge appearance="filled" color="success">{money(totalRevenue)}</Badge>
          </div>
          <div className={styles.listRow}>
            <Text>Expenses</Text>
            <Badge appearance="filled" color="danger">{money(totalExpenses)}</Badge>
          </div>
          <Link to={`/clients/${clientId}/reports`} style={{ color: tokens.colorBrandForeground1 }}>
            Open full reports
          </Link>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Accounts receivable</Text>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>As of today</Caption1>
          </div>
          <Text className={styles.moneyBig}>{money(arTotal)}</Text>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
            Based on AR aging report
          </Caption1>
          <div className={styles.donut}><div className={styles.donutInner} /></div>
          <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
            Journal entries posted: {journalRows.length}
          </Body1>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Recent uploads</Text>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Last documents</Caption1>
          </div>
          {recentDocs.length === 0 && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>No files uploaded for this client yet.</Body1>
          )}
          {recentDocs.map((d) => (
            <div className={styles.listRow} key={d.id}>
              <div>
                <Text weight="semibold">{d.filename ?? "(no filename)"}</Text>
                <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>{fmtDateTime(d.received_at)}</Caption1>
              </div>
              <Badge
                appearance="tint"
                color={d.ocr_status === "complete" ? "success" : d.ocr_status === "failed" ? "danger" : "warning"}
              >
                {d.ocr_status}
              </Badge>
            </div>
          ))}
          <Link to={`/clients/${clientId}/documents`} style={{ color: tokens.colorBrandForeground1 }}>
            View all documents
          </Link>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Quick metrics</Text>
            <BookContacts24Regular />
          </div>
          <div className={styles.listRow}>
            <Text>Periods</Text>
            <Badge appearance="filled" color="brand">{periodRows.length}</Badge>
          </div>
          <div className={styles.listRow}>
            <Text>Accounts</Text>
            <Badge appearance="filled" color="brand">{accountRows.length}</Badge>
          </div>
          <div className={styles.listRow}>
            <Text>Artifacts</Text>
            <Badge appearance="filled" color="brand">{clientArtifacts.length}</Badge>
          </div>
          <div className={styles.listRow}>
            <Text>Client ID</Text>
            <Caption1><code>{shortId(clientId)}</code></Caption1>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <Text className={styles.cardTitle}>Upload and create</Text>
            <ArrowUpload24Regular />
          </div>
          <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
            Add a new file for OCR classification and draft generation.
          </Body1>
          <Link to={`/clients/${clientId}/documents`} style={{ textDecoration: "none" }}>
            <Button appearance="primary">Select a file</Button>
          </Link>
          {latestPeriod && (
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
              Current period: {latestPeriod.name} ({fmtDate(latestPeriod.start_date)} to {fmtDate(latestPeriod.end_date)})
            </Caption1>
          )}
        </div>

      </div>
    </div>
  );
}
