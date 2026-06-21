import {
  Badge,
  Body1,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Dropdown,
  Field,
  Input,
  makeStyles,
  Option,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { AddRegular, DeleteRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDate, fmtMoney, shortId, todayIso } from "../../lib/format";

const useStyles = makeStyles({
  expanded: {
    backgroundColor: tokens.colorNeutralBackground2,
    padding: "12px",
    borderRadius: tokens.borderRadiusMedium,
    margin: "8px 0",
  },
  lineGrid: {
    display: "grid",
    gridTemplateColumns: "1.5fr 1fr 1fr 2fr auto",
    gap: "8px",
    alignItems: "end",
    marginBottom: "8px",
  },
  totalsRow: {
    display: "flex",
    justifyContent: "flex-end",
    columnGap: "24px",
    padding: "8px 0",
    fontFamily: tokens.fontFamilyMonospace,
  },
});

interface DraftLine {
  account_id: string;
  debit: string;
  credit: string;
  description: string;
}

export default function JournalEntriesTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("je-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });

  const [periodFilter, setPeriodFilter] = useState<string | undefined>(undefined);

  const entries = useQuery({
    queryKey: ["entries", clientId, periodFilter],
    queryFn: () => api.listJournalEntries(clientId, periodFilter),
  });

  const accountMap = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.id, a])),
    [accounts.data],
  );

  // ---- Post dialog ----
  const [open, setOpen] = useState(false);
  const [period, setPeriod] = useState("");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [memo, setMemo] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([
    { account_id: "", debit: "", credit: "", description: "" },
    { account_id: "", debit: "", credit: "", description: "" },
  ]);

  const totals = useMemo(() => {
    let d = 0;
    let c = 0;
    for (const ln of lines) {
      d += Number(ln.debit || 0);
      c += Number(ln.credit || 0);
    }
    return { d, c, balanced: d === c && d > 0 };
  }, [lines]);

  const post = useMutation({
    mutationFn: () =>
      api.postJournalEntry({
        client_id: clientId,
        period_id: period,
        entry_date: entryDate,
        memo: memo || null,
        lines: lines
          .filter((l) => l.account_id)
          .map((l) => ({
            account_id: l.account_id,
            debit: l.debit || "0",
            credit: l.credit || "0",
            description: l.description || null,
          })),
      }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Entry posted</ToastTitle></Toast>, { intent: "success" });
      setOpen(false);
      setMemo("");
      setLines([
        { account_id: "", debit: "", credit: "", description: "" },
        { account_id: "", debit: "", credit: "", description: "" },
      ]);
      qc.invalidateQueries({ queryKey: ["entries", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <Section
        title="Journal entries"
        subtitle="Double-entry postings, ordered by entry date."
        toolbar={
          <div style={{ display: "flex", columnGap: 12 }}>
            <Dropdown
              placeholder="All periods"
              value={periods.data?.find((p) => p.id === periodFilter)?.name ?? "All periods"}
              selectedOptions={periodFilter ? [periodFilter] : []}
              onOptionSelect={(_, d) => setPeriodFilter(d.optionValue || undefined)}
            >
              <Option value="">All periods</Option>
              {(periods.data ?? []).map((p) => (
                <Option key={p.id} value={p.id}>
                  {p.name}
                </Option>
              ))}
            </Dropdown>
            <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="primary" icon={<AddRegular />}>
                  Post entry
                </Button>
              </DialogTrigger>
              <DialogSurface style={{ maxWidth: 760 }}>
                <DialogBody>
                  <DialogTitle>Post manual journal entry</DialogTitle>
                  <DialogContent>
                    <div style={{ display: "grid", rowGap: 12, marginTop: 8 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                        <Field label="Period" required>
                          <Dropdown
                            placeholder="Select period"
                            selectedOptions={period ? [period] : []}
                            value={periods.data?.find((p) => p.id === period)?.name ?? ""}
                            onOptionSelect={(_, d) => setPeriod(d.optionValue ?? "")}
                          >
                            {(periods.data ?? []).map((p) => (
                              <Option
                                key={p.id}
                                value={p.id}
                                text={p.is_locked ? `${p.name} (locked)` : p.name}
                                disabled={p.is_locked}
                              >
                                {p.is_locked ? `${p.name} (locked)` : p.name}
                              </Option>
                            ))}
                          </Dropdown>
                        </Field>
                        <Field label="Entry date" required>
                          <Input
                            type="date"
                            value={entryDate}
                            onChange={(_, d) => setEntryDate(d.value)}
                          />
                        </Field>
                      </div>
                      <Field label="Memo">
                        <Input value={memo} onChange={(_, d) => setMemo(d.value)} />
                      </Field>

                      <Body1 style={{ marginTop: 8, fontWeight: 600 }}>Lines</Body1>
                      {lines.map((ln, i) => (
                        <div key={i} className={styles.lineGrid}>
                          <Dropdown
                            placeholder="Account"
                            selectedOptions={ln.account_id ? [ln.account_id] : []}
                            value={accountMap.get(ln.account_id)?.name ?? ""}
                            onOptionSelect={(_, d) => {
                              const next = [...lines];
                              next[i] = { ...next[i], account_id: d.optionValue ?? "" };
                              setLines(next);
                            }}
                          >
                            {(accounts.data ?? []).map((a) => (
                              <Option key={a.id} value={a.id} text={`${a.code} — ${a.name}`}>
                                {a.code} — {a.name}
                              </Option>
                            ))}
                          </Dropdown>
                          <Input
                            placeholder="Debit"
                            value={ln.debit}
                            onChange={(_, d) => {
                              const next = [...lines];
                              next[i] = { ...next[i], debit: d.value };
                              setLines(next);
                            }}
                          />
                          <Input
                            placeholder="Credit"
                            value={ln.credit}
                            onChange={(_, d) => {
                              const next = [...lines];
                              next[i] = { ...next[i], credit: d.value };
                              setLines(next);
                            }}
                          />
                          <Input
                            placeholder="Description"
                            value={ln.description}
                            onChange={(_, d) => {
                              const next = [...lines];
                              next[i] = { ...next[i], description: d.value };
                              setLines(next);
                            }}
                          />
                          <Button
                            appearance="subtle"
                            icon={<DeleteRegular />}
                            onClick={() => setLines(lines.filter((_, j) => j !== i))}
                            disabled={lines.length <= 2}
                          />
                        </div>
                      ))}
                      <Button
                        appearance="secondary"
                        icon={<AddRegular />}
                        onClick={() =>
                          setLines([
                            ...lines,
                            { account_id: "", debit: "", credit: "", description: "" },
                          ])
                        }
                      >
                        Add line
                      </Button>

                      <div className={styles.totalsRow}>
                        <span>Debits: <strong>{fmtMoney(totals.d)}</strong></span>
                        <span>Credits: <strong>{fmtMoney(totals.c)}</strong></span>
                        <Badge appearance="tint" color={totals.balanced ? "success" : "warning"}>
                          {totals.balanced ? "balanced" : "unbalanced"}
                        </Badge>
                      </div>
                    </div>
                  </DialogContent>
                  <DialogActions>
                    <DialogTrigger disableButtonEnhancement>
                      <Button appearance="secondary">Cancel</Button>
                    </DialogTrigger>
                    <Button
                      appearance="primary"
                      disabled={!period || !totals.balanced || post.isPending}
                      onClick={() => post.mutate()}
                    >
                      Post
                    </Button>
                  </DialogActions>
                </DialogBody>
              </DialogSurface>
            </Dialog>
          </div>
        }
      >
        {entries.isLoading && <LoadingState />}
        {entries.error && <ErrorState error={entries.error} />}
        {entries.data && entries.data.length === 0 && (
          <EmptyState title="No journal entries yet" />
        )}
        {entries.data && entries.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Date</TableHeaderCell>
                <TableHeaderCell>Memo</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell style={{ textAlign: "right" }}>Total</TableHeaderCell>
                <TableHeaderCell>ID</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.data.map((e) => {
                const total = e.lines.reduce((s, l) => s + Number(l.debit), 0);
                return (
                  <>
                    <TableRow key={e.id}>
                      <TableCell>{fmtDate(e.entry_date)}</TableCell>
                      <TableCell>{e.memo ?? "—"}</TableCell>
                      <TableCell>
                        <Badge appearance="tint" color={e.status === "posted" ? "success" : "warning"}>
                          {e.status}
                        </Badge>
                      </TableCell>
                      <TableCell style={{ textAlign: "right", fontFamily: tokens.fontFamilyMonospace }}>
                        {fmtMoney(total)}
                      </TableCell>
                      <TableCell><code>{shortId(e.id)}</code></TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={5} style={{ padding: 0 }}>
                        <div className={styles.expanded}>
                          <Table size="extra-small">
                            <TableHeader>
                              <TableRow>
                                <TableHeaderCell>Line</TableHeaderCell>
                                <TableHeaderCell>Account</TableHeaderCell>
                                <TableHeaderCell style={{ textAlign: "right" }}>Debit</TableHeaderCell>
                                <TableHeaderCell style={{ textAlign: "right" }}>Credit</TableHeaderCell>
                                <TableHeaderCell>Description</TableHeaderCell>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {e.lines.map((l) => {
                                const a = accountMap.get(l.account_id);
                                return (
                                  <TableRow key={l.id}>
                                    <TableCell>{l.line_no}</TableCell>
                                    <TableCell>
                                      {a ? (
                                        <>
                                          <code>{a.code}</code> {a.name}
                                        </>
                                      ) : (
                                        <code>{shortId(l.account_id)}</code>
                                      )}
                                    </TableCell>
                                    <TableCell style={{ textAlign: "right", fontFamily: tokens.fontFamilyMonospace }}>
                                      {Number(l.debit) > 0 ? fmtMoney(l.debit) : ""}
                                    </TableCell>
                                    <TableCell style={{ textAlign: "right", fontFamily: tokens.fontFamilyMonospace }}>
                                      {Number(l.credit) > 0 ? fmtMoney(l.credit) : ""}
                                    </TableCell>
                                    <TableCell>{l.description ?? ""}</TableCell>
                                  </TableRow>
                                );
                              })}
                            </TableBody>
                          </Table>
                        </div>
                      </TableCell>
                    </TableRow>
                  </>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
