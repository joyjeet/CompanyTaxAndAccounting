import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/ApiClient";
import { useApi } from "../api/useApi";
import type { DraftOut } from "../auth/types";

interface LineDraft {
  account_id: string;
  debit: string;
  credit: string;
  description: string;
}

/**
 * Draft detail page. Shows the AI-extracted payload + the proposed lines
 * (if any) and lets the reviewer promote into a real journal entry or
 * reject. Promotion is the ONLY path that crosses into the ledger; the
 * backend enforces SUM(debits) == SUM(credits).
 */
export default function DraftDetail() {
  const { id } = useParams<{ id: string }>();
  const api = useApi();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const draft = useQuery({
    queryKey: ["drafts", "all"],
    queryFn: () => api.listDrafts(false),
    select: (rows: DraftOut[]) => rows.find((r) => r.id === id) ?? null,
  });

  const [periodId, setPeriodId] = useState("");
  const [entryDate, setEntryDate] = useState(new Date().toISOString().slice(0, 10));
  const [memo, setMemo] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([
    { account_id: "", debit: "", credit: "", description: "" },
    { account_id: "", debit: "", credit: "", description: "" },
  ]);
  const [rejectReason, setRejectReason] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const promote = useMutation({
    mutationFn: () =>
      api.promoteDraft(id!, {
        period_id: periodId.trim(),
        entry_date: entryDate,
        memo: memo.trim() || undefined,
        lines: lines
          .filter((l) => l.account_id.trim())
          .map((l) => ({
            account_id: l.account_id.trim(),
            debit: l.debit.trim() || "0",
            credit: l.credit.trim() || "0",
            description: l.description.trim() || undefined,
          })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["drafts"] });
      navigate("/", { replace: true });
    },
    onError: (e) =>
      setErr(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)),
  });

  const reject = useMutation({
    mutationFn: () => api.rejectDraft(id!, rejectReason.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["drafts"] });
      navigate("/", { replace: true });
    },
    onError: (e) =>
      setErr(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)),
  });

  if (draft.isLoading) return <p>Loading…</p>;
  if (!draft.data) return <p className="muted">Draft not found.</p>;

  const d = draft.data;
  const conf = Number.parseFloat(d.confidence);

  function setLine(i: number, patch: Partial<LineDraft>) {
    setLines((rows) => rows.map((r, j) => (i === j ? { ...r, ...patch } : r)));
  }

  function addLine() {
    setLines((rows) => [
      ...rows,
      { account_id: "", debit: "", credit: "", description: "" },
    ]);
  }

  return (
    <div>
      <h2>
        Draft <span className="muted">({d.kind})</span>
      </h2>
      <div className="card">
        <p>
          <strong>Confidence:</strong> {(conf * 100).toFixed(1)}%{" "}
          {d.high_confidence && <span className="badge high">high</span>}
          {!d.high_confidence && conf < 0.6 && <span className="badge low">low</span>}
        </p>
        <p>
          <strong>Status:</strong> {d.status}
          {" · "}
          <strong>Model:</strong> {d.model}
        </p>
        <p>
          <strong>Source document:</strong> <code>{d.source_document_id}</code>
        </p>
        <details>
          <summary>AI payload</summary>
          <pre style={{ overflow: "auto" }}>{JSON.stringify(d.payload, null, 2)}</pre>
        </details>
      </div>

      <div className="card">
        <h3>Promote to journal entry</h3>
        <p className="muted">
          Each line must specify either a debit OR a credit (not both). The backend
          rejects any entry where debits ≠ credits.
        </p>
        <div className="form-grid">
          <label htmlFor="period">Period ID</label>
          <input
            id="period"
            placeholder="UUID"
            value={periodId}
            onChange={(e) => setPeriodId(e.target.value)}
          />
          <label htmlFor="date">Entry date</label>
          <input
            id="date"
            type="date"
            value={entryDate}
            onChange={(e) => setEntryDate(e.target.value)}
          />
          <label htmlFor="memo">Memo</label>
          <input
            id="memo"
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />
        </div>

        <table style={{ marginTop: 16 }}>
          <thead>
            <tr>
              <th>Account ID</th>
              <th>Debit</th>
              <th>Credit</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td>
                  <input
                    placeholder="UUID"
                    value={l.account_id}
                    onChange={(e) => setLine(i, { account_id: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    placeholder="0.00"
                    value={l.debit}
                    onChange={(e) => setLine(i, { debit: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    placeholder="0.00"
                    value={l.credit}
                    onChange={(e) => setLine(i, { credit: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    value={l.description}
                    onChange={(e) => setLine(i, { description: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          <button onClick={addLine}>+ Add line</button>
        </p>

        <button
          className="primary"
          disabled={promote.isPending || !periodId}
          onClick={() => {
            setErr(null);
            promote.mutate();
          }}
        >
          {promote.isPending ? "Promoting…" : "Promote"}
        </button>
      </div>

      <div className="card">
        <h3>Reject</h3>
        <input
          placeholder="Reason (optional)"
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          style={{ width: "60%", marginRight: 12 }}
        />
        <button
          className="danger"
          disabled={reject.isPending}
          onClick={() => {
            setErr(null);
            reject.mutate();
          }}
        >
          {reject.isPending ? "Rejecting…" : "Reject"}
        </button>
      </div>

      {err && <p className="error">{err}</p>}
    </div>
  );
}
