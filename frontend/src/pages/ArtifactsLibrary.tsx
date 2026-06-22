import {
  Badge,
  Button,
  Caption1,
  Dropdown,
  makeStyles,
  Option,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { ArrowDownloadRegular, LockClosedRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/useApi";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  num: { textAlign: "right", fontFamily: tokens.fontFamilyMonospace },
  toolbar: { display: "flex", gap: "12px" },
});

const KINDS = [
  "profit_and_loss",
  "balance_sheet",
  "cash_flow",
  "tax_worksheet",
  "audit_package",
  "narrative",
];

export default function ArtifactsLibrary() {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("art-lib-toaster");
  const { dispatchToast } = useToastController(toasterId);
  const [kindFilter, setKindFilter] = useState<string>("");

  const artifacts = useQuery({
    queryKey: ["artifacts", kindFilter || "all"],
    queryFn: () => api.listArtifacts(kindFilter ? { kind: kindFilter } : undefined),
  });

  const finalize = useMutation({
    mutationFn: (id: string) => api.finalizeArtifact(id),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Finalized</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const download = useMutation({
    mutationFn: async (id: string) => {
      const { blob, filename } = await api.downloadArtifact(id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Text size={700} weight="semibold">Artifacts</Text>
          <InfoHint
            title="What is an artifact?"
            body={
              <>
                An artifact is a generated document — PDF, CSV, or JSON —
                produced from posted journal entries. Examples:
                profit-and-loss, balance sheet, cash-flow, tax worksheet,
                audit package, narrative report.
                <br /><br />
                Artifacts have two states:
                <ul style={{ marginTop: 6, marginBottom: 6, paddingLeft: 18 }}>
                  <li><b>draft</b> — you can regenerate it (e.g. after
                    posting more entries). Not visible to portal users.</li>
                  <li><b>finalized</b> — SHA-256 footer is locked; file is
                    immutable; portal users can download it.</li>
                </ul>
                Click <b>Finalize</b> to lock; <b>Download</b> to get a
                copy. To <i>generate</i> a new artifact, go to a client's
                Statements or Tax tab.
              </>
            }
          />
        </div>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Encrypted generated outputs across all clients in the firm.
        </Caption1>
      </div>

      <Section
        title="Generated artifacts"
        toolbar={
          <div className={styles.toolbar}>
            <Dropdown
              value={kindFilter || "All kinds"}
              selectedOptions={kindFilter ? [kindFilter] : []}
              onOptionSelect={(_, d) => setKindFilter(d.optionValue ?? "")}
            >
              <Option value="">All kinds</Option>
              {KINDS.map((k) => (
                <Option key={k} value={k}>{k}</Option>
              ))}
            </Dropdown>
          </div>
        }
      >
        {artifacts.isLoading && <LoadingState />}
        {artifacts.error && <ErrorState error={artifacts.error} />}
        {artifacts.data && artifacts.data.length === 0 && (
          <EmptyState title="No artifacts match" description="Generate from a client's Statements or Tax tab." />
        )}
        {artifacts.data && artifacts.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Title</TableHeaderCell>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Client</TableHeaderCell>
                <TableHeaderCell className={styles.num}>Size</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {artifacts.data.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>{a.title}</TableCell>
                  <TableCell>{a.kind}</TableCell>
                  <TableCell><code>{a.format}</code></TableCell>
                  <TableCell>
                    <Badge
                      appearance="tint"
                      color={a.status === "finalized" ? "success" : "informative"}
                    >
                      {a.status}
                    </Badge>
                  </TableCell>
                  <TableCell><code>{shortId(a.client_id)}</code></TableCell>
                  <TableCell className={styles.num}>{(a.size_bytes / 1024).toFixed(1)} KB</TableCell>
                  <TableCell>
                    {a.status !== "finalized" && (
                      <Button
                        appearance="subtle"
                        size="small"
                        icon={<LockClosedRegular />}
                        onClick={() => finalize.mutate(a.id)}
                      >
                        Finalize
                      </Button>
                    )}
                    <Button
                      appearance="subtle"
                      size="small"
                      icon={<ArrowDownloadRegular />}
                      onClick={() => download.mutate(a.id)}
                    >
                      Download
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
