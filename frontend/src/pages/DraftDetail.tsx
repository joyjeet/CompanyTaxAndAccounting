import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  OptionGroup,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { AddRegular, DeleteRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useFirmRole } from "../auth/useFirmRole";
import type { CoaOut } from "../auth/types";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";
import { fmtMoney, shortId, todayIso } from "../lib/format";
import {
  periodCoversRange,
  pickBestPeriod,
  statementRangeFromTxns,
  suggestPeriodName,
  toWholeMonths,
} from "../lib/statementPeriod";
import {
  promoteAllDisabledReason,
  promoteDisabledReason,
  rejectDisabledReason,
} from "./draftActionGate";

interface DraftLine {
  account_id: string;
  debit: string;
  credit: string;
  description: string;
}

const ACCOUNT_TYPE_ORDER = ["asset", "liability", "equity", "revenue", "expense"] as const;

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  asset: "Assets",
  liability: "Liabilities",
  equity: "Equity",
  revenue: "Income",
  expense: "Expenses",
};

const useStyles = makeStyles({
  payload: {
    backgroundColor: tokens.colorNeutralBackground2,
    padding: "12px",
    borderRadius: tokens.borderRadiusMedium,
    overflow: "auto",
    fontSize: tokens.fontSizeBase200,
    fontFamily: tokens.fontFamilyMonospace,
    maxHeight: "300px",
  },
  totals: {
    display: "flex",
    justifyContent: "flex-end",
    columnGap: "24px",
    padding: "8px 0",
    fontFamily: tokens.fontFamilyMonospace,
  },
});

