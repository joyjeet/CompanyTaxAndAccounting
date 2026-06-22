import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Toast,
  ToastBody,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { ArrowUploadRegular, DatabaseSearchRegular, DeleteRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../../api/useApi";
import InfoHint from "../../components/InfoHint";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDateTime, shortId } from "../../lib/format";
import DocumentDetailDialog from "./DocumentDetailDialog";

const useStyles = makeStyles({
  uploader: {
    display: "flex",
    columnGap: "12px",
    alignItems: "flex-end",
    marginBottom: "16px",
    backgroundColor: tokens.colorNeutralBackground2,
    padding: "16px",
    borderRadius: tokens.borderRadiusMedium,
  },
});

// Maps backend OcrStatus values (pending/in_progress/complete/failed) to
// Fluent UI Badge colors.
const OCR_COLORS: Record<string, "success" | "warning" | "danger" | "informative"> = {
  complete: "success",
  failed: "danger",
  in_progress: "warning",
  pending: "informative",
};

export default function DocumentsTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("docs-toaster");
  const { dispatchToast } = useToastController(toasterId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [kindHint, setKindHint] = useState("generic");
  // Document detail dialog: when set, the click-to-view modal is open.
  const [openDocId, setOpenDocId] = useState<string | null>(null);

  // Setup-state checks: a brand-new client has no periods/accounts, so any
  // upload would land as a draft with nowhere to be promoted to. We surface
  // a one-click "Seed defaults" banner in that case.
  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });
  const needsSetup =
    (periods.data && periods.data.length === 0) ||
    (accounts.data && accounts.data.length === 0);

  const seed = useMutation({
    mutationFn: () => api.seedDefaults(clientId, true),
    onSuccess: (r) => {
      const created = r.accounts_created.length;
      const samples = r.sample_entries_posted;
      dispatchToast(
        <Toast>
          <ToastTitle>Demo data seeded</ToastTitle>
          <ToastBody>
            {created} new accounts, period {r.period_created ? "created" : "already existed"}, {samples} sample entries posted.
          </ToastBody>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["accounts", clientId] });
      qc.invalidateQueries({ queryKey: ["periods", clientId] });
      qc.invalidateQueries({ queryKey: ["entries", clientId] });
      qc.invalidateQueries({ queryKey: ["tb", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  // Demo helper: wipe transactional data (docs, drafts, JEs, artifacts) so a
  // fresh upload-to-statement flow can be exercised. Keeps accounts + period.
  const [resetOpen, setResetOpen] = useState(false);
  const reset = useMutation({
    mutationFn: () => api.resetClient(clientId, true),
    onSuccess: (r) => {
      const total = Object.values(r.deleted).reduce((a, b) => a + b, 0);
      dispatchToast(
        <Toast>
          <ToastTitle>Demo data cleaned</ToastTitle>
          <ToastBody>
            {total} rows deleted across {Object.keys(r.deleted).filter(k => r.deleted[k] > 0).length} tables. Chart of accounts + period kept.
          </ToastBody>
        </Toast>,
        { intent: "success" },
      );
      setResetOpen(false);
      // Refresh everything that could now be empty.
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      qc.invalidateQueries({ queryKey: ["entries", clientId] });
      qc.invalidateQueries({ queryKey: ["tb", clientId] });
      qc.invalidateQueries({ queryKey: ["pl", clientId] });
      qc.invalidateQueries({ queryKey: ["bs", clientId] });
      qc.invalidateQueries({ queryKey: ["cf", clientId] });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.listDocuments(),
    // Auto-refresh while any doc is still processing so the user sees
    // OCR transition pending → in_progress → complete without manual refresh.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return false;
      const stillWorking = data.some(
        (d) => d.ocr_status === "pending" || d.ocr_status === "in_progress",
      );
      return stillWorking ? 2000 : false;
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, kindHint, clientId),
    onSuccess: (r) => {
      const autoPosted = r.auto_promoted_count ?? 0;
      let title: string;
      let body: string | null = null;
      if (r.deduped) {
        title = `Uploaded · sha ${shortId(r.sha256)} (already on file)`;
      } else if (autoPosted > 0) {
        title = `Uploaded · auto-posted ${autoPosted} journal entr${autoPosted === 1 ? "y" : "ies"}`;
        body = "High-confidence classification: posted directly to the ledger. View it in Journal entries or Trial balance.";
      } else {
        title = `Uploaded · sha ${shortId(r.sha256)} — draft queued in Review queue`;
        body = "Open Review queue (firm-staff sidebar) to approve, edit, or reject.";
      }
      dispatchToast(
        <Toast>
          <ToastTitle>{title}</ToastTitle>
          {body && <ToastBody>{body}</ToastBody>}
        </Toast>,
        { intent: "success" },
      );
      if (inputRef.current) inputRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["drafts"] });
      if (autoPosted > 0) {
        qc.invalidateQueries({ queryKey: ["entries", clientId] });
        qc.invalidateQueries({ queryKey: ["tb", clientId] });
        qc.invalidateQueries({ queryKey: ["pl", clientId] });
        qc.invalidateQueries({ queryKey: ["bs", clientId] });
        qc.invalidateQueries({ queryKey: ["cf", clientId] });
      }
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const clientDocs = (docs.data ?? []).filter((d) => d.client_id === clientId);

  return (
    <div>
      <Toaster toasterId={toasterId} />
      {needsSetup && (
        <MessageBar intent="warning" style={{ marginBottom: 12 }}>
          <MessageBarBody>
            <MessageBarTitle>This client needs a starter chart of accounts and an open period.</MessageBarTitle>
            <Body1 block>
              Without accounts + a period, uploaded documents can become drafts but cannot be posted to the ledger or trial balance. Seed a sensible default set to unblock the demo — it's idempotent and safe to re-run.
            </Body1>
          </MessageBarBody>
          <MessageBarActions>
            <Button
              appearance="primary"
              icon={seed.isPending ? <Spinner size="tiny" /> : <DatabaseSearchRegular />}
              disabled={seed.isPending}
              onClick={() => seed.mutate()}
            >
              Seed defaults
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}
      <div className={styles.uploader}>
        <Field label="Kind hint" hint="generic / bank_statement / invoice / receipt …">
          <Input value={kindHint} onChange={(_, d) => setKindHint(d.value)} />
        </Field>
        <input
          ref={inputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
          }}
        />
        <Button
          appearance="primary"
          icon={upload.isPending ? <Spinner size="tiny" /> : <ArrowUploadRegular />}
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
        >
          Upload file
        </Button>
        <Dialog open={resetOpen} onOpenChange={(_, d) => setResetOpen(d.open)}>
          <DialogTrigger disableButtonEnhancement>
            <Button
              appearance="subtle"
              icon={<DeleteRegular />}
              disabled={reset.isPending}
            >
              Reset demo data
            </Button>
          </DialogTrigger>
          <DialogSurface>
            <DialogBody>
              <DialogTitle>Reset transactional data for this client?</DialogTitle>
              <DialogContent>
                <Body1 block>
                  This deletes <b>all</b> uploaded documents, drafts, journal
                  entries, tax worksheets, and generated reports for this
                  client so you can run a fresh upload-to-statement flow.
                </Body1>
                <Body1 block style={{ marginTop: 8 }}>
                  Preserved: chart of accounts, accounting periods, the
                  client itself, and the audit trail. This action is only
                  available in non-production environments.
                </Body1>
              </DialogContent>
              <DialogActions>
                <Button
                  appearance="secondary"
                  onClick={() => setResetOpen(false)}
                  disabled={reset.isPending}
                >
                  Cancel
                </Button>
                <Button
                  appearance="primary"
                  icon={reset.isPending ? <Spinner size="tiny" /> : <DeleteRegular />}
                  disabled={reset.isPending}
                  onClick={() => reset.mutate()}
                >
                  Yes, reset
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
        <InfoHint
          title="What happens after I click Upload?"
          body={
            <>
              <ol style={{ margin: "0 0 0 18px", padding: 0 }}>
                <li>
                  The file is virus-scanned, hashed (SHA-256), and stored
                  encrypted in your tenant-private Azure Blob container.
                </li>
                <li>
                  <b>OCR / extraction</b> runs and pulls structured fields
                  (vendor, amount, date, tax-form boxes, etc.) onto the
                  document row. Watch the <b>OCR</b> badge below transition
                  <i> pending → in_progress → complete</i>.
                </li>
                <li>
                  <b>Classification</b> proposes a journal entry and writes
                  a <b>draft</b> row. The draft shows up in the firm-staff{" "}
                  <b>Review queue</b> for a CPA to approve, edit, or reject.
                </li>
                <li>
                  Approving the draft posts a real, balanced journal entry.
                  That entry then flows into the Trial balance, P&amp;L,
                  Balance sheet, Cash flow, and Tax worksheets.
                </li>
              </ol>
              The same file uploaded twice is deduplicated by hash and
              won't create a second draft.
            </>
          }
        />
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Documents are linked to the currently-active client identity.
        </Caption1>
      </div>

      <Section
        title={`${clientDocs.length} documents for this client`}
        subtitle="Click a row to inspect OCR fields, derived drafts, and open the original file. The list auto-refreshes while a document is still processing."
        help={{
          title: "Reading the OCR badge",
          body: (
            <>
              <b>pending</b> — the file has been stored but the extractor
              hasn't started yet.
              <br />
              <b>in_progress</b> — the OCR / Document Intelligence call is
              running.
              <br />
              <b>complete</b> — fields have been extracted and a draft
              journal entry has been created in the <b>Review queue</b>{" "}
              (firm-staff only).
              <br />
              <b>failed</b> — the extractor errored. The file is still
              stored; you can re-upload or open the document to see the
              error message.
            </>
          ),
        }}
      >
        {docs.isLoading && <LoadingState />}
        {docs.error && <ErrorState error={docs.error} />}
        {!docs.isLoading && clientDocs.length === 0 && (
          <EmptyState title="No documents" description="Upload a file to get started." />
        )}
        {clientDocs.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Filename</TableHeaderCell>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>OCR</TableHeaderCell>
                <TableHeaderCell>SHA-256</TableHeaderCell>
                <TableHeaderCell>Received</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {clientDocs.map((d) => (
                <TableRow
                  key={d.id}
                  onClick={() => setOpenDocId(d.id)}
                  style={{ cursor: "pointer" }}
                >
                  <TableCell>{d.filename ?? "(no name)"}</TableCell>
                  <TableCell>{d.kind}</TableCell>
                  <TableCell>
                    <Badge appearance="tint" color={OCR_COLORS[d.ocr_status] ?? "informative"}>
                      {d.ocr_status}
                    </Badge>
                  </TableCell>
                  <TableCell><code>{shortId(d.sha256)}</code></TableCell>
                  <TableCell>{fmtDateTime(d.received_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
      <DocumentDetailDialog
        documentId={openDocId}
        onClose={() => setOpenDocId(null)}
      />
    </div>
  );
}
