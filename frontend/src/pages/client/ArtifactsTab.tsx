import {
  Badge,
  Button,
  makeStyles,
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
import { ArrowDownloadRegular, LockClosedRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtDateTime, shortId } from "../../lib/format";

const useStyles = makeStyles({
  num: { textAlign: "right", fontFamily: tokens.fontFamilyMonospace },
});

export default function ArtifactsTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("artifacts-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const artifacts = useQuery({
    queryKey: ["artifacts"],
    queryFn: () => api.listArtifacts(),
  });

  const finalize = useMutation({
    mutationFn: (id: string) => api.finalizeArtifact(id),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Artifact finalized</ToastTitle></Toast>, { intent: "success" });
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

  const rows = (artifacts.data ?? []).filter((a) => a.client_id === clientId);

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <Section
        title="Artifacts library"
        subtitle="Encrypted at rest. Finalize to lock the SHA-256 footer; download to share."
        help={{
          title: "What is an artifact?",
          body: (
            <>
              An artifact is a generated document for this client —
              statements (P&amp;L, BS, CF), tax worksheets, audit
              packages, narrative reports. Generate them from the
              <b> Statements</b> and <b>Tax</b> tabs.
              <br /><br />
              <b>draft</b> = regeneratable, internal only. <b>finalized</b>
              = SHA-256 locked, immutable, downloadable by the client in
              their portal. Click <b>Finalize</b> when the artifact is
              ready to ship; click <b>Download</b> to fetch a decrypted
              copy.
            </>
          ),
        }}
      >
        {artifacts.isLoading && <LoadingState />}
        {artifacts.error && <ErrorState error={artifacts.error} />}
        {!artifacts.isLoading && rows.length === 0 && (
          <EmptyState title="No artifacts" description="Generate from Statements or Tax." />
        )}
        {rows.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Title</TableHeaderCell>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Created At</TableHeaderCell>
                <TableHeaderCell>Finalized At</TableHeaderCell>
                <TableHeaderCell className={styles.num}>Size</TableHeaderCell>
                <TableHeaderCell>SHA-256</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>{a.title}</TableCell>
                  <TableCell>{a.kind}</TableCell>
                  <TableCell><code>{a.format}</code></TableCell>
                  <TableCell>
                    <Badge appearance="tint" color={a.status === "finalized" ? "success" : "informative"}>
                      {a.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{fmtDateTime(a.generated_at)}</TableCell>
                  <TableCell>{fmtDateTime(a.finalized_at)}</TableCell>
                  <TableCell className={styles.num}>{(a.size_bytes / 1024).toFixed(1)} KB</TableCell>
                  <TableCell><code>{shortId(a.plaintext_sha256)}</code></TableCell>
                  <TableCell>
                    {a.status !== "finalized" && (
                      <Button
                        appearance="subtle"
                        size="small"
                        icon={<LockClosedRegular />}
                        onClick={() => finalize.mutate(a.id)}
                        disabled={finalize.isPending}
                      >
                        Finalize
                      </Button>
                    )}
                    <Button
                      appearance="subtle"
                      size="small"
                      icon={<ArrowDownloadRegular />}
                      onClick={() => download.mutate(a.id)}
                      disabled={download.isPending}
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
