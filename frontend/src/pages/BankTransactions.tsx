import {
  Badge,
  Button,
  Caption1,
  Toast,
  Toaster,
  ToastTitle,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import type { DraftOut } from "../auth/types";
import { roleDisplayName } from "../auth/firmRole";
import { useFirmRole } from "../auth/useFirmRole";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

type TxnStatus = "pending" | "posted" | "excluded";

interface TxnRow {
  key: string;
  draftId: string;
  txnIndex: number;
  status: TxnStatus;
  rawDate: string;
  isoDate: string;
  description: string;
  direction: string;
  amount: string;
  accountCode: string;
}

function parseIndexList(value: unknown): Set<number> {
  if (!Array.isArray(value)) return new Set<number>();
  const out = new Set<number>();
  for (const raw of value) {
    const n = Number(raw);
    if (Number.isInteger(n) && n >= 0) out.add(n);
  }
  return out;
}

function buildRows(draft: DraftOut): TxnRow[] {
  const payload = draft.payload ?? {};
  if (payload.is_statement !== true) return [];

  const txns = Array.isArray(payload.transactions)
    ? (payload.transactions as Array<Record<string, unknown>>)
    : [];

  const posted = parseIndexList(payload._posted_indexes);
  const excluded = parseIndexList(payload._excluded_indexes);

  // Backward compatibility for statement drafts promoted before per-row
  // status tracking existed.
  if (posted.size === 0 && excluded.size === 0) {
    if (draft.status === "promoted") {
      for (let i = 0; i < txns.length; i += 1) posted.add(i);
    } else if (draft.status === "rejected") {
      for (let i = 0; i < txns.length; i += 1) excluded.add(i);
    }
  }

  return txns.map((txn, idx) => {
    const status: TxnStatus = posted.has(idx)
      ? "posted"
      : excluded.has(idx)
        ? "excluded"
        : "pending";
    return {
      key: `${draft.id}:${idx}`,
      draftId: draft.id,
      txnIndex: idx,
      status,
      rawDate: String(txn.raw_date ?? ""),
      isoDate: String(txn.date ?? ""),
      description: String(txn.description ?? ""),
      direction: String(txn.direction ?? ""),
      amount: String(txn.amount ?? ""),
      accountCode: String(txn.proposed_account_code ?? ""),
    };
  });
}

export default function BankTransactions() {
  const api = useApi();
  const qc = useQueryClient();
  const { capabilities, role, isLoading: roleLoading } = useFirmRole();
  const toasterId = useId("bank-tx-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const drafts = useQuery({
    queryKey: ["drafts", "all"],
    queryFn: () => api.listDrafts(false),
  });

  const rows = (drafts.data ?? [])
    .filter((d) => d.kind === "bank_transaction")
    .flatMap((d) => buildRows(d))
    .sort((a, b) => {
      // Most recent first when ISO dates are present.
      if (a.isoDate && b.isoDate) return b.isoDate.localeCompare(a.isoDate);
      if (a.isoDate) return -1;
      if (b.isoDate) return 1;
      return 0;
    });

  const [pendingRows, postedRows, excludedRows] = [
    rows.filter((r) => r.status === "pending"),
    rows.filter((r) => r.status === "posted"),
    rows.filter((r) => r.status === "excluded"),
  ];

  const pending = pendingRows.length;
  const posted = postedRows.length;
  const excluded = excludedRows.length;

  const learnRule = useMutation({
    mutationFn: (input: { draftId: string; transactionIndex: number; code: string }) =>
      api.learnStatementRule(input.draftId, {
        transaction_index: input.transactionIndex,
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

  return (
    <div style={{ display: "grid", rowGap: 16 }}>
      <Toaster toasterId={toasterId} />
      <div>
        <Text size={700} weight="semibold" block>
          Bank transactions
        </Text>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          All statement transactions across drafts, grouped by Pending, Posted, and Excluded.
        </Caption1>
        {roleLoading ? (
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            Resolving your team role...
          </Caption1>
        ) : !capabilities.canPromoteDrafts ? (
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            Your role ({role ? roleDisplayName(role) : "unknown"}) can view transactions but cannot post or exclude from here.
          </Caption1>
        ) : null}
      </div>

      <Section title={`All transactions (${rows.length})`}>
        {drafts.isLoading && <LoadingState />}
        {drafts.error && <ErrorState error={drafts.error} />}
        {drafts.data && rows.length === 0 && (
          <EmptyState
            title="No statement transactions yet"
            description="Upload and classify a bank statement to populate this view."
          />
        )}
        {rows.length > 0 && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <Badge appearance="filled" color="warning">Pending {pending}</Badge>
              <Badge appearance="filled" color="success">Posted {posted}</Badge>
              <Badge appearance="filled" color="danger">Excluded {excluded}</Badge>
            </div>
            <Table size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Date</TableHeaderCell>
                  <TableHeaderCell>Description</TableHeaderCell>
                  <TableHeaderCell>Direction</TableHeaderCell>
                  <TableHeaderCell>Amount</TableHeaderCell>
                  <TableHeaderCell>Account</TableHeaderCell>
                  <TableHeaderCell>Draft</TableHeaderCell>
                  <TableHeaderCell>Rule</TableHeaderCell>
                  <TableHeaderCell></TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.key}>
                    <TableCell>
                      <Badge
                        appearance="filled"
                        color={
                          row.status === "posted"
                            ? "success"
                            : row.status === "excluded"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {row.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <code>{row.rawDate || row.isoDate || "-"}</code>
                    </TableCell>
                    <TableCell>{row.description || "-"}</TableCell>
                    <TableCell>{row.direction || "-"}</TableCell>
                    <TableCell>
                      <code>{row.amount || "-"}</code>
                    </TableCell>
                    <TableCell>
                      <code>{row.accountCode || "-"}</code>
                    </TableCell>
                    <TableCell>
                      <code>{shortId(row.draftId)}</code>
                    </TableCell>
                    <TableCell>
                      <Button
                        size="small"
                        appearance="subtle"
                        disabled={!capabilities.canPromoteDrafts || !row.accountCode || learnRule.isPending}
                        onClick={() =>
                          learnRule.mutate({
                            draftId: row.draftId,
                            transactionIndex: row.txnIndex,
                            code: row.accountCode,
                          })
                        }
                      >
                        Learn rule
                      </Button>
                    </TableCell>
                    <TableCell>
                      <Link to={`/drafts/${row.draftId}`}>
                        <Button appearance="subtle">Open draft</Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </Section>
    </div>
  );
}
