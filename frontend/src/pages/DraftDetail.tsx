import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  makeStyles,
  Option,
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
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";
import { fmtMoney, shortId, todayIso } from "../lib/format";

interface DraftLine {
  account_id: string;
  debit: string;
  credit: string;
  description: string;
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
  const { identity } = useAuth();
  const toasterId = useId("draft-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const draft = useQuery({
    queryKey: ["drafts", "all"],
    queryFn: () => api.listDrafts(false),
    select: (rows) => rows.find((r) => r.id === id) ?? null,
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

  const [periodId, setPeriodId] = useState("");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [memo, setMemo] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([
    { account_id: "", debit: "", credit: "", description: "" },
    { account_id: "", debit: "", credit: "", description: "" },
  ]);
  const [rejectReason, setRejectReason] = useState("");

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

  if (draft.isLoading) return <LoadingState />;
  if (draft.error) return <ErrorState error={draft.error} />;
  if (!draft.data) return <Body1>Draft not found.</Body1>;

  const d = draft.data;
  const conf = Number.parseFloat(d.confidence);

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

      <Section
        title="AI classification"
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
        <details style={{ marginTop: 12 }}>
          <summary>Raw payload</summary>
          <pre className={styles.payload}>{JSON.stringify(d.payload, null, 2)}</pre>
        </details>
      </Section>

      <Section title="Promote to journal entry">
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
                      value={accountMap.get(ln.account_id)?.name ?? ""}
                      onOptionSelect={(_, dd) => {
                        const next = [...lines];
                        next[i] = { ...next[i], account_id: dd.optionValue ?? "" };
                        setLines(next);
                      }}
                    >
                      {(accounts.data ?? []).map((a) => (
                        <Option key={a.id} value={a.id} text={`${a.code} — ${a.name}`}>
                          {a.code} — {a.name}
                        </Option>
                      ))}
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
              disabled={!clientId || !periodId || !totals.balanced || promote.isPending}
              onClick={() => promote.mutate()}
            >
              {promote.isPending ? <Spinner size="tiny" /> : "Promote to journal entry"}
            </Button>
          </div>
        </div>
      </Section>

      <Section title="Reject this draft">
        <Field label="Reason (optional)">
          <Textarea value={rejectReason} onChange={(_, dd) => setRejectReason(dd.value)} />
        </Field>
        <div style={{ marginTop: 12 }}>
          <Button
            appearance="secondary"
            disabled={reject.isPending}
            onClick={() => reject.mutate()}
          >
            Reject draft
          </Button>
        </div>
      </Section>
    </div>
  );
}
