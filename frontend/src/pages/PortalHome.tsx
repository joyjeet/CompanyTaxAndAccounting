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
        <Text size={700} weight="semibold">
          Welcome{identity ? `, ${identity.sub}` : ""}
        </Text>
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

      <Section title="Recent activity">
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
                    d.ocr_status === "succeeded"
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
