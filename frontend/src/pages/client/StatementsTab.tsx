import {
  Badge,
  Button,
  Caption1,
  Dropdown,
  makeStyles,
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
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { DocumentPdfRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDate, fmtMoney } from "../../lib/format";

type StatementTab = "tb" | "pl" | "bs" | "cf";

const useStyles = makeStyles({
  toolbar: {
    display: "flex",
    columnGap: "12px",
    alignItems: "center",
    marginBottom: "12px",
  },
  num: {
    textAlign: "right",
    fontFamily: tokens.fontFamilyMonospace,
  },
  totalRow: {
    fontWeight: tokens.fontWeightSemibold,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  sectionHeader: {
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
  },
});

export default function StatementsTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("st-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [tab, setTab] = useState<StatementTab>("tb");
  const [periodId, setPeriodId] = useState<string>("");

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: async () => {
      const ps = await api.listPeriods(clientId);
      if (ps.length > 0 && !periodId) setPeriodId(ps[0].id);
      return ps;
    },
  });

  const tb = useQuery({
    queryKey: ["tb", clientId, periodId],
    queryFn: () => api.getTrialBalance(clientId, periodId),
    enabled: !!periodId && tab === "tb",
  });
  const pl = useQuery({
    queryKey: ["pl", clientId, periodId],
    queryFn: () => api.getProfitAndLoss(clientId, periodId),
    enabled: !!periodId && tab === "pl",
  });
  const bs = useQuery({
    queryKey: ["bs", clientId, periodId],
    queryFn: () => api.getBalanceSheet(clientId, periodId),
    enabled: !!periodId && tab === "bs",
  });
  const cf = useQuery({
    queryKey: ["cf", clientId, periodId],
    queryFn: () => api.getCashFlow(clientId, periodId),
    enabled: !!periodId && tab === "cf",
  });

  const generate = useMutation({
    mutationFn: (kind: "profit_and_loss" | "balance_sheet" | "cash_flow") =>
      api.generateStatementArtifact({ period_id: periodId, kind, format: "pdf" }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>PDF artifact generated</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  if (periods.isLoading) return <LoadingState />;
  if (periods.error) return <ErrorState error={periods.error} />;
  if (!periods.data || periods.data.length === 0) {
    return <EmptyState title="No periods" description="Create a period before previewing statements." />;
  }

  const periodLabel = periods.data.find((p) => p.id === periodId)?.name ?? "";

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.toolbar}>
        <Dropdown
          value={periodLabel}
          selectedOptions={periodId ? [periodId] : []}
          onOptionSelect={(_, d) => d.optionValue && setPeriodId(d.optionValue)}
        >
          {periods.data.map((p) => (
            <Option
              key={p.id}
              value={p.id}
              text={`${p.name} (${fmtDate(p.start_date)} – ${fmtDate(p.end_date)})`}
            >
              {p.name} ({fmtDate(p.start_date)} – {fmtDate(p.end_date)})
            </Option>
          ))}
        </Dropdown>
        <Button
          appearance="secondary"
          icon={<DocumentPdfRegular />}
          disabled={!periodId || generate.isPending || tab === "tb"}
          onClick={() => {
            const kind =
              tab === "pl" ? "profit_and_loss" : tab === "bs" ? "balance_sheet" : "cash_flow";
            generate.mutate(kind);
          }}
        >
          Generate PDF artifact
        </Button>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Preview pulls live numbers. Generate creates a finalizable encrypted artifact.
        </Caption1>
      </div>

      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value as StatementTab)}>
        <Tab value="tb">Trial balance</Tab>
        <Tab value="pl">Profit &amp; loss</Tab>
        <Tab value="bs">Balance sheet</Tab>
        <Tab value="cf">Cash flow</Tab>
      </TabList>

      <div style={{ marginTop: 16 }}>
        {tab === "tb" && (
          <Section
            title="Trial balance"
            subtitle="Cumulative debits and credits per account through the period end."
            help={{
              title: "What is a trial balance?",
              body: (
                <>
                  A trial balance is the accountant's first sanity check
                  before producing financial statements. It lists every
                  account on the chart of accounts with its <i>total
                  debits</i> and <i>total credits</i> from inception through
                  the period end.
                  <br /><br />
                  In a valid double-entry book{" "}
                  <b>total debits must equal total credits</b>. The footer
                  shows a green badge when they do; a red badge means a
                  journal entry was posted unbalanced (which the system
                  should refuse — if you ever see this, file a bug).
                  <br /><br />
                  Numbers come from <i>posted</i> journal entries only;
                  drafts and unposted entries are excluded.
                </>
              ),
            }}
            toolbar={
              tb.data && (
                <Badge appearance="tint" color={tb.data.balances ? "success" : "danger"}>
                  {tb.data.balances ? "Debits = Credits" : "Out of balance"}
                </Badge>
              )
            }
          >
            {tb.isLoading && <LoadingState />}
            {tb.error && <ErrorState error={tb.error} />}
            {tb.data && tb.data.rows.length === 0 && (
              <EmptyState
                title="No accounts have activity yet"
                description="Post some journal entries (from approved drafts) and the balances will appear here."
              />
            )}
            {tb.data && tb.data.rows.length > 0 && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Code</TableHeaderCell>
                    <TableHeaderCell>Account</TableHeaderCell>
                    <TableHeaderCell>Type</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Debit</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Credit</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Balance</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tb.data.rows.map((r) => (
                    <TableRow key={r.account_id}>
                      <TableCell><code>{r.code}</code></TableCell>
                      <TableCell>{r.name}</TableCell>
                      <TableCell>{r.account_type}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(r.debit_total)}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(r.credit_total)}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow className={styles.totalRow}>
                    <TableCell colSpan={3}>
                      <Text weight="bold">Totals</Text>
                    </TableCell>
                    <TableCell className={styles.num}>
                      <Text weight="bold">{fmtMoney(tb.data.total_debits)}</Text>
                    </TableCell>
                    <TableCell className={styles.num}>
                      <Text weight="bold">{fmtMoney(tb.data.total_credits)}</Text>
                    </TableCell>
                    <TableCell className={styles.num}></TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            )}
          </Section>
        )}

        {tab === "pl" && (
          <Section
            title="Profit &amp; loss"
            help={{
              title: "What this shows",
              body: (
                <>
                  Revenue minus expenses for the selected period.
                  <i> Positive net income</i> = the business made money this
                  period; <i>negative</i> = it lost money.
                  <br /><br />
                  Click <b>Generate PDF artifact</b> to produce a signed,
                  finalizable copy that you can finalize in the Artifacts
                  tab and send to the client.
                </>
              ),
            }}
          >
            {pl.isLoading && <LoadingState />}
            {pl.error && <ErrorState error={pl.error} />}
            {pl.data && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Account</TableHeaderCell>
                    <TableHeaderCell>Name</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Amount</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pl.data.revenue.length > 0 && (
                    <>
                      <TableRow className={styles.sectionHeader}>
                        <TableCell colSpan={3}>Revenue</TableCell>
                      </TableRow>
                      {pl.data.revenue.map((r) => (
                        <TableRow key={r.account_id}>
                          <TableCell><code>{r.code}</code></TableCell>
                          <TableCell>{r.name}</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                        </TableRow>
                      ))}
                      <TableRow className={styles.totalRow}>
                        <TableCell colSpan={2}>Total revenue</TableCell>
                        <TableCell className={styles.num}>{fmtMoney(pl.data.total_revenue)}</TableCell>
                      </TableRow>
                    </>
                  )}

                  {pl.data.expenses.length > 0 && (
                    <>
                      <TableRow className={styles.sectionHeader}>
                        <TableCell colSpan={3}>Expenses</TableCell>
                      </TableRow>
                      {pl.data.expenses.map((r) => (
                        <TableRow key={r.account_id}>
                          <TableCell><code>{r.code}</code></TableCell>
                          <TableCell>{r.name}</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                        </TableRow>
                      ))}
                      <TableRow className={styles.totalRow}>
                        <TableCell colSpan={2}>Total expenses</TableCell>
                        <TableCell className={styles.num}>{fmtMoney(pl.data.total_expenses)}</TableCell>
                      </TableRow>
                    </>
                  )}

                  <TableRow className={styles.totalRow}>
                    <TableCell colSpan={2}>
                      <Text size={400} weight="bold">Net income</Text>
                    </TableCell>
                    <TableCell className={styles.num}>
                      <Text size={400} weight="bold">{fmtMoney(pl.data.net_income)}</Text>
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            )}
          </Section>
        )}

        {tab === "bs" && (
          <Section
            title="Balance sheet"
            help={{
              title: "What this shows",
              body: (
                <>
                  A snapshot of <b>Assets = Liabilities + Equity</b> as of
                  the period end. The green badge confirms the books
                  balance; the system asserts this on every computation, so
                  a red badge here would mean something is seriously
                  wrong upstream.
                  <br /><br />
                  Equity includes <i>Retained earnings (period)</i> — the
                  cumulative net income from inception through the period
                  end — so equity moves with net income automatically.
                </>
              ),
            }}
            toolbar={
              bs.data && (
                <Badge appearance="tint" color={bs.data.balances ? "success" : "danger"}>
                  {bs.data.balances ? "Assets = Liab + Equity" : "Out of balance"}
                </Badge>
              )
            }
          >
            {bs.isLoading && <LoadingState />}
            {bs.error && <ErrorState error={bs.error} />}
            {bs.data && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Account</TableHeaderCell>
                    <TableHeaderCell>Name</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Balance</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bs.data.assets.length > 0 && (
                    <>
                      <TableRow className={styles.sectionHeader}>
                        <TableCell colSpan={3}>Assets</TableCell>
                      </TableRow>
                      {bs.data.assets.map((r) => (
                        <TableRow key={r.account_id}>
                          <TableCell><code>{r.code}</code></TableCell>
                          <TableCell>{r.name}</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                        </TableRow>
                      ))}
                      <TableRow className={styles.totalRow}>
                        <TableCell colSpan={2}>Total assets</TableCell>
                        <TableCell className={styles.num}>{fmtMoney(bs.data.total_assets)}</TableCell>
                      </TableRow>
                    </>
                  )}

                  {bs.data.liabilities.length > 0 && (
                    <>
                      <TableRow className={styles.sectionHeader}>
                        <TableCell colSpan={3}>Liabilities</TableCell>
                      </TableRow>
                      {bs.data.liabilities.map((r) => (
                        <TableRow key={r.account_id}>
                          <TableCell><code>{r.code}</code></TableCell>
                          <TableCell>{r.name}</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                        </TableRow>
                      ))}
                      <TableRow className={styles.totalRow}>
                        <TableCell colSpan={2}>Total liabilities</TableCell>
                        <TableCell className={styles.num}>{fmtMoney(bs.data.total_liabilities)}</TableCell>
                      </TableRow>
                    </>
                  )}

                  {(bs.data.equity.length > 0 || Number(bs.data.retained_earnings_to_date) !== 0) && (
                    <>
                      <TableRow className={styles.sectionHeader}>
                        <TableCell colSpan={3}>Equity</TableCell>
                      </TableRow>
                      {bs.data.equity.map((r) => (
                        <TableRow key={r.account_id}>
                          <TableCell><code>{r.code}</code></TableCell>
                          <TableCell>{r.name}</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(r.signed_balance)}</TableCell>
                        </TableRow>
                      ))}
                      {Number(bs.data.retained_earnings_to_date) !== 0 && (
                        <TableRow>
                          <TableCell colSpan={2}>Retained earnings (period)</TableCell>
                          <TableCell className={styles.num}>{fmtMoney(bs.data.retained_earnings_to_date)}</TableCell>
                        </TableRow>
                      )}
                      <TableRow className={styles.totalRow}>
                        <TableCell colSpan={2}>Total equity</TableCell>
                        <TableCell className={styles.num}>{fmtMoney(bs.data.total_equity)}</TableCell>
                      </TableRow>
                    </>
                  )}
                </TableBody>
              </Table>
            )}
          </Section>
        )}

        {tab === "cf" && (
          <Section
            title="Cash flow"
            help={{
              title: "What this shows",
              body: (
                <>
                  The direct change-in-cash for the selected period across
                  the configured cash accounts (default: account{" "}
                  <code>1000</code>). Opening cash + Inflows − Outflows =
                  Closing cash, and the system asserts that equality.
                  <br /><br />
                  A full operating / investing / financing breakdown will
                  arrive once statement classification is wired in; this
                  view gives you the deterministic change-in-cash core
                  that everything else builds on.
                </>
              ),
            }}
          >
            {cf.isLoading && <LoadingState />}
            {cf.error && <ErrorState error={cf.error} />}
            {cf.data && (
              <Table size="small">
                <TableBody>
                  <TableRow>
                    <TableCell>Cash accounts</TableCell>
                    <TableCell className={styles.num}>
                      {cf.data.cash_account_codes.map((c) => <code key={c}>{c}</code>).reduce<React.ReactNode[]>(
                        (acc, el, i) => (i === 0 ? [el] : [...acc, ", ", el]),
                        [],
                      )}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Opening cash</TableCell>
                    <TableCell className={styles.num}>{fmtMoney(cf.data.opening_cash)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Inflows</TableCell>
                    <TableCell className={styles.num}>{fmtMoney(cf.data.inflows)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Outflows</TableCell>
                    <TableCell className={styles.num}>{fmtMoney(cf.data.outflows)}</TableCell>
                  </TableRow>
                  <TableRow className={styles.totalRow}>
                    <TableCell>Net change</TableCell>
                    <TableCell className={styles.num}>{fmtMoney(cf.data.net_change)}</TableCell>
                  </TableRow>
                  <TableRow className={styles.totalRow}>
                    <TableCell>Closing cash</TableCell>
                    <TableCell className={styles.num}>{fmtMoney(cf.data.closing_cash)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}
