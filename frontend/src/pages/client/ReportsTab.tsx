/**
 * Reports tab — PART C client-facing reports.
 *
 * Adds, beyond the existing Statements tab (TB / P&L / BS / CF):
 *
 *   • General Ledger   — open any account and see every line that moved it,
 *                        with a running balance.
 *   • AR Aging         — receivables bucketed 0-30 / 31-60 / 61-90 / 90+.
 *   • AP Aging         — payables, same buckets.
 *   • Rollup tree      — COA hierarchy with parent subtotals computed
 *                        deterministically from leaf postings.
 *   • Drill-down       — click any figure to see the underlying journal lines.
 *
 * All numbers come from the backend `/statements/*` endpoints, which compute
 * them in SQL from POSTED journal entries (no AI, no free-hand math). The
 * portal sees these reports only after the firm has locked the period — that
 * gate is enforced server-side; here we just surface the resulting 403.
 */
import {
  Badge,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Option,
  Tab,
  TabList,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toaster,
  Tooltip,
  makeStyles,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { ChevronDownRegular, ChevronRightRegular, OpenRegular } from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDate, fmtMoney, shortId, todayIso } from "../../lib/format";
import {
  REPORT_PERIOD_OPTIONS,
  type ReportPeriodPreset,
  resolveReportPeriod,
} from "../../lib/reportPeriods";
import type { RollupNodeOut, RollupTreeOut } from "../../auth/types";

type ReportTab = "gl" | "ar" | "ap" | "rollup";