export default function DraftDetail() {
  const styles = useStyles();
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const qc = useQueryClient();
  const { identity } = useAuth();
  const { capabilities, role } = useFirmRole();
  const toasterId = useId("draft-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const draft = useQuery({
    queryKey: ["drafts", "all"],
    queryFn: () => api.listDrafts(false),
    select: (rows) => rows.find((r) => r.id === id) ?? null,
  });

  const sourceDocument = useQuery({
    queryKey: ["document-detail", draft.data?.source_document_id],
    queryFn: () => api.getDocument(draft.data!.source_document_id),
    enabled: !!draft.data?.source_document_id,
  });

  // For promotion we need a client_id. The identity may or may not have
  // one. If it does, use it; otherwise we ask the user to pick from the
  // firm's clients.
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients() });
  const [clientId, setClientId] = useState<string>(identity?.clientId ?? "");
  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
    enabled: !!clientId,
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
    enabled: !!clientId,
  });
  const accountMap = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.id, a])),
    [accounts.data],
  );
  const accountCodeMap = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.code, a])),
    [accounts.data],
  );
  const suspenseAccount = useMemo(() => {
    const rows = accounts.data ?? [];
    return (
      rows.find((a) => /suspense|uncategor/i.test(a.name)) ??
      rows.find((a) => a.code === "9999")
    );
  }, [accounts.data]);
  const groupedAccounts = useMemo(() => {
    const buckets = new Map<string, CoaOut[]>();
    for (const type of ACCOUNT_TYPE_ORDER) buckets.set(type, []);
    for (const account of accounts.data ?? []) {
      const group = buckets.get(account.account_type) ?? [];
      group.push(account);
      buckets.set(account.account_type, group);
    }
    for (const rows of buckets.values()) {
      rows.sort((left, right) => left.code.localeCompare(right.code));
    }
    return ACCOUNT_TYPE_ORDER.map((type) => ({
      type,
      label: ACCOUNT_TYPE_LABELS[type],
      accounts: buckets.get(type) ?? [],
    })).filter((group) => group.accounts.length > 0);
  }, [accounts.data]);

  const accountLabelByCode = (code: string): string => {
    const acct = accountCodeMap.get(code);
    if (!acct) {
      if (code === "9999") {
        if (suspenseAccount) {
          return `${suspenseAccount.code} - ${suspenseAccount.name}`;
        }
        return "9999 - Suspense account";
      }
      return code;
    }
    return `${acct.code} - ${acct.name}`;
  };

  const [periodId, setPeriodId] = useState("");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [memo, setMemo] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([
    { account_id: "", debit: "", credit: "", description: "" },
    { account_id: "", debit: "", credit: "", description: "" },
  ]);
  const [rejectReason, setRejectReason] = useState("");

  useEffect(() => {
    if (clientId) return;
    if (!sourceDocument.data?.client_id) return;
    setClientId(sourceDocument.data.client_id);
  }, [clientId, sourceDocument.data?.client_id]);

  // Pre-fill the promote form from the AI's payload once accounts have
  // loaded. Only runs ONCE per draft (guarded by `prefilledRef`) so a user
  // who manually edits a field is never overwritten by a re-render.
  const prefilledRef = useRef<string | null>(null);
  useEffect(() => {
    const drow = draft.data;
    const accts = accounts.data;
    if (!drow || !accts || accts.length === 0) return;
    if (prefilledRef.current === drow.id) return;
    prefilledRef.current = drow.id;

    const payload = (drow.payload ?? {}) as Record<string, unknown>;
    const byCode = new Map(accts.map((a) => [a.code, a]));
    // Heuristics for the "cash" leg of a transaction. Order matters.
    const cash =
      byCode.get("1000") ??
      byCode.get("1010") ??
      accts.find((a) => /cash|checking|bank/i.test(a.name));
    const ap = byCode.get("2000") ?? accts.find((a) => /payable/i.test(a.name));

    const setAmountLines = (
      debitAcct: typeof accts[number] | undefined,
      creditAcct: typeof accts[number] | undefined,
      amount: string,
      description: string,
    ) => {
      if (!debitAcct || !creditAcct || !amount) return;
      setLines([
        { account_id: debitAcct.id, debit: amount, credit: "", description },
        { account_id: creditAcct.id, debit: "", credit: amount, description },
      ]);
    };

    if (drow.kind === "bank_transaction" || drow.kind === "receipt") {
      const code = String(payload.proposed_account_code ?? "");
      const amount = String(payload.amount ?? "");
      const date = String(payload.date ?? "");
      const memoVal = String(payload.memo ?? payload.merchant ?? "");
      const debitAcct = byCode.get(code) ?? suspenseAccount ?? accts.find((a) => a.code === "9999");
      if (memoVal) setMemo(memoVal);
      if (date) setEntryDate(date);
      setAmountLines(debitAcct, cash, amount, memoVal);
    } else if (drow.kind === "invoice") {
      const vendor = String(payload.vendor ?? "");
      const total = String(payload.total ?? "");
      const date = String(payload.date ?? "");
      if (vendor) setMemo(vendor);
      if (date) setEntryDate(date);
      // Invoice received -> debit an expense, credit AP.
      const expense =
        byCode.get("5000") ??
        accts.find((a) => /expense/i.test(a.name));
      setAmountLines(expense, ap, total, vendor);
    }
    // tax_form / generic: nothing to pre-fill — the reasons block will
    // explain why and the OCR fields/text are surfaced separately.
  }, [draft.data, accounts.data]);

  const totals = useMemo(() => {
    let d = 0;
    let c = 0;
    for (const ln of lines) {
      d += Number(ln.debit || 0);
      c += Number(ln.credit || 0);
    }
    return { d, c, balanced: d === c && d > 0 };
  }, [lines]);

  const promote = useMutation({
    mutationFn: () =>
      api.promoteDraft(id, {
        client_id: clientId || undefined,
        period_id: periodId,
        entry_date: entryDate,
        memo: memo || undefined,
        lines: lines
          .filter((l) => l.account_id)
          .map((l) => ({
            account_id: l.account_id,
            debit: l.debit || "0",
            credit: l.credit || "0",
            description: l.description || undefined,
          })),
      }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Promoted to journal entry</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      qc.invalidateQueries({ queryKey: ["entries"] });
      navigate("/review", { replace: true });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const reject = useMutation({
    mutationFn: () => api.rejectDraft(id, rejectReason || undefined),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Draft rejected</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      navigate("/review", { replace: true });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  // ----- Bank statement (multi-transaction) handling ---------------------
  // When the classifier detects a bank statement, payload.transactions is a
  // list and we expose a "Post all N transactions" button rather than the
  // single-entry promote form.
  const payload = (draft.data?.payload ?? {}) as Record<string, unknown>;
  const isStatement = payload.is_statement === true;
  const rawTxns = Array.isArray(payload.transactions)
    ? (payload.transactions as Array<Record<string, unknown>>)
    : [];
  const [txnOverrides, setTxnOverrides] = useState<Record<number, string>>({});

  // ----- Statement period alignment --------------------------------------
  // The backend clamps every transaction date into the selected period
  // (`app/domain/promotion.py::_clamp`), so posting a July statement against
  // a full-year period silently rewrites all 17 dates to Jan 1. We derive the
  // statement's own span, pre-select a period that genuinely covers it, and
  // make any mismatch loud instead of silent.
  const statementRange = useMemo(() => statementRangeFromTxns(rawTxns), [rawTxns]);

  const selectedPeriod = useMemo(
    () => (periods.data ?? []).find((p) => p.id === periodId) ?? null,
    [periods.data, periodId],
  );
  const periodMismatch =
    statementRange !== null &&
    selectedPeriod !== null &&
    !periodCoversRange(selectedPeriod, statementRange);

  // Auto-select the narrowest covering period. Guarded per draft+client so a
  // reviewer's manual choice is never overwritten by a re-render or refetch.
  const periodAutoRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isStatement || !statementRange) return;
    const rows = periods.data;
    if (!rows || rows.length === 0) return;
    const key = `${id}:${clientId}`;
    if (periodAutoRef.current === key) return;
    periodAutoRef.current = key;
    if (periodId) return; // reviewer already chose one
    const best = pickBestPeriod(rows, statementRange);
    if (best) setPeriodId(best.id);
  }, [isStatement, statementRange, periods.data, periodId, id, clientId]);

  // "Custom period" inline form state.
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const createPeriod = useMutation({
    mutationFn: (body: { name: string; start_date: string; end_date: string }) =>
      api.createPeriod(clientId, body),
    onSuccess: (created) => {
      dispatchToast(
        <Toast>
          <ToastTitle>Period “{created.name}” created</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      // Refresh the dropdown, then select the period we just made.
      qc.invalidateQueries({ queryKey: ["periods", clientId] });
      setPeriodId(created.id);
      setCustomOpen(false);
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  /** Create a period snapped to the whole month(s) the statement falls in. */
  const createPeriodFromStatement = () => {
    if (!statementRange) return;
    const snapped = toWholeMonths(statementRange);
    createPeriod.mutate({
      name: suggestPeriodName(statementRange),
      start_date: snapped.start,
      end_date: snapped.end,
    });
  };

  const openCustomPeriod = () => {
    // Pre-fill from the statement so the common case is one click away.
    if (statementRange) {
      const snapped = toWholeMonths(statementRange);
      setCustomName(suggestPeriodName(statementRange));
      setCustomStart(snapped.start);
      setCustomEnd(snapped.end);
    }
    setCustomOpen(true);
  };

  const promoteAll = useMutation({
    mutationFn: () => {
      const overrides: Record<string, string> = {};
      for (const [idx, code] of Object.entries(txnOverrides)) {
        if (code) overrides[String(idx)] = code;
      }
      return api.promoteStatementDraft(id, {
        client_id: clientId || undefined,
        period_id: periodId,
        cash_account_code: "1000",
        account_overrides: Object.keys(overrides).length ? overrides : undefined,
      });
    },
    onSuccess: (res) => {
      const skipped = res.skipped.length;
      const posted = res.journal_entry_ids.length;
      dispatchToast(
        <Toast>
          <ToastTitle>
            Posted {posted} journal entr{posted === 1 ? "y" : "ies"}
            {skipped > 0 ? ` (${skipped} skipped — see audit)` : ""}
          </ToastTitle>
        </Toast>,
        { intent: skipped > 0 ? "warning" : "success" },
      );
      qc.invalidateQueries({ queryKey: ["drafts"] });
      qc.invalidateQueries({ queryKey: ["entries"] });
      navigate("/review", { replace: true });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  if (draft.isLoading) return <LoadingState />;
  if (draft.error) return <ErrorState error={draft.error} />;
  if (!draft.data) return <Body1>Draft not found.</Body1>;

  const d = draft.data;
  const conf = Number.parseFloat(d.confidence);
  const canPromoteDrafts = capabilities.canPromoteDrafts;
  const blockedReason = rejectDisabledReason({ canPromoteDrafts, role });
  const promoteAllReason = promoteAllDisabledReason({
    canPromoteDrafts,
    role,
    clientId,
    periodId,
  });
  const promoteReason = promoteDisabledReason({
    canPromoteDrafts,
    role,
    clientId,
    periodId,
    balanced: totals.balanced,
  });

  const renderAccountOptions = () => (
    <>
      {groupedAccounts.map((group) => (
        <OptionGroup key={group.type} label={group.label}>
          {group.accounts.map((a) => (
            <Option key={a.id} value={a.id} text={`${a.code} — ${a.name}`}>
              {a.code} — {a.name}
            </Option>
          ))}
        </OptionGroup>
      ))}
    </>
  );

  return (
    <div style={{ display: "grid", rowGap: 16 }}>
      <Toaster toasterId={toasterId} />
      <div>
        <Text
          size={200}
          style={{ color: tokens.colorNeutralForeground3, cursor: "pointer" }}
          onClick={() => navigate("/review")}
        >
          ← Review queue
        </Text>
        <Text size={700} weight="semibold" block>
          Draft · {d.kind}
        </Text>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Source document <code>{shortId(d.source_document_id)}</code>
        </Caption1>
      </div>

      <SourceDocumentPreview documentId={d.source_document_id} />

      <Section
        title="AI classification"
        help={{
          title: "How to read this",
          body: (
            <>
              The classifier read the source document's extracted fields
              and produced this proposed journal entry. The <b>confidence
              badge</b> reflects how sure the model is.
              <br /><br />
              <b>What to check:</b>
              <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                <li>
                  Is the <i>kind</i> right? (invoice / receipt /
                  bank_transaction / tax form)
                </li>
                <li>
                  Open the <i>Raw payload</i> below to see exactly which
                  fields drove the classification (vendor, amount,
                  proposed accounts, sign).
                </li>
                <li>
                  Then scroll down to <b>Promote to journal entry</b> to
                  edit the proposed lines and post, or <b>Reject this
                  draft</b> if the classifier got it badly wrong.
                </li>
              </ul>
            </>
          ),
        }}
        toolbar={
          <Badge appearance="filled" color={d.high_confidence ? "success" : conf < 0.6 ? "danger" : "warning"}>
            {(conf * 100).toFixed(0)}% confidence
          </Badge>
        }
      >
        <Body1>
          <strong>Status:</strong> {d.status} · <strong>Model:</strong> <code>{d.model}</code> ·{" "}
          <strong>Prompt:</strong> <code>{d.prompt_version}</code>
        </Body1>
        {(() => {
          const payload = (d.payload ?? {}) as Record<string, unknown>;
          const reasons = Array.isArray(payload._reasons)
            ? (payload._reasons as unknown[]).map(String)
            : [];
          const fields = Array.isArray(payload.fields)
            ? (payload.fields as Array<Record<string, unknown>>)
            : [];
          const text = typeof payload.text === "string" ? payload.text : "";
          return (
            <>
              {reasons.length > 0 && (
                <div
                  style={{
                    marginTop: 12,
                    padding: "10px 12px",
                    backgroundColor: tokens.colorNeutralBackground2,
                    borderLeft: `3px solid ${conf < 0.6 ? tokens.colorPaletteRedBorder1 : tokens.colorPaletteYellowBorder1}`,
                    borderRadius: tokens.borderRadiusMedium,
                  }}
                >
                  <Text weight="semibold" size={300} block>
                    Why {(conf * 100).toFixed(0)}% confidence?
                  </Text>
                  <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                    {reasons.map((r, i) => (
                      <li key={i}>
                        <Text size={200}>{r}</Text>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {fields.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text weight="semibold" size={300} block>
                    OCR extracted fields
                  </Text>
                  <Table size="extra-small" style={{ marginTop: 4 }}>
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Field</TableHeaderCell>
                        <TableHeaderCell>Value</TableHeaderCell>
                        <TableHeaderCell>OCR conf.</TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {fields.map((f, i) => (
                        <TableRow key={i}>
                          <TableCell><code>{String(f.name ?? "")}</code></TableCell>
                          <TableCell>{String(f.value ?? "")}</TableCell>
                          <TableCell>
                            {typeof f.confidence === "number"
                              ? `${(f.confidence * 100).toFixed(0)}%`
                              : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
              {text && !fields.length && (
                <div style={{ marginTop: 12 }}>
                  <Text weight="semibold" size={300} block>
                    OCR text
                  </Text>
                  <pre className={styles.payload}>{text}</pre>
                </div>
              )}
            </>
          );
        })()}
        <details style={{ marginTop: 12 }}>
          <summary>Raw payload</summary>
          <pre className={styles.payload}>{JSON.stringify(d.payload, null, 2)}</pre>
        </details>
      </Section>

      {isStatement && (
        <Section
          title={`Bank statement transactions (${rawTxns.length})`}
          help={{
            title: "Posting a multi-transaction statement",
            body: (
              <>
                The classifier parsed each line of the statement into a
                proposed transaction. Clicking <b>Post all transactions</b>
                creates <b>one balanced journal entry per row</b> against
                the selected period — deposits get DR Cash / CR &lt;income
                or other&gt;, payments get DR &lt;expense&gt; / CR Cash.
                <br /><br />
                You can <b>override the account code</b> on any row before
                posting (e.g. move a Suspense 9999 row to the right
                expense account). Rows whose code does not exist in this
                client's chart of accounts will be reported as
                &ldquo;skipped&rdquo; in the result toast.
              </>
            ),
          }}
        >
          {(() => {
            const totalDeposits = rawTxns
              .filter((t) => String(t.direction) === "deposit")
              .reduce((s, t) => s + Number(String(t.amount ?? "0")), 0);
            const totalPayments = rawTxns
              .filter((t) => String(t.direction) === "payment")
              .reduce((s, t) => s + Number(String(t.amount ?? "0")), 0);
            const period =
              typeof payload.statement_period === "string"
                ? payload.statement_period
                : "";
            const holder =
              typeof payload.account_holder === "string"
                ? payload.account_holder
                : "";
            const beg =
              typeof payload.beginning_balance === "string"
                ? payload.beginning_balance
                : "";
            const end =
              typeof payload.ending_balance === "string"
                ? payload.ending_balance
                : "";
            return (
              <>
                <Body1>
                  {holder && <><strong>{holder}</strong> · </>}
                  {period && <>{period} · </>}
                  Beginning <strong>{beg || "—"}</strong> · Ending{" "}
                  <strong>{end || "—"}</strong>
                </Body1>
                <div className={styles.totals}>
                  <span>
                    Deposits: <strong>{fmtMoney(totalDeposits)}</strong>
                  </span>
                  <span>
                    Payments: <strong>{fmtMoney(totalPayments)}</strong>
                  </span>
                  <span>
                    Net change:{" "}
                    <strong>
                      {fmtMoney(totalDeposits - totalPayments)}
                    </strong>
                  </span>
                </div>
                <Table size="extra-small" style={{ marginTop: 8 }}>
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>Date</TableHeaderCell>
                      <TableHeaderCell>Description</TableHeaderCell>
                      <TableHeaderCell>Direction</TableHeaderCell>
                      <TableHeaderCell>Amount</TableHeaderCell>
                      <TableHeaderCell>Account</TableHeaderCell>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rawTxns.map((t, i) => {
                      const proposed = String(t.proposed_account_code ?? "");
                      const normalizedProposed =
                        accountCodeMap.has(proposed)
                          ? proposed
                          : (suspenseAccount?.code ?? proposed);
                      const current = txnOverrides[i] ?? normalizedProposed;
                      const acct = accountCodeMap.get(current);
                      const dir = String(t.direction ?? "");
                      return (
                        <TableRow key={i}>
                          <TableCell>
                            <code>{String(t.raw_date ?? t.date ?? "")}</code>
                          </TableCell>
                          <TableCell>{String(t.description ?? "")}</TableCell>
                          <TableCell>
                            <Badge
                              appearance="tint"
                              color={dir === "deposit" ? "success" : "warning"}
                            >
                              {dir}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <code>{String(t.amount ?? "")}</code>
                          </TableCell>
                          <TableCell>
                            <Dropdown
                              placeholder="Account"
                              selectedOptions={acct ? [acct.id] : []}
                              value={accountLabelByCode(current)}
                              onOptionSelect={(_, dd) => {
                                const next = { ...txnOverrides };
                                const newAcct = (accounts.data ?? []).find(
                                  (a) => a.id === dd.optionValue,
                                );
                                if (newAcct) next[i] = newAcct.code;
                                setTxnOverrides(next);
                              }}
                            >
                              {renderAccountOptions()}
                            </Dropdown>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                {periodMismatch && statementRange && selectedPeriod && (
                  <MessageBar intent="warning" style={{ marginTop: 12 }}>
                    <MessageBarBody>
                      <MessageBarTitle>
                        This period does not cover the statement dates.
                      </MessageBarTitle>
                      <Body1 block>
                        The statement runs <b>{statementRange.start}</b> to{" "}
                        <b>{statementRange.end}</b>, but <b>{selectedPeriod.name}</b>{" "}
                        runs {selectedPeriod.start_date} to {selectedPeriod.end_date}.
                        Posting now would <b>silently move every out-of-range
                        transaction</b> to the nearest period boundary — the
                        amounts stay correct but the dates do not. Pick a
                        matching period or create one below.
                      </Body1>
                    </MessageBarBody>
                  </MessageBar>
                )}
                {!statementRange && (
                  <MessageBar intent="info" style={{ marginTop: 12 }}>
                    <MessageBarBody>
                      <MessageBarTitle>No transaction dates detected.</MessageBarTitle>
                      <Body1 block>
                        The parser could not infer a year for these rows, so the
                        period cannot be checked automatically. Confirm the
                        period manually before posting.
                      </Body1>
                    </MessageBarBody>
                  </MessageBar>
                )}
                <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
                  {!identity?.clientId && (
                    <Field label="Client" required>
                      <Dropdown
                        placeholder="Select client"
                        value={
                          clients.data?.find((c) => c.id === clientId)?.name ?? ""
                        }
                        selectedOptions={clientId ? [clientId] : []}
                        onOptionSelect={(_, dd) => setClientId(dd.optionValue ?? "")}
                      >
                        {(clients.data ?? []).map((c) => (
                          <Option key={c.id} value={c.id}>{c.name}</Option>
                        ))}
                      </Dropdown>
                    </Field>
                  )}
                  <Field
                    label="Period"
                    required
                    hint={
                      statementRange
                        ? `Statement covers ${statementRange.start} → ${statementRange.end}`
                        : "No dated rows found on this statement"
                    }
                  >
                    <Dropdown
                      placeholder="Select period"
                      value={selectedPeriod?.name ?? ""}
                      selectedOptions={periodId ? [periodId] : []}
                      onOptionSelect={(_, dd) => setPeriodId(dd.optionValue ?? "")}
                    >
                      {(periods.data ?? []).map((p) => {
                        const covers =
                          statementRange !== null && periodCoversRange(p, statementRange);
                        const label = p.is_locked
                          ? `${p.name} (locked)`
                          : covers
                            ? `${p.name} ✓ matches statement`
                            : p.name;
                        return (
                          <Option
                            key={p.id}
                            value={p.id}
                            text={label}
                            disabled={p.is_locked}
                          >
                            {label}
                          </Option>
                        );
                      })}
                    </Dropdown>
                  </Field>
                  {statementRange && (
                    <Button
                      appearance="secondary"
                      disabled={!clientId || createPeriod.isPending}
                      onClick={createPeriodFromStatement}
                      icon={createPeriod.isPending ? <Spinner size="tiny" /> : undefined}
                    >
                      Use statement period ({suggestPeriodName(statementRange)})
                    </Button>
                  )}
                  <Button
                    appearance="secondary"
                    disabled={!clientId || createPeriod.isPending}
                    onClick={openCustomPeriod}
                  >
                    Custom period…
                  </Button>
                  <Button
                    appearance="primary"
                    disabled={!canPromoteDrafts || !clientId || !periodId || promoteAll.isPending}
                    title={promoteAllReason}
                    onClick={() => promoteAll.mutate()}
                  >
                    {promoteAll.isPending ? (
                      <Spinner size="tiny" />
                    ) : (
                      `Post all ${rawTxns.length} transactions`
                    )}
                  </Button>
                </div>
                {customOpen && (
                  <div
                    style={{
                      marginTop: 12,
                      padding: 12,
                      display: "flex",
                      gap: 12,
                      alignItems: "flex-end",
                      flexWrap: "wrap",
                      backgroundColor: tokens.colorNeutralBackground2,
                      borderRadius: tokens.borderRadiusMedium,
                    }}
                  >
                    <Field label="Period name" required>
                      <Input
                        value={customName}
                        onChange={(_, dd) => setCustomName(dd.value)}
                        placeholder="e.g. Jul 2025"
                      />
                    </Field>
                    <Field label="Start date" required>
                      <Input
                        type="date"
                        value={customStart}
                        onChange={(_, dd) => setCustomStart(dd.value)}
                      />
                    </Field>
                    <Field label="End date" required>
                      <Input
                        type="date"
                        value={customEnd}
                        onChange={(_, dd) => setCustomEnd(dd.value)}
                      />
                    </Field>
                    <Button
                      appearance="primary"
                      disabled={
                        !customName.trim() ||
                        !customStart ||
                        !customEnd ||
                        customStart > customEnd ||
                        createPeriod.isPending
                      }
                      onClick={() =>
                        createPeriod.mutate({
                          name: customName.trim(),
                          start_date: customStart,
                          end_date: customEnd,
                        })
                      }
                    >
                      {createPeriod.isPending ? <Spinner size="tiny" /> : "Create & select"}
                    </Button>
                    <Button
                      appearance="subtle"
                      disabled={createPeriod.isPending}
                      onClick={() => setCustomOpen(false)}
                    >
                      Cancel
                    </Button>
                    {customStart > customEnd && customStart && customEnd && (
                      <Caption1 style={{ color: tokens.colorPaletteRedForeground1 }}>
                        Start date must be on or before the end date.
                      </Caption1>
                    )}
                  </div>
                )}
                {!canPromoteDrafts && (
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    {blockedReason}
                  </Caption1>
                )}
              </>
            );
          })()}
        </Section>
      )}

      {!isStatement && (
      <Section
        title="Promote to journal entry"
        help={{
          title: "What ‘Promote’ does",
          body: (
            <>
              Promoting writes a <b>real, posted, balanced journal
              entry</b> against the selected period. The entry is
              immutable after posting (correction = reversing entry, not
              edit) and immediately affects the trial balance, P&amp;L,
              balance sheet, and downstream tax worksheets.
              <br /><br />
              <b>Required:</b>
              <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                <li>The period must be open (locked periods are disabled).</li>
                <li>Every line needs an account, a debit OR a credit (not both), and the total debits must equal total credits.</li>
                <li>Entry date must fall inside the selected period.</li>
              </ul>
              The draft is marked <i>promoted</i> and the source document
              gets a permanent link to the resulting journal entry for
              audit.
            </>
          ),
        }}
      >
        <div style={{ display: "grid", rowGap: 12 }}>
          {!identity?.clientId && (
            <Field label="Client" required>
              <Dropdown
                placeholder="Select client"
                value={clients.data?.find((c) => c.id === clientId)?.name ?? ""}
                selectedOptions={clientId ? [clientId] : []}
                onOptionSelect={(_, dd) => setClientId(dd.optionValue ?? "")}
              >
                {(clients.data ?? []).map((c) => (
                  <Option key={c.id} value={c.id}>{c.name}</Option>
                ))}
              </Dropdown>
            </Field>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Period" required>
              <Dropdown
                placeholder="Select period"
                value={periods.data?.find((p) => p.id === periodId)?.name ?? ""}
                selectedOptions={periodId ? [periodId] : []}
                onOptionSelect={(_, dd) => setPeriodId(dd.optionValue ?? "")}
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
              <Input type="date" value={entryDate} onChange={(_, dd) => setEntryDate(dd.value)} />
            </Field>
          </div>
          <Field label="Memo">
            <Input value={memo} onChange={(_, dd) => setMemo(dd.value)} />
          </Field>

          <Text weight="semibold" style={{ marginTop: 8 }}>Lines</Text>
          <Table size="extra-small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Account</TableHeaderCell>
                <TableHeaderCell>Debit</TableHeaderCell>
                <TableHeaderCell>Credit</TableHeaderCell>
                <TableHeaderCell>Description</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((ln, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <Dropdown
                      placeholder="Account"
                      selectedOptions={ln.account_id ? [ln.account_id] : []}
                      value={
                        accountMap.get(ln.account_id)
                          ? `${accountMap.get(ln.account_id)!.code} - ${accountMap.get(ln.account_id)!.name}`
                          : ""
                      }
                      onOptionSelect={(_, dd) => {
                        const next = [...lines];
                        next[i] = { ...next[i], account_id: dd.optionValue ?? "" };
                        setLines(next);
                      }}
                    >
                      {renderAccountOptions()}
                    </Dropdown>
                  </TableCell>
                  <TableCell>
                    <Input
                      value={ln.debit}
                      onChange={(_, dd) => {
                        const next = [...lines];
                        next[i] = { ...next[i], debit: dd.value };
                        setLines(next);
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      value={ln.credit}
                      onChange={(_, dd) => {
                        const next = [...lines];
                        next[i] = { ...next[i], credit: dd.value };
                        setLines(next);
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      value={ln.description}
                      onChange={(_, dd) => {
                        const next = [...lines];
                        next[i] = { ...next[i], description: dd.value };
                        setLines(next);
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      appearance="subtle"
                      icon={<DeleteRegular />}
                      onClick={() => setLines(lines.filter((_, j) => j !== i))}
                      disabled={lines.length <= 2}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div>
            <Button
              appearance="secondary"
              icon={<AddRegular />}
              onClick={() => setLines([...lines, { account_id: "", debit: "", credit: "", description: "" }])}
            >
              Add line
            </Button>
          </div>

          <div className={styles.totals}>
            <span>Debits: <strong>{fmtMoney(totals.d)}</strong></span>
            <span>Credits: <strong>{fmtMoney(totals.c)}</strong></span>
            <Badge appearance="tint" color={totals.balanced ? "success" : "warning"}>
              {totals.balanced ? "balanced" : "unbalanced"}
            </Badge>
          </div>

          <div>
            <Button
              appearance="primary"
              disabled={!canPromoteDrafts || !clientId || !periodId || !totals.balanced || promote.isPending}
              title={promoteReason}
              onClick={() => promote.mutate()}
            >
              {promote.isPending ? <Spinner size="tiny" /> : "Promote to journal entry"}
            </Button>
            {!canPromoteDrafts && (
              <Caption1 block style={{ marginTop: 6, color: tokens.colorNeutralForeground3 }}>
                {blockedReason}
              </Caption1>
            )}
          </div>
        </div>
      </Section>
      )}

      <Section
        title="Reject this draft"
        help={{
          title: "When to reject",
          body: (
            <>
              Reject when the classifier produced something fundamentally
              wrong (wrong kind, wrong document, duplicate of an entry
              you already posted manually). Rejected drafts are kept for
              audit but do <b>not</b> post anything. The source document
              stays in the library; you can always re-classify it later
              (re-upload triggers a new draft) or post a manual journal
              entry from the Journal entries tab.
            </>
          ),
        }}
      >
        <Field label="Reason (optional)">
          <Textarea value={rejectReason} onChange={(_, dd) => setRejectReason(dd.value)} />
        </Field>
        <div style={{ marginTop: 12 }}>
          <Button
            appearance="secondary"
            disabled={!canPromoteDrafts || reject.isPending}
            title={blockedReason}
            onClick={() => reject.mutate()}
          >
            Reject draft
          </Button>
          {!canPromoteDrafts && (
            <Caption1 block style={{ marginTop: 6, color: tokens.colorNeutralForeground3 }}>
              {blockedReason}
            </Caption1>
          )}
        </div>
      </Section>
    </div>
  );
}


// --------------------------------------------------------------------------
// Source document preview pane.
// Streams the original uploaded file (PDF / image / text) inline so the
// reviewer can see what the classifier actually read. Fetches the bytes
// through ApiClient so the bearer token is attached, then turns them into
// a blob URL for the <iframe> / <img>.
// --------------------------------------------------------------------------
function SourceDocumentPreview({
  documentId,
}: {
  documentId: string;
}): JSX.Element {
  const api = useApi();
  const styles = usePreviewStyles();
  const [open, setOpen] = useState(true);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mime, setMime] = useState<string>("");
  const [filename, setFilename] = useState<string>("");

  // Pull doc metadata for the filename / content type so we can pick the
  // right renderer (PDF inline vs <img>).
  const detail = useQuery({
    queryKey: ["document-detail", documentId],
    queryFn: () => api.getDocument(documentId),
  });

  useEffect(() => {
    if (detail.data) {
      setMime(detail.data.content_type ?? "");
      setFilename(detail.data.filename ?? "");
    }
  }, [detail.data]);

  // Fetch + create object URL the first time the pane is opened (and
  // whenever the doc id changes). Revoke on unmount / change.
  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    if (!open) return;
    if (!documentId) return;
    setLoading(true);
    setError(null);
    api
      .downloadDocumentBlob(documentId)
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setUrl(createdUrl);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [api, documentId, open]);

  const lower = mime.toLowerCase();
  const isPdf = lower.includes("pdf") || filename.toLowerCase().endsWith(".pdf");
  const isImg = lower.startsWith("image/");
  const isText =
    lower.startsWith("text/") ||
    lower.includes("json") ||
    lower.includes("csv");

  return (
    <Section
      title="Source document"
      help={{
        title: "What is this?",
        body: (
          <>
            The original file you uploaded — the same bytes the
            classifier read. Useful for spot-checking that a parsed
            transaction (e.g. an amount or a vendor name) actually
            matches the page.
          </>
        ),
      }}
      toolbar={
        <div style={{ display: "flex", gap: 8 }}>
          {url && (
            <Button
              size="small"
              appearance="secondary"
              onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
            >
              Open in new tab
            </Button>
          )}
          <Button
            size="small"
            appearance="secondary"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Hide" : "Show"} preview
          </Button>
        </div>
      }
    >
      <Body1>
        <strong>{filename || "(no filename)"}</strong>
        {mime && <> · <code>{mime}</code></>}
      </Body1>
      {!open && (
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Preview hidden — click <i>Show preview</i> to load it.
        </Caption1>
      )}
      {open && loading && <LoadingState />}
      {open && error && (
        <Body1 style={{ color: tokens.colorPaletteRedForeground1 }}>
          Failed to load preview: {error}
        </Body1>
      )}
      {open && url && !loading && !error && (
        <div className={styles.frame}>
          {isPdf && (
            <iframe
              title="Source document preview"
              src={url}
              className={styles.iframe}
            />
          )}
          {isImg && (
            <img
              alt="Source document preview"
              src={url}
              className={styles.img}
            />
          )}
          {isText && <TextPreview url={url} />}
          {!isPdf && !isImg && !isText && (
            <Body1>
              Inline preview not supported for <code>{mime || "this type"}</code>.
              Use <i>Open in new tab</i> to view it.
            </Body1>
          )}
        </div>
      )}
    </Section>
  );
}


function TextPreview({ url }: { url: string }): JSX.Element {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((r) => r.text())
      .then((t) => {
        if (!cancelled) setText(t);
      })
      .catch(() => {
        if (!cancelled) setText("(failed to read)");
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  if (text === null) return <LoadingState />;
  return (
    <pre
      style={{
        margin: 0,
        padding: 12,
        backgroundColor: tokens.colorNeutralBackground2,
        borderRadius: tokens.borderRadiusMedium,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxHeight: 600,
        overflow: "auto",
        fontFamily: tokens.fontFamilyMonospace,
        fontSize: tokens.fontSizeBase200,
      }}
    >
      {text}
    </pre>
  );
}


const usePreviewStyles = makeStyles({
  frame: {
    marginTop: "8px",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    overflow: "hidden",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  iframe: {
    border: "none",
    width: "100%",
    height: "640px",
    display: "block",
  },
  img: {
    maxWidth: "100%",
    maxHeight: "640px",
    display: "block",
    margin: "0 auto",
  },
});
