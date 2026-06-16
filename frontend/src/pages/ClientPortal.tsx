import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError } from "../api/ApiClient";
import { useApi } from "../api/useApi";

const DOC_KINDS = [
  "generic",
  "w2",
  "1099_nec",
  "1099_int",
  "1098",
  "invoice",
  "receipt",
  "bank_statement",
];

/**
 * Client portal. A portal user can:
 *   - upload a document (kind-hint selector)
 *   - see the list of their own uploaded documents and their OCR status
 *   - see READ-ONLY drafts the AI has produced for their documents
 */
export default function ClientPortal() {
  const api = useApi();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [kindHint, setKindHint] = useState("generic");
  const [err, setErr] = useState<string | null>(null);

  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.listDocuments(),
    refetchInterval: 5000,
  });

  const drafts = useQuery({
    queryKey: ["drafts", "all"],
    queryFn: () => api.listDrafts(false),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, kindHint),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      if (fileRef.current) fileRef.current.value = "";
    },
    onError: (e) =>
      setErr(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)),
  });

  return (
    <div>
      <h2>Upload a document</h2>
      <div className="card">
        <div className="form-grid">
          <label htmlFor="kind">Kind</label>
          <select id="kind" value={kindHint} onChange={(e) => setKindHint(e.target.value)}>
            {DOC_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <label htmlFor="file">File</label>
          <input
            id="file"
            type="file"
            ref={fileRef}
            onChange={(e) => {
              setErr(null);
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
            }}
          />
        </div>
        {upload.isPending && <p>Uploading…</p>}
        {upload.isSuccess && (
          <p className="muted">
            Uploaded. Source doc ID:{" "}
            <code>{upload.data?.source_document_id}</code>
            {upload.data?.deduped && " (deduped against an earlier upload)"}
          </p>
        )}
        {err && <p className="error">{err}</p>}
      </div>

      <h2>Your documents</h2>
      {docs.isLoading && <p>Loading…</p>}
      {docs.data && docs.data.length === 0 && (
        <p className="muted">No documents uploaded yet.</p>
      )}
      {docs.data && docs.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Filename</th>
              <th>Kind</th>
              <th>OCR status</th>
              <th>Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {docs.data.map((d) => (
              <tr key={d.id}>
                <td>{d.filename ?? <span className="muted">(unnamed)</span>}</td>
                <td>{d.kind}</td>
                <td>
                  <span
                    className={`badge ${
                      d.ocr_status === "complete"
                        ? "high"
                        : d.ocr_status === "failed"
                        ? "error"
                        : ""
                    }`}
                  >
                    {d.ocr_status}
                  </span>
                  {d.ocr_error && (
                    <span className="muted" title={d.ocr_error}>
                      {" "}
                      ⚠
                    </span>
                  )}
                </td>
                <td className="muted">{new Date(d.received_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 style={{ marginTop: 24 }}>Drafts (read-only)</h2>
      <p className="muted">
        These are the AI's preliminary classifications. Your CPA firm will
        review and post them.
      </p>
      {drafts.data && drafts.data.length === 0 && (
        <p className="muted">No drafts yet.</p>
      )}
      {drafts.data && drafts.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Status</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {drafts.data.map((d) => {
              const conf = Number.parseFloat(d.confidence);
              return (
                <tr key={d.id}>
                  <td>{d.kind}</td>
                  <td>{d.status}</td>
                  <td>{(conf * 100).toFixed(1)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