const useStyles = makeStyles({
  toolbar: {
    display: "flex",
    columnGap: "12px",
    alignItems: "center",
    marginBottom: "12px",
    flexWrap: "wrap",
  },
  num: {
    textAlign: "right",
    fontFamily: tokens.fontFamilyMonospace,
  },
  totalRow: {
    fontWeight: tokens.fontWeightSemibold,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  parentRow: {
    backgroundColor: tokens.colorNeutralBackground2,
    fontWeight: tokens.fontWeightSemibold,
  },
  linkLike: {
    cursor: "pointer",
    color: tokens.colorBrandForeground1,
    textDecoration: "underline",
  },
  treeToggle: {
    cursor: "pointer",
    border: "none",
    background: "none",
    padding: "0 4px",
    color: tokens.colorNeutralForeground2,
  },
  drillDialog: {
    minWidth: "640px",
    maxWidth: "90vw",
  },
});

export default function ReportsTab({
  clientId,
  portalView = false,
}: {
  clientId: string;
  /**
   * When true: filter the period dropdown to LOCKED periods only (the only
   * ones a portal user can read — the backend enforces this). Set by
   * `PortalReports`; firm-side `ClientDetail` leaves it false.
   */
  portalView?: boolean;
}) {
  const styles = useStyles();
  const api = useApi();
  const toasterId = useId("reports-toaster");
  // Toasts are wired but unused for now — pulled in pre-emptively so the
  // drill-down dialog and future actions can dispatch without ceremony.
  useToastController(toasterId);

  const [tab, setTab] = useState<ReportTab>("gl");
  const [periodId, setPeriodId] = useState<string>("");
  const [periodPreset, setPeriodPreset] = useState<ReportPeriodPreset>("all");
  const [customStart, setCustomStart] = useState(todayIso());
  const [customEnd, setCustomEnd] = useState(todayIso());
  const [accountId, setAccountId] = useState<string>(""); // for general ledger
  const [arCodes, setArCodes] = useState<string>("1100");
  const [apCodes, setApCodes] = useState<string>("2000");
  const [rollupScope, setRollupScope] =
    useState<"trial_balance" | "balance_sheet" | "profit_and_loss">("trial_balance");

  // Drill-down dialog state.
  const [drillAccountId, setDrillAccountId] = useState<string | null>(null);

  const periods = useQuery({
    queryKey: ["periods", clientId, portalView],
    queryFn: async () => {
      const ps = await api.listPeriods(clientId);
      const visible = ps.filter((p) => (portalView ? p.is_locked : true));
      if (portalView && visible.length > 0 && !periodId) setPeriodId(visible[0].id);
      return visible;
    },
    enabled: portalView,
  });

  const accounts = useQuery({
    queryKey: ["coa", clientId],
    queryFn: async () => {
      const rows = await api.listAccounts(clientId);
      if (!accountId && rows.length > 0) setAccountId(rows[0].id);
      return rows;
    },
  });

  const reportPeriod = resolveReportPeriod({
    preset: periodPreset,
    customStart,
    customEnd,
  });
  const rangeQuery = {
    periodStart: reportPeriod.startDate,
    periodEnd: reportPeriod.endDate,
  };
  const periodQuery = portalView
    ? { periodId }
    : rangeQuery;

  const gl = useQuery({
    queryKey: ["gl", clientId, periodQuery, accountId],
    queryFn: () => api.getGeneralLedger(clientId, periodQuery, accountId),
    enabled: !!accountId && tab === "gl" && (portalView ? !!periodId : true),
  });

  const ar = useQuery({
    queryKey: ["ar-aging", clientId, periodQuery, arCodes],
    queryFn: () =>
      api.getArAging(
        clientId,
        periodQuery,
        arCodes.split(",").map((c) => c.trim()).filter(Boolean),
      ),
    enabled: tab === "ar" && (portalView ? !!periodId : true),
  });

  const ap = useQuery({
    queryKey: ["ap-aging", clientId, periodQuery, apCodes],
    queryFn: () =>
      api.getApAging(
        clientId,
        periodQuery,
        apCodes.split(",").map((c) => c.trim()).filter(Boolean),
      ),
    enabled: tab === "ap" && (portalView ? !!periodId : true),
  });

  const rollup = useQuery({
    queryKey: ["rollup", clientId, periodQuery, rollupScope],
    queryFn: () => api.getAccountRollup(clientId, periodQuery, rollupScope),
    enabled: tab === "rollup" && (portalView ? !!periodId : true),
  });

  const drill = useQuery({
    queryKey: ["drill", clientId, periodQuery, drillAccountId],
    queryFn: () =>
      api.getAccountActivity(clientId, periodQuery, drillAccountId as string),
    enabled: !!drillAccountId && (portalView ? !!periodId : true),
  });

  if (portalView && periods.isLoading) return <LoadingState />;
  if (portalView && periods.error) return <ErrorState error={periods.error} />;
  if (portalView && (!periods.data || periods.data.length === 0)) {
    return (
      <EmptyState
        title={portalView ? "No finalized reports yet" : "No periods"}
        description={
          portalView
            ? "Your firm hasn't finalized (locked) any periods yet. Live reports become visible here once a period is closed."
            : "Create a period before viewing reports."
        }
      />
    );
  }

  const selectedPeriod = portalView ? periods.data?.find((p) => p.id === periodId) : null;
  const periodLabel = selectedPeriod
    ? `${selectedPeriod.name} (${fmtDate(selectedPeriod.start_date)} – ${fmtDate(selectedPeriod.end_date)})`
    : reportPeriod.label;
  const selectedAccount = accounts.data?.find((a) => a.id === accountId);
  const accountLabel = selectedAccount
    ? `${selectedAccount.code} ${selectedAccount.name}`
    : "";

  return (
    <div>
      <Toaster toasterId={toasterId} />

      <div className={styles.toolbar}>
        {portalView ? (
          <>
            <Dropdown
              value={periodLabel}
              selectedOptions={periodId ? [periodId] : []}
              onOptionSelect={(_, d) => d.optionValue && setPeriodId(d.optionValue)}
            >
              {periods.data?.map((p) => (
                <Option
                  key={p.id}
                  value={p.id}
                  text={`${p.name} (${fmtDate(p.start_date)} – ${fmtDate(p.end_date)})`}
                >
                  {p.name} ({fmtDate(p.start_date)} – {fmtDate(p.end_date)})
                  {p.is_locked ? " · locked" : " · open"}
                </Option>
              ))}
            </Dropdown>
            {selectedPeriod && (
              <Badge
                appearance="tint"
                color={selectedPeriod.is_locked ? "success" : "warning"}
              >
                {selectedPeriod.is_locked ? "Finalized (locked)" : "Draft (open)"}
              </Badge>
            )}
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
              Reports below cover periods your firm has finalized (locked).
            </Caption1>
          </>
        ) : (
          <>
            <Dropdown
              value={periodLabel}
              selectedOptions={[periodPreset]}
              onOptionSelect={(_, d) => {
                const next = (d.optionValue as ReportPeriodPreset | undefined) ?? "all";
                setPeriodPreset(next);
                if (next === "custom") {
                  setCustomStart(todayIso());
                  setCustomEnd(todayIso());
                }
              }}
            >
              {REPORT_PERIOD_OPTIONS.map((option) => (
                <Option key={option.value} value={option.value} text={option.label}>
                  {option.label}
                </Option>
              ))}
            </Dropdown>
            {periodPreset === "custom" && (
              <>
                <Input type="date" value={customStart} onChange={(_, d) => setCustomStart(d.value)} />
                <Input type="date" value={customEnd} onChange={(_, d) => setCustomEnd(d.value)} />
              </>
            )}
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
              Reports below use the selected date range.
            </Caption1>
          </>
        )}
      </div>

      <TabList
        selectedValue={tab}
        onTabSelect={(_, d) => setTab(d.value as ReportTab)}
      >
        <Tab value="gl">General ledger</Tab>
        <Tab value="ar">AR aging</Tab>
        <Tab value="ap">AP aging</Tab>
        <Tab value="rollup">Rollup tree</Tab>
      </TabList>

      <div style={{ marginTop: 16 }}>
        {tab === "gl" && (
          <Section
            title="General ledger"
            subtitle="Every posted line that moved a chosen account, with a running balance."
            help={{
              title: "What is the general ledger?",
              body: (
                <>
                  Pick an account from the dropdown — the table below lists every
                  posted journal line that touched it in this period, in date
                  order, with a running balance after each line.
                  <br /><br />
                  <b>Opening balance</b> is the signed balance carried in from
                  before the period; <b>Closing balance</b> is what comes out
                  the other side. Both are signed at the account's natural
                  normal balance (Cash positive when there's cash, etc.).
                </>
              ),
            }}
            toolbar={
              accounts.data && (
                <Dropdown
                  value={accountLabel}
                  selectedOptions={accountId ? [accountId] : []}
                  onOptionSelect={(_, d) => d.optionValue && setAccountId(d.optionValue)}
                  style={{ minWidth: 280 }}
                >
                  {accounts.data.map((a) => (
                    <Option key={a.id} value={a.id} text={`${a.code} ${a.name}`}>
                      {a.code} — {a.name} ({a.account_type})
                    </Option>
                  ))}
                </Dropdown>
              )
            }
          >
            {gl.isLoading && <LoadingState />}
            {gl.error && <ErrorState error={gl.error} />}
            {gl.data && (
              <>
                <div style={{ marginBottom: 8, display: "flex", gap: 24 }}>
                  <Text>
                    <b>Opening:</b> {fmtMoney(gl.data.opening_balance)}
                  </Text>
                  <Text>
                    <b>Closing:</b> {fmtMoney(gl.data.closing_balance)}
                  </Text>
                  <Text style={{ color: tokens.colorNeutralForeground3 }}>
                    {gl.data.rows.length} posted line{gl.data.rows.length === 1 ? "" : "s"}
                  </Text>
                </div>
                {gl.data.rows.length === 0 ? (
                  <EmptyState
                    title="No activity in this period"
                    description="Pick a different period or account, or post some entries first."
                  />
                ) : (
                  <Table size="small">
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Date</TableHeaderCell>
                        <TableHeaderCell>Memo / description</TableHeaderCell>
                        <TableHeaderCell className={styles.num}>Debit</TableHeaderCell>
                        <TableHeaderCell className={styles.num}>Credit</TableHeaderCell>
                        <TableHeaderCell className={styles.num}>Running</TableHeaderCell>
                        <TableHeaderCell>Entry</TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {gl.data.rows.map((r) => (
                        <TableRow key={r.line_id}>
                          <TableCell>{fmtDate(r.entry_date)}</TableCell>
                          <TableCell>
                            {r.line_description ?? r.memo ?? (
                              <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                                (no description)
                              </Caption1>
                            )}
                          </TableCell>
                          <TableCell className={styles.num}>
                            {Number(r.debit) > 0 ? fmtMoney(r.debit) : ""}
                          </TableCell>
                          <TableCell className={styles.num}>
                            {Number(r.credit) > 0 ? fmtMoney(r.credit) : ""}
                          </TableCell>
                          <TableCell className={styles.num}>
                            {fmtMoney(r.running_balance)}
                          </TableCell>
                          <TableCell>
                            <code>{shortId(r.entry_id)}</code>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </>
            )}
          </Section>
        )}

        {tab === "ar" && (
          <AgingPanel
            title="AR aging"
            subtitle="Outstanding receivables grouped by age."
            codes={arCodes}
            setCodes={setArCodes}
            helpBody={
              <>
                Receivables (money owed to you) are bucketed by the age of
                each posted line on the AR account, computed as
                <i> period-end minus entry-date</i>. Buckets are 0-30, 31-60,
                61-90, and 90+ days. Payments credited against AR cancel the
                invoice in the same bucket.
                <br /><br />
                Without an invoice subledger, aging is by entry-date — when a
                proper invoice/due-date subledger is added, this will switch
                to age-by-due-date automatically.
              </>
            }
            placeholder="comma-separated AR account codes (default: 1100)"
            query={ar}
            onDrillAccount={(id) => setDrillAccountId(id)}
            styles={styles}
          />
        )}

        {tab === "ap" && (
          <AgingPanel
            title="AP aging"
            subtitle="Outstanding payables grouped by age."
            codes={apCodes}
            setCodes={setApCodes}
            helpBody={
              <>
                Payables (money you owe vendors) are bucketed by the age of
                each posted line on the AP account. Buckets are 0-30, 31-60,
                61-90, and 90+ days. Vendor payments debited against AP
                cancel the bill in the same bucket.
              </>
            }
            placeholder="comma-separated AP account codes (default: 2000)"
            query={ap}
            onDrillAccount={(id) => setDrillAccountId(id)}
            styles={styles}
          />
        )}

        {tab === "rollup" && (
          <Section
            title="Account rollup tree"
            subtitle="COA hierarchy with parent subtotals computed from leaf postings."
            help={{
              title: "What is the rollup tree?",
              body: (
                <>
                  Shows the chart of accounts as a tree. <b>Parent</b>{" "}
                  (non-leaf) accounts display the sum of all leaf descendants
                  — they never have direct postings themselves (leaf-only
                  posting is enforced by the system). Click any account name
                  to drill down to the underlying journal lines.
                </>
              ),
            }}
            toolbar={
              <Dropdown
                value={
                  rollupScope === "trial_balance"
                    ? "Trial balance"
                    : rollupScope === "balance_sheet"
                    ? "Balance sheet"
                    : "Profit & loss"
                }
                selectedOptions={[rollupScope]}
                onOptionSelect={(_, d) =>
                  d.optionValue &&
                  setRollupScope(d.optionValue as typeof rollupScope)
                }
              >
                <Option value="trial_balance">Trial balance</Option>
                <Option value="balance_sheet">Balance sheet</Option>
                <Option value="profit_and_loss">Profit &amp; loss</Option>
              </Dropdown>
            }
          >
            {rollup.isLoading && <LoadingState />}
            {rollup.error && <ErrorState error={rollup.error} />}
            {rollup.data && (
              <RollupTree
                tree={rollup.data}
                onDrill={(id) => setDrillAccountId(id)}
                styles={styles}
              />
            )}
          </Section>
        )}
      </div>

      <DrillDownDialog
        accountId={drillAccountId}
        periodId={periodId}
        query={drill}
        styles={styles}
        onClose={() => setDrillAccountId(null)}
      />
    </div>
  );
}


// --------------------------------------------------------------------------- //
// Aging panel
// --------------------------------------------------------------------------- //
type AgingQueryType = ReturnType<typeof useQuery<import("../../auth/types").AgingReportOut>>;

function AgingPanel({
  title,
  subtitle,
  codes,
  setCodes,
  helpBody,
  placeholder,
  query,
  onDrillAccount,
  styles,
}: {
  title: string;
  subtitle: string;
  codes: string;
  setCodes: (v: string) => void;
  helpBody: React.ReactNode;
  placeholder: string;
  query: AgingQueryType;
  onDrillAccount: (accountId: string) => void;
  styles: ReturnType<typeof useStyles>;
}) {
  return (
    <Section
      title={title}
      subtitle={subtitle}
      help={{ title, body: helpBody }}
      toolbar={
        <Input
          value={codes}
          onChange={(_, d) => setCodes(d.value)}
          placeholder={placeholder}
          style={{ minWidth: 280 }}
        />
      }
    >
      {query.isLoading && <LoadingState />}
      {query.error && <ErrorState error={query.error} />}
      {query.data && (
        <>
          {query.data.rows.length === 0 ? (
            <EmptyState
              title="Nothing outstanding"
              description="No open balances on the chosen accounts as of the period end."
            />
          ) : (
            <Table size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>Account</TableHeaderCell>
                  {query.data.totals_by_bucket.map((b) => (
                    <TableHeaderCell key={b.label} className={styles.num}>
                      {b.label}
                    </TableHeaderCell>
                  ))}
                  <TableHeaderCell className={styles.num}>Total</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.rows.map((row) => (
                  <TableRow key={row.account_id}>
                    <TableCell>
                      <Tooltip content="Drill down to underlying entries" relationship="label">
                        <span
                          className={styles.linkLike}
                          onClick={() => onDrillAccount(row.account_id)}
                        >
                          <code>{row.account_code}</code> {row.account_name}
                        </span>
                      </Tooltip>
                    </TableCell>
                    {row.buckets.map((b) => (
                      <TableCell key={b.label} className={styles.num}>
                        {fmtMoney(b.amount)}
                      </TableCell>
                    ))}
                    <TableCell className={styles.num}>
                      <Text weight="bold">{fmtMoney(row.total)}</Text>
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow className={styles.totalRow}>
                  <TableCell><Text weight="bold">Totals</Text></TableCell>
                  {query.data.totals_by_bucket.map((b) => (
                    <TableCell key={b.label} className={styles.num}>
                      <Text weight="bold">{fmtMoney(b.amount)}</Text>
                    </TableCell>
                  ))}
                  <TableCell className={styles.num}>
                    <Text weight="bold">{fmtMoney(query.data.grand_total)}</Text>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          )}
        </>
      )}
    </Section>
  );
}


// --------------------------------------------------------------------------- //
// Rollup tree (collapsible)
// --------------------------------------------------------------------------- //
function RollupTree({
  tree,
  onDrill,
  styles,
}: {
  tree: RollupTreeOut;
  onDrill: (accountId: string) => void;
  styles: ReturnType<typeof useStyles>;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const rows: React.ReactNode[] = [];

  function render(node: RollupNodeOut, depth: number, parentCollapsed: boolean): void {
    if (parentCollapsed) return;
    const isCollapsed = collapsed.has(node.account_id);
    const hasChildren = node.children.length > 0;
    rows.push(
      <TableRow key={node.account_id} className={node.is_leaf ? "" : styles.parentRow}>
        <TableCell>
          <span style={{ paddingLeft: depth * 16 }}>
            {hasChildren ? (
              <button
                className={styles.treeToggle}
                onClick={() => toggle(node.account_id)}
                aria-label={isCollapsed ? "Expand" : "Collapse"}
              >
                {isCollapsed ? <ChevronRightRegular /> : <ChevronDownRegular />}
              </button>
            ) : (
              <span style={{ display: "inline-block", width: 24 }} />
            )}
            <span
              className={styles.linkLike}
              onClick={() => onDrill(node.account_id)}
              title="Drill down to journal entries"
            >
              <code>{node.code}</code> {node.name}
            </span>
            {!node.is_leaf && (
              <Badge
                appearance="tint"
                color="informative"
                size="small"
                style={{ marginLeft: 6 }}
              >
                rollup
              </Badge>
            )}
          </span>
        </TableCell>
        <TableCell>{node.account_type}</TableCell>
        <TableCell className={styles.num}>{fmtMoney(node.debit_total)}</TableCell>
        <TableCell className={styles.num}>{fmtMoney(node.credit_total)}</TableCell>
        <TableCell className={styles.num}>
          <Text weight={node.is_leaf ? "regular" : "semibold"}>
            {fmtMoney(node.signed_balance)}
          </Text>
        </TableCell>
      </TableRow>,
    );
    for (const c of node.children) {
      render(c, depth + 1, isCollapsed);
    }
  }
  for (const root of tree.roots) render(root, 0, false);

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No accounts in scope"
        description="Pick a different period or scope."
      />
    );
  }
  return (
    <Table size="small">
      <TableHeader>
        <TableRow>
          <TableHeaderCell>Account</TableHeaderCell>
          <TableHeaderCell>Type</TableHeaderCell>
          <TableHeaderCell className={styles.num}>Debit</TableHeaderCell>
          <TableHeaderCell className={styles.num}>Credit</TableHeaderCell>
          <TableHeaderCell className={styles.num}>Balance</TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>{rows}</TableBody>
    </Table>
  );
}


// --------------------------------------------------------------------------- //
// Drill-down dialog
// --------------------------------------------------------------------------- //
type DrillQueryType = ReturnType<
  typeof useQuery<import("../../auth/types").DrillDownOut>
>;

function DrillDownDialog({
  accountId,
  periodId,
  query,
  styles,
  onClose,
}: {
  accountId: string | null;
  periodId: string;
  query: DrillQueryType;
  styles: ReturnType<typeof useStyles>;
  onClose: () => void;
}) {
  const open = !!accountId && !!periodId;
  return (
    <Dialog
      open={open}
      onOpenChange={(_, d) => {
        if (!d.open) onClose();
      }}
    >
      <DialogSurface className={styles.drillDialog}>
        <DialogBody>
          <DialogTitle>
            <OpenRegular style={{ marginRight: 6 }} />
            {query.data
              ? `Drill-down: ${query.data.account_code} ${query.data.account_name}`
              : "Drill-down"}
          </DialogTitle>
          <DialogContent>
            {query.isLoading && <LoadingState />}
            {query.error && <ErrorState error={query.error} />}
            {query.data && (
              <>
                <Caption1 block style={{ marginBottom: 8 }}>
                  {query.data.is_rollup
                    ? `Rollup of ${query.data.leaf_account_ids.length} leaf account(s) `
                    : "Leaf account "}
                  · {query.data.lines.length} posted line(s) ·{" "}
                  signed total <b>{fmtMoney(query.data.signed_total)}</b>{" "}
                  (D {fmtMoney(query.data.total_debit)} / C {fmtMoney(query.data.total_credit)})
                </Caption1>
                {query.data.lines.length === 0 ? (
                  <EmptyState
                    title="No lines in this period"
                    description="This account had no posted activity during the period."
                  />
                ) : (
                  <Table size="small">
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Date</TableHeaderCell>
                        <TableHeaderCell>Account</TableHeaderCell>
                        <TableHeaderCell>Memo / description</TableHeaderCell>
                        <TableHeaderCell className={styles.num}>Debit</TableHeaderCell>
                        <TableHeaderCell className={styles.num}>Credit</TableHeaderCell>
                        <TableHeaderCell>Entry</TableHeaderCell>
                        <TableHeaderCell>Source</TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {query.data.lines.map((ln) => (
                        <TableRow key={ln.line_id}>
                          <TableCell>{fmtDate(ln.entry_date)}</TableCell>
                          <TableCell>
                            <code>{ln.account_code}</code> {ln.account_name}
                          </TableCell>
                          <TableCell>
                            {ln.line_description ?? ln.memo ?? (
                              <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                                (no description)
                              </Caption1>
                            )}
                          </TableCell>
                          <TableCell className={styles.num}>
                            {Number(ln.debit) > 0 ? fmtMoney(ln.debit) : ""}
                          </TableCell>
                          <TableCell className={styles.num}>
                            {Number(ln.credit) > 0 ? fmtMoney(ln.credit) : ""}
                          </TableCell>
                          <TableCell><code>{shortId(ln.entry_id)}</code></TableCell>
                          <TableCell>
                            {ln.source_document_id ? (
                              <code>{shortId(ln.source_document_id)}</code>
                            ) : (
                              <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                                —
                              </Caption1>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>
              Close
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
