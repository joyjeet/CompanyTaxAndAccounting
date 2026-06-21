import {
  Button,
  Caption1,
  makeStyles,
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
import { ArrowDownloadRegular } from "@fluentui/react-icons";
import { useMutation, useQuery } from "@tanstack/react-query";

import { useApi } from "../api/useApi";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  num: { textAlign: "right", fontFamily: tokens.fontFamilyMonospace },
});

export default function PortalReports() {
  const styles = useStyles();
  const api = useApi();
  const toasterId = useId("portal-reports-toaster");
  const { dispatchToast } = useToastController(toasterId);

  // Portal users can only see FINALIZED artifacts. The backend already
  // filters but we belt-and-suspenders here.
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: () => api.listArtifacts() });

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

  const finalized = (artifacts.data ?? []).filter((a) => a.status === "finalized");

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.header}>
        <Text size={700} weight="semibold">My reports</Text>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Final financial statements, tax worksheets, and other reports prepared by your firm.
        </Caption1>
      </div>

      <Section title={`${finalized.length} finalized reports`}>
        {artifacts.isLoading && <LoadingState />}
        {artifacts.error && <ErrorState error={artifacts.error} />}
        {!artifacts.isLoading && finalized.length === 0 && (
          <EmptyState
            title="No reports yet"
            description="Your firm will publish reports here once they're finalized."
          />
        )}
        {finalized.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Title</TableHeaderCell>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell className={styles.num}>Size</TableHeaderCell>
                <TableHeaderCell>SHA-256</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {finalized.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>{a.title}</TableCell>
                  <TableCell>{a.kind}</TableCell>
                  <TableCell><code>{a.format}</code></TableCell>
                  <TableCell className={styles.num}>{(a.size_bytes / 1024).toFixed(1)} KB</TableCell>
                  <TableCell><code>{shortId(a.plaintext_sha256)}</code></TableCell>
                  <TableCell>
                    <Button
                      appearance="primary"
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
