import {
  Badge,
  Button,
  Caption1,
  Field,
  Input,
  makeStyles,
  Spinner,
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
import { ArrowUploadRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDateTime, shortId } from "../../lib/format";

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

const OCR_COLORS: Record<string, "success" | "warning" | "danger" | "informative"> = {
  succeeded: "success",
  failed: "danger",
  running: "warning",
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

  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.listDocuments(),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, kindHint),
    onSuccess: (r) => {
      dispatchToast(
        <Toast><ToastTitle>Uploaded · sha {shortId(r.sha256)}{r.deduped ? " (dedup)" : ""}</ToastTitle></Toast>,
        { intent: "success" },
      );
      if (inputRef.current) inputRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const clientDocs = (docs.data ?? []).filter((d) => d.client_id === clientId);

  return (
    <div>
      <Toaster toasterId={toasterId} />
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
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Documents are linked to the currently-active client identity.
        </Caption1>
      </div>

      <Section
        title={`${clientDocs.length} documents for this client`}
        subtitle="OCR runs asynchronously. Refresh to see status changes."
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
                <TableRow key={d.id}>
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
    </div>
  );
}
