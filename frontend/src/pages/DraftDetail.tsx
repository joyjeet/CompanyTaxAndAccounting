import {
  Badge,
  Body1,
  Button,
  Caption1,
  Combobox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
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
import { useEffectiveIdentity } from "../auth/TenantContext";
import { useFirmRole } from "../auth/useFirmRole";
import type { AccountType, CoaOut } from "../auth/types";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";
import { fmtMoney, shortId, todayIso } from "../lib/format";
import { statementRangeFromTxns } from "../lib/statementPeriod";
import {
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

/**
 * Sentinel option value for the "create a new account" row that sits at the
 * bottom of every account picker. Reviewers routinely hit a transaction that
 * has no home in the client's chart yet; making them leave the draft, add the
 * account, and come back loses their in-progress categorizations.
 */
const NEW_ACCOUNT_OPTION = "__ctaa_new_account__";

interface AccountGroup {
  type: string;
  label: string;
  accounts: CoaOut[];
}

/**
 * Searchable account picker. A client's chart of accounts routinely runs to a
 * hundred-plus rows, so a plain dropdown is unusable while triaging the queue.
 * This filters the grouped options against what the reviewer types (matching
 * both code and name) while keeping the grouping and the "+ New account" row.
 */
export function AccountPicker({
  groups,
  selectedId,
  label,
  allowCreate,
  onPick,
  onCreateNew,
}: {
  groups: AccountGroup[];
  selectedId?: string;
  label: string;
  allowCreate: boolean;
  onPick: (accountId: string) => void;
  onCreateNew: () => void;
}) {
  // undefined => idle (show the selected account's label); string => filtering.
  const [query, setQuery] = useState<string | undefined>(undefined);
  const filter = (query ?? "").trim().toLowerCase();
  const filtered = useMemo(
    () =>
      groups
        .map((g) => ({
          ...g,
          accounts:
            filter === ""
              ? g.accounts
              : g.accounts.filter((a) =>
                  `${a.code} ${a.name}`.toLowerCase().includes(filter),
                ),
        }))
        .filter((g) => g.accounts.length > 0),
    [groups, filter],
  );

  return (
    <Combobox
      aria-label="Account"
      placeholder="Search accounts…"
      style={{ width: "100%", minWidth: 200 }}
      value={query ?? label}
      selectedOptions={selectedId ? [selectedId] : []}
      onChange={(e) => setQuery(e.target.value)}
      onOptionSelect={(_, data) => {
        // Fluent fires onOptionSelect with an undefined optionValue when it
        // auto-clears the selection — which happens on every keystroke that
        // doesn't prefix-match the current option (e.g. typing a name, since
        // the option text starts with the code). Ignore it, or the search box
        // would be wiped and only code (prefix) searches would ever filter.
        if (!data.optionValue) return;
        if (data.optionValue === NEW_ACCOUNT_OPTION) {
          onCreateNew();
        } else {
          onPick(data.optionValue);
        }
        setQuery(undefined);
      }}
      onOpenChange={(_, data) => {
        // Open with an empty box so the reviewer can just start typing to
        // search; closing without a pick restores the selected account label.
        setQuery(data.open ? "" : undefined);
      }}
    >
      {filtered.map((group) => (
        <OptionGroup key={group.type} label={group.label}>
          {group.accounts.map((a) => (
            <Option key={a.id} value={a.id} text={`${a.code} — ${a.name}`}>
              {a.code} — {a.name}
            </Option>
          ))}
        </OptionGroup>
      ))}
      {filtered.length === 0 && (
        <Option value="__no_match__" disabled text="No matching accounts">
          No matching accounts
        </Option>
      )}
      {allowCreate && (
        <OptionGroup label="Chart of accounts">
          <Option value={NEW_ACCOUNT_OPTION} text="+ New account...">
            + New account...
          </Option>
        </OptionGroup>
      )}
    </Combobox>
  );
}

interface NewAccountDraft {
  /** Applies the created account back to the picker that opened the dialog. */
  apply: (account: CoaOut) => void;
  code: string;
  name: string;
  accountType: AccountType;
}

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
  const identity = useEffectiveIdentity();
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

  const [newAccount, setNewAccount] = useState<NewAccountDraft | null>(null);

  const createAccount = useMutation({
    mutationFn: (input: NewAccountDraft) =>
      api.createAccount(clientId, {
        code: input.code.trim(),
        name: input.name.trim(),
        account_type: input.accountType,
        parent_account_id: null,
      }),
    onSuccess: async (created, input) => {
      // Refetch before applying so the picker can resolve the new id.
      await qc.invalidateQueries({ queryKey: ["accounts", clientId] });
      input.apply(created);
      setNewAccount(null);
      dispatchToast(
        <Toast>
          <ToastTitle>Created {created.code} — {created.name}</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

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
  const [activeTxnTab, setActiveTxnTab] = useState<"pending" | "posted" | "excluded">("pending");
  const [postedIndexes, setPostedIndexes] = useState<number[]>([]);
  const [excludedIndexes, setExcludedIndexes] = useState<number[]>([]);

  const persistedPostedIndexes = useMemo(() => {
    const raw = payload._posted_indexes;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((v) => Number(v))
      .filter((n) => Number.isInteger(n) && n >= 0);
  }, [payload._posted_indexes]);

  const persistedExcludedIndexes = useMemo(() => {
    const raw = payload._excluded_indexes;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((v) => Number(v))
      .filter((n) => Number.isInteger(n) && n >= 0);
  }, [payload._excluded_indexes]);

  useEffect(() => {
    setPostedIndexes(persistedPostedIndexes);
    setExcludedIndexes(persistedExcludedIndexes);
    setActiveTxnTab("pending");
  }, [id, persistedPostedIndexes, persistedExcludedIndexes]);

  // ----- Statement date span ---------------------------------------------
  // Purely informational: the books are continuous, so every transaction is
  // posted on its own date. We surface the span so a reviewer can sanity-check
  // it, and warn when the parser could not infer dates at all.
  const statementRange = useMemo(() => statementRangeFromTxns(rawTxns), [rawTxns]);

  const applyTxnDecision = useMutation({
    mutationFn: (input: { mode: "accept" | "reject"; indexes: number[] }) => {
      const overrides: Record<string, string> = {};
      for (const [idx, code] of Object.entries(txnOverrides)) {
        if (code) overrides[String(idx)] = code;
      }

      const acceptedIndexes = input.mode === "accept" ? input.indexes : [];
      const rejectedIndexes = input.mode === "reject" ? input.indexes : [];

      return api.promoteStatementDraft(id, {
        client_id: clientId || undefined,
        cash_account_code: "1000",
        account_overrides: Object.keys(overrides).length ? overrides : undefined,
        accepted_indexes: acceptedIndexes,
        rejected_indexes: rejectedIndexes,
      });
    },
    onSuccess: (res, vars) => {
      setPostedIndexes(res.posted_indexes);
      setExcludedIndexes(res.excluded_indexes);

      const postedNow = res.journal_entry_ids.length;
      const excludedNow = vars.mode === "reject" ? vars.indexes.length : 0;
      const learnedNow = res.learned_rule_count;

      dispatchToast(
        <Toast>
          <ToastTitle>
            {vars.mode === "accept"
              ? `Posted ${postedNow} transaction${postedNow === 1 ? "" : "s"}`
              : `Excluded ${excludedNow} transaction${excludedNow === 1 ? "" : "s"}`}
            {learnedNow > 0 ? ` · Learned ${learnedNow} rule${learnedNow === 1 ? "" : "s"}` : ""}
          </ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["drafts"] });
      qc.invalidateQueries({ queryKey: ["entries"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const learnTxnRule = useMutation({
    mutationFn: (input: { index: number; code: string }) =>
      api.learnStatementRule(id, {
        client_id: clientId || undefined,
        transaction_index: input.index,
        target_account_code: input.code,
      }),
    onSuccess: (res) => {
      dispatchToast(
        <Toast>
          <ToastTitle>
            Learned {res.learned_rule_count} rule{res.learned_rule_count === 1 ? "" : "s"} for future categorization.
          </ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["rules-engine"] });
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
  const promoteReason = promoteDisabledReason({
    canPromoteDrafts,
    role,
    clientId,
    balanced: totals.balanced,
  });

  /**
   * Wraps a picker's selection handler so choosing the sentinel row opens the
   * create-account dialog instead of selecting a non-existent account.
   */
  const openNewAccount = (apply: (account: CoaOut) => void) =>
    setNewAccount({ apply, code: "", name: "", accountType: "expense" });

  const postedSet = new Set(postedIndexes);
  const excludedSet = new Set(excludedIndexes);
  const pendingIndexes = rawTxns
    .map((_, i) => i)
    .filter((i) => !postedSet.has(i) && !excludedSet.has(i));
  const displayedIndexes =
    activeTxnTab === "pending"
      ? pendingIndexes
      : activeTxnTab === "posted"
        ? rawTxns.map((_, i) => i).filter((i) => postedSet.has(i))
        : rawTxns.map((_, i) => i).filter((i) => excludedSet.has(i));

  return (
    <div style={{ display: "grid", rowGap: 16 }}>
      <Toaster toasterId={toasterId} />

      <Dialog
        open={newAccount !== null}
        onOpenChange={(_, data) => {
          if (!data.open) setNewAccount(null);
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>New account</DialogTitle>
            <DialogContent>
              <div style={{ display: "grid", rowGap: 12, paddingTop: 4 }}>
                <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                  Adds the account to this client's chart of accounts and selects
                  it here, so you keep your place in the review.
                </Caption1>
                <Field label="Code" required>
                  <Input
                    value={newAccount?.code ?? ""}
                    placeholder="6150"
                    onChange={(_, d) =>
                      setNewAccount((prev) => (prev ? { ...prev, code: d.value } : prev))
                    }
                  />
                </Field>
                <Field label="Name" required>
                  <Input
                    value={newAccount?.name ?? ""}
                    placeholder="Software subscriptions"
                    onChange={(_, d) =>
                      setNewAccount((prev) => (prev ? { ...prev, name: d.value } : prev))
                    }
                  />
                </Field>
                <Field
                  label="Type"
                  required
                  hint="Decides where the account lands on the P&L and balance sheet."
                >
                  <Dropdown
                    value={
                      newAccount ? ACCOUNT_TYPE_LABELS[newAccount.accountType] : ""
                    }
                    selectedOptions={newAccount ? [newAccount.accountType] : []}
                    onOptionSelect={(_, d) =>
                      setNewAccount((prev) =>
                        prev
                          ? { ...prev, accountType: (d.optionValue as AccountType) ?? prev.accountType }
                          : prev,
                      )
                    }
                  >
                    {ACCOUNT_TYPE_ORDER.map((type) => (
                      <Option key={type} value={type} text={ACCOUNT_TYPE_LABELS[type]}>
                        {ACCOUNT_TYPE_LABELS[type]}
                      </Option>
                    ))}
                  </Dropdown>
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setNewAccount(null)}>
                Cancel
              </Button>
              <Button
                appearance="primary"
                disabled={
                  !newAccount ||
                  !newAccount.code.trim() ||
                  !newAccount.name.trim() ||
                  createAccount.isPending
                }
                onClick={() => newAccount && createAccount.mutate(newAccount)}
              >
                {createAccount.isPending ? "Creating..." : "Create and select"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
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
          title={`Bank transactions (${rawTxns.length})`}
          help={{
            title: "Pending, posted, and excluded workflow",
            body: (
              <>
                Each row starts in <b>Pending</b>. Clicking <b>Accept</b>
                posts it immediately (one journal entry per row) and moves it
                to <b>Posted</b>. Clicking <b>Reject</b> excludes it
                immediately and moves it to <b>Excluded</b>.
                <br /><br />
                Use <b>Accept all pending</b> or <b>Reject all pending</b> to
                process all remaining rows in one click. The tabs let you
                switch between pending work and historical posted/excluded rows.
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
                <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                  <Button
                    appearance={activeTxnTab === "pending" ? "primary" : "secondary"}
                    onClick={() => setActiveTxnTab("pending")}
                  >
                    Pending ({pendingIndexes.length})
                  </Button>
                  <Button
                    appearance={activeTxnTab === "posted" ? "primary" : "secondary"}
                    onClick={() => setActiveTxnTab("posted")}
                  >
                    Posted ({postedIndexes.length})
                  </Button>
                  <Button
                    appearance={activeTxnTab === "excluded" ? "primary" : "secondary"}
                    onClick={() => setActiveTxnTab("excluded")}
                  >
                    Excluded ({excludedIndexes.length})
                  </Button>
                </div>

                <Table size="extra-small" style={{ marginTop: 8 }}>
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>Date</TableHeaderCell>
                      <TableHeaderCell>Description</TableHeaderCell>
                      <TableHeaderCell>Direction</TableHeaderCell>
                      <TableHeaderCell>Amount</TableHeaderCell>
                      <TableHeaderCell>Account</TableHeaderCell>
                      <TableHeaderCell>Status / Action</TableHeaderCell>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {displayedIndexes.map((i) => {
                      const t = rawTxns[i] ?? {};
                      const proposed = String(t.proposed_account_code ?? "");
                      const normalizedProposed =
                        accountCodeMap.has(proposed)
                          ? proposed
                          : (suspenseAccount?.code ?? proposed);
                      const current = txnOverrides[i] ?? normalizedProposed;
                      const acct = accountCodeMap.get(current);
                      const dir = String(t.direction ?? "");
                      const status = postedSet.has(i)
                        ? "posted"
                        : excludedSet.has(i)
                          ? "excluded"
                          : "pending";
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
                            {status === "pending" ? (
                              <AccountPicker
                                groups={groupedAccounts}
                                selectedId={acct?.id}
                                label={accountLabelByCode(current)}
                                allowCreate={!!canPromoteDrafts && !!clientId}
                                onCreateNew={() =>
                                  openNewAccount((created) =>
                                    setTxnOverrides((prev) => ({ ...prev, [i]: created.code })),
                                  )
                                }
                                onPick={(accountId) => {
                                  const newAcct = (accounts.data ?? []).find(
                                    (a) => a.id === accountId,
                                  );
                                  if (newAcct) {
                                    setTxnOverrides((prev) => ({ ...prev, [i]: newAcct.code }));
                                  }
                                }}
                              />
                            ) : (
                              <Body1>{accountLabelByCode(current) || "—"}</Body1>
                            )}
                          </TableCell>
                          <TableCell>
                            {status === "pending" ? (
                              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                                <Button
                                  size="small"
                                  appearance="primary"
                                  disabled={!canPromoteDrafts || !clientId || applyTxnDecision.isPending || learnTxnRule.isPending}
                                  onClick={() => applyTxnDecision.mutate({ mode: "accept", indexes: [i] })}
                                >
                                  Accept
                                </Button>
                                <Button
                                  size="small"
                                  appearance="secondary"
                                  disabled={!canPromoteDrafts || !clientId || applyTxnDecision.isPending || learnTxnRule.isPending}
                                  onClick={() => applyTxnDecision.mutate({ mode: "reject", indexes: [i] })}
                                >
                                  Reject
                                </Button>
                                <Button
                                  size="small"
                                  appearance="subtle"
                                  disabled={!canPromoteDrafts || !current || applyTxnDecision.isPending || learnTxnRule.isPending}
                                  onClick={() => learnTxnRule.mutate({ index: i, code: current })}
                                >
                                  Learn rule
                                </Button>
                              </div>
                            ) : (
                              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", alignItems: "center" }}>
                                <Badge appearance="filled" color={status === "posted" ? "success" : "danger"}>
                                  {status === "posted" ? "Posted" : "Excluded"}
                                </Badge>
                                <Button
                                  size="small"
                                  appearance="subtle"
                                  disabled={!canPromoteDrafts || !current || applyTxnDecision.isPending || learnTxnRule.isPending}
                                  onClick={() => learnTxnRule.mutate({ index: i, code: current })}
                                >
                                  Learn rule
                                </Button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Button
                    appearance="secondary"
                    disabled={
                      !canPromoteDrafts ||
                      !clientId ||
                      applyTxnDecision.isPending ||
                      pendingIndexes.length === 0
                    }
                    onClick={() => applyTxnDecision.mutate({ mode: "accept", indexes: pendingIndexes })}
                  >
                    Accept all pending
                  </Button>
                  <Button
                    appearance="secondary"
                    disabled={
                      !canPromoteDrafts ||
                      !clientId ||
                      applyTxnDecision.isPending ||
                      pendingIndexes.length === 0
                    }
                    onClick={() => applyTxnDecision.mutate({ mode: "reject", indexes: pendingIndexes })}
                  >
                    Reject all pending
                  </Button>
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    {pendingIndexes.length} pending, {postedIndexes.length} posted, {excludedIndexes.length} excluded.
                  </Caption1>
                </div>
                {!statementRange && (
                  <MessageBar intent="info" style={{ marginTop: 12 }}>
                    <MessageBarBody>
                      <MessageBarTitle>No transaction dates detected.</MessageBarTitle>
                      <Body1 block>
                        The parser could not infer full calendar dates for these
                        rows, so they will be posted using today's date. Check
                        the dates on the resulting entries before finalising.
                      </Body1>
                    </MessageBarBody>
                  </MessageBar>
                )}
                {applyTxnDecision.isPending && (
                  <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
                    <Spinner size="tiny" />
                    <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                      Processing transactions...
                    </Caption1>
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
              entry</b> dated on the entry date you choose. The entry is
              immutable after posting (correction = reversing entry, not
              edit) and immediately affects the trial balance, P&amp;L,
              balance sheet, and downstream tax worksheets.
              <br /><br />
              <b>Required:</b>
              <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                <li>Every line needs an account, a debit OR a credit (not both), and the total debits must equal total credits.</li>
                <li>An entry date — the books are continuous, so any date is accepted and the entry is filed under it.</li>
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
          <Field
            label="Entry date"
            required
            hint="The books are continuous — the entry is recorded on this exact date."
          >
            <Input type="date" value={entryDate} onChange={(_, dd) => setEntryDate(dd.value)} />
          </Field>
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
                    <AccountPicker
                      groups={groupedAccounts}
                      selectedId={ln.account_id || undefined}
                      label={
                        accountMap.get(ln.account_id)
                          ? `${accountMap.get(ln.account_id)!.code} - ${accountMap.get(ln.account_id)!.name}`
                          : ""
                      }
                      allowCreate={!!canPromoteDrafts && !!clientId}
                      onCreateNew={() =>
                        openNewAccount((created) =>
                          setLines((prev) => {
                            const next = [...prev];
                            next[i] = { ...next[i], account_id: created.id };
                            return next;
                          }),
                        )
                      }
                      onPick={(accountId) => {
                        const next = [...lines];
                        next[i] = { ...next[i], account_id: accountId };
                        setLines(next);
                      }}
                    />
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
              disabled={!canPromoteDrafts || !clientId || !totals.balanced || promote.isPending}
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
