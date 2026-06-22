import {
  Badge,
  Body1,
  Caption1,
  makeStyles,
  shorthands,
  Text,
  tokens,
} from "@fluentui/react-components";
import {
  ChartMultipleRegular,
  Document24Regular,
  DocumentBulletList24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";
import { fmtDateTime, shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "24px" },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
    gap: "16px",
    marginBottom: "24px",
  },
  kpi: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("20px"),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    display: "flex",
    alignItems: "center",
    columnGap: "16px",
    textDecoration: "none",
    color: "inherit",
  },
  kpiIcon: {
    width: "48px",
    height: "48px",
    display: "grid",
    placeItems: "center",
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
  },
});

export default function PortalHome() {
  const styles = useStyles();
  const api = useApi();
  const { identity } = useAuth();

  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.listDocuments() });
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: () => api.listArtifacts() });

  const finalized = (artifacts.data ?? []).filter((a) => a.status === "finalized");

  return (
    <div>
      <div className={styles.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Text size={700} weight="semibold">
            Welcome{identity ? `, ${identity.sub}` : ""}
          </Text>
          <InfoHint
            title="What you can do here"
            body={
              <>
                This is your client portal. From here you can:
                <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
                  <li><b>Upload documents</b> (invoices, receipts, bank statements) for your firm to process.</li>
                  <li><b>Download finalized reports</b> — financial statements, tax worksheets — once your firm publishes them.</li>
                  <li>Track which documents have been received and processed.</li>
                </ul>
                Use the cards below as shortcuts.
              </>
            }
          />
        </div>
        <Body1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Upload bookkeeping documents and review the financial statements your firm produces for you.
        </Body1>
      </div>

      <div className={styles.grid}>
        <Link to="/portal/documents" className={styles.kpi}>
          <div className={styles.kpiIcon}><Document24Regular /></div>
          <div>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Documents</Caption1>
            <Text size={600} weight="semibold" block>{docs.data?.length ?? 0}</Text>
          </div>
        </Link>
        <Link to="/portal/reports" className={styles.kpi}>
          <div className={styles.kpiIcon}><DocumentBulletList24Regular /></div>
          <div>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Finalized reports</Caption1>
            <Text size={600} weight="semibold" block>{finalized.length}</Text>
          </div>
        </Link>
        <Link to="/portal/documents" className={styles.kpi}>
          <div className={styles.kpiIcon}><ChartMultipleRegular /></div>
          <div>
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Upload new</Caption1>
            <Text size={400} weight="semibold" block>Send to your accountant</Text>
          </div>
        </Link>
      </div>

      <Section
        title="Recent activity"
        help={{
          title: "What you're seeing",
          body: (
            <>
              The latest documents you've sent to your accounting firm.
              The OCR badge tells you where each one is in their workflow:
              <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
                <li><b>pending</b> — received, queued for processing</li>
                <li><b>in_progress</b> — your firm's system is reading it</li>
                <li><b>complete</b> — read successfully, now awaiting CPA review</li>
                <li><b>failed</b> — we couldn't extract text; your firm will reach out</li>
              </ul>
            </>
          ),
        }}
      >
        {docs.isLoading && <LoadingState />}
        {docs.error && <ErrorState error={docs.error} />}
        {docs.data && docs.data.length === 0 && (
          <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
            No documents yet. <Link to="/portal/documents">Upload your first.</Link>
          </Body1>
        )}
        {docs.data && docs.data.length > 0 && (
          <div style={{ display: "grid", rowGap: 8 }}>
            {docs.data.slice(0, 8).map((d) => (
              <div
                key={d.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "10px 12px",
                  backgroundColor: tokens.colorNeutralBackground2,
                  borderRadius: tokens.borderRadiusMedium,
                }}
              >
                <div>
                  <Text weight="semibold">{d.filename ?? "(no filename)"}</Text>
                  <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                    {d.kind} · {fmtDateTime(d.received_at)} · <code>{shortId(d.sha256)}</code>
                  </Caption1>
                </div>
                <Badge
                  appearance="tint"
                  color={
                    d.ocr_status === "complete"
                      ? "success"
                      : d.ocr_status === "failed"
                        ? "danger"
                        : "warning"
                  }
                >
                  {d.ocr_status}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
