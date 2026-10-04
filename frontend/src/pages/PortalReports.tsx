import {
  Badge,
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
  Tooltip,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { ArrowDownloadRegular } from "@fluentui/react-icons";
import { useMutation, useQuery } from "@tanstack/react-query";

import { useApi } from "../api/useApi";
import { useEffectiveIdentity } from "../auth/TenantContext";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { fmtDateTime, shortId } from "../lib/format";
import ReportsTab from "./client/ReportsTab";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  num: { textAlign: "right", fontFamily: tokens.fontFamilyMonospace },
});

const STATUS_COLOR: Record<string, "success" | "warning" | "informative"> = {
  finalized: "success",
  draft: "warning",
};

export default function PortalReports() {
  const styles = useStyles();
  const api = useApi();
  const identity = useEffectiveIdentity();
  const toasterId = useId("portal-reports-toaster");
  const { dispatchToast } = useToastController(toasterId);

  // Portal users now see both DRAFT (pending) and FINALIZED reports so they
  // know their firm is preparing work — but only finalized reports are
  // downloadable. The backend enforces this; we mirror the rule in the UI.
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

  const visible = artifacts.data ?? [];
  const pending = visible.filter((a) => a.status === "draft");
  const finalized = visible.filter((a) => a.status === "finalized");

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Text size={700} weight="semibold">My reports</Text>
          <InfoHint
            title="What is a report?"
            body={
              <>
                Reports are the financial documents your firm is preparing
                for you — financial statements, tax worksheets, and audit
                packages.
                <br /><br />
                <b>Pending</b> reports are in progress: your CPA has
                generated a draft and is still reviewing the numbers. You
                can see that work is happening but can't download yet.
                <br /><br />
                <b>Approved</b> reports have been finalized and signed off.
                The file is locked: its SHA-256 footer proves it hasn't
                been changed. Click <b>Download</b> to get a copy.
              </>
            }
          />
        </div>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Pending and approved reports prepared by your firm.
        </Caption1>
      </div>

      <Section
        title={`${pending.length} pending · ${finalized.length} approved`}
        subtitle="Pending reports are draft work your CPA has generated. They become downloadable once approved (finalized)."
      >
        {artifacts.isLoading && <LoadingState />}
        {artifacts.error && <ErrorState error={artifacts.error} />}
        {!artifacts.isLoading && visible.length === 0 && (
          <EmptyState
            title="No reports yet"
            description="Your firm will publish reports here as they prepare them."
          />
        )}
        {visible.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Title</TableHeaderCell>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell>Created At</TableHeaderCell>
                <TableHeaderCell>Approved At</TableHeaderCell>
                <TableHeaderCell className={styles.num}>Size</TableHeaderCell>
                <TableHeaderCell>SHA-256</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((a) => {
                const isFinal = a.status === "finalized";
                return (
                  <TableRow key={a.id}>
                    <TableCell>{a.title}</TableCell>
                    <TableCell>{a.kind}</TableCell>
                    <TableCell>
                      <Badge
                        appearance="tint"
                        color={STATUS_COLOR[a.status] ?? "informative"}
                      >
                        {isFinal ? "approved" : "pending review"}
                      </Badge>
                    </TableCell>
                    <TableCell><code>{a.format}</code></TableCell>
                    <TableCell>{fmtDateTime(a.generated_at)}</TableCell>
                    <TableCell>{fmtDateTime(a.finalized_at)}</TableCell>
                    <TableCell className={styles.num}>{(a.size_bytes / 1024).toFixed(1)} KB</TableCell>
                    <TableCell><code>{shortId(a.plaintext_sha256)}</code></TableCell>
                    <TableCell>
                      {isFinal ? (
                        <Button
                          appearance="primary"
                          size="small"
                          icon={<ArrowDownloadRegular />}
                          onClick={() => download.mutate(a.id)}
                        >
                          Download
                        </Button>
                      ) : (
                        <Tooltip
                          content="This report is still being prepared by your CPA. It will be downloadable once approved."
                          relationship="label"
                        >
                          <Button
                            appearance="secondary"
                            size="small"
                            icon={<ArrowDownloadRegular />}
                            disabled
                          >
                            Pending
                          </Button>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>

      {identity?.clientId && (
        <div style={{ marginTop: 24 }}>
          <Section
            title="Live reports"
            subtitle="Computed live from posted ledger entries. Only periods your firm has finalized (locked) appear here."
          >
            <ReportsTab clientId={identity.clientId} portalView />
          </Section>
        </div>
      )}
    </div>
  );
}
