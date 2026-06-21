import {
  Badge,
  Caption1,
  Field,
  Input,
  makeStyles,
  shorthands,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toast,
  Toaster,
  ToastBody,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { ArrowUploadRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../api/useApi";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { fmtDateTime, shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  dropZone: {
    ...shorthands.border("2px", "dashed", tokens.colorNeutralStroke2),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.padding("32px"),
    textAlign: "center",
    backgroundColor: tokens.colorNeutralBackground2,
    transition: "background-color 100ms ease",
    cursor: "pointer",
  },
  dragOver: {
    backgroundColor: tokens.colorBrandBackground2,
    ...shorthands.border("2px", "dashed", tokens.colorBrandStroke1),
  },
  uploadGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "16px",
    marginBottom: "16px",
  },
});

const OCR_COLORS: Record<string, "success" | "warning" | "danger" | "informative"> = {
  succeeded: "success",
  failed: "danger",
  running: "warning",
  pending: "informative",
};

export default function PortalDocuments() {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("portal-docs-toaster");
  const { dispatchToast } = useToastController(toasterId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [kindHint, setKindHint] = useState("generic");
  const [dragOver, setDragOver] = useState(false);

  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.listDocuments() });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, kindHint),
    onSuccess: (r) => {
      dispatchToast(
        <Toast>
          <ToastTitle>{r.deduped ? "Duplicate detected" : "Upload received"}</ToastTitle>
          <ToastBody>SHA-256 {shortId(r.sha256)}</ToastBody>
        </Toast>,
        { intent: "success" },
      );
      if (inputRef.current) inputRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.header}>
        <Text size={700} weight="semibold">My documents</Text>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Drop files below to send them to your accounting team for processing.
        </Caption1>
      </div>

      <div className={styles.uploadGrid}>
        <Field label="Kind hint" hint="generic / bank_statement / invoice / receipt …">
          <Input value={kindHint} onChange={(_, d) => setKindHint(d.value)} />
        </Field>
        <div />
      </div>

      <div
        className={`${styles.dropZone} ${dragOver ? styles.dragOver : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) upload.mutate(file);
        }}
        onClick={() => inputRef.current?.click()}
      >
        {upload.isPending ? (
          <Spinner label="Uploading…" />
        ) : (
          <>
            <ArrowUploadRegular fontSize={32} />
            <Text size={400} weight="semibold" block style={{ marginTop: 8 }}>
              Drag &amp; drop a file or click to browse
            </Text>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
              PDFs, images, CSVs, scanned receipts. One at a time.
            </Caption1>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
          }}
        />
      </div>

      <div style={{ marginTop: 24 }}>
        <Section title={`${docs.data?.length ?? 0} uploaded documents`}>
          {docs.isLoading && <LoadingState />}
          {docs.error && <ErrorState error={docs.error} />}
          {docs.data && docs.data.length === 0 && <EmptyState title="No uploads yet" />}
          {docs.data && docs.data.length > 0 && (
            <Table size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>Filename</TableHeaderCell>
                  <TableHeaderCell>Kind</TableHeaderCell>
                  <TableHeaderCell>OCR</TableHeaderCell>
                  <TableHeaderCell>Received</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.data.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>{d.filename ?? "(no name)"}</TableCell>
                    <TableCell>{d.kind}</TableCell>
                    <TableCell>
                      <Badge appearance="tint" color={OCR_COLORS[d.ocr_status] ?? "informative"}>
                        {d.ocr_status}
                      </Badge>
                    </TableCell>
                    <TableCell>{fmtDateTime(d.received_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
      </div>
    </div>
  );
}
