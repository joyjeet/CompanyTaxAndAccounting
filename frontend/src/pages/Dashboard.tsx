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
  BookContacts24Regular,
  ClipboardTaskListLtr24Regular,
  Document24Regular,
  DocumentBulletList24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";
import { fmtDateTime, shortId } from "../lib/format";

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: "16px",
    marginBottom: "24px",
  },
  kpi: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("20px"),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    boxShadow: tokens.shadow2,
    display: "flex",
    alignItems: "center",
    columnGap: "16px",
  },
  kpiIcon: {
    width: "44px",
    height: "44px",
    display: "grid",
    placeItems: "center",
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
  },
  kpiValue: {
    fontSize: tokens.fontSizeHero700,
    fontWeight: tokens.fontWeightSemibold,
    lineHeight: tokens.lineHeightHero700,
  },
  list: {
    display: "flex",
    flexDirection: "column",
    rowGap: "8px",
  },
  listItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    ...shorthands.padding("10px", "12px"),
    backgroundColor: tokens.colorNeutralBackground2,
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
  },
  sectionsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
    gap: "16px",
  },
});

function Kpi({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
}) {
  const styles = useStyles();
  return (
    <div className={styles.kpi}>
      <div className={styles.kpiIcon}>{icon}</div>
      <div>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>{label}</Caption1>
        <div className={styles.kpiValue}>{value}</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const styles = useStyles();
  const api = useApi();
  const { identity } = useAuth();

  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients() });
  const drafts = useQuery({
    queryKey: ["drafts", "pending"],
    queryFn: () => api.listDrafts(true),
  });
  const docs = useQuery({ queryKey: ["documents"], queryFn: () => api.listDocuments() });
  const artifacts = useQuery({
    queryKey: ["artifacts"],
    queryFn: () => api.listArtifacts(),
  });

  const anyError = clients.error || drafts.error || docs.error || artifacts.error;
  const anyLoading =
    clients.isLoading || drafts.isLoading || docs.isLoading || artifacts.isLoading;

  return (
    <div>
      <div style={{ marginBottom: "16px" }}>
        <Text size={700} weight="semibold">
          Welcome back{identity ? `, ${identity.sub}` : ""}
        </Text>
        <Body1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Firm overview across all clients in your tenant.
        </Body1>
      </div>

      {anyError && <ErrorState error={anyError} />}

      <div className={styles.grid}>
        <Kpi
          icon={<BookContacts24Regular />}
          label="Clients"
          value={anyLoading ? "…" : clients.data?.length ?? 0}
        />
        <Kpi
          icon={<ClipboardTaskListLtr24Regular />}
          label="Pending drafts"
          value={anyLoading ? "…" : drafts.data?.length ?? 0}
        />
        <Kpi
          icon={<Document24Regular />}
          label="Documents"
          value={anyLoading ? "…" : docs.data?.length ?? 0}
        />
        <Kpi
          icon={<DocumentBulletList24Regular />}
          label="Artifacts"
          value={anyLoading ? "…" : artifacts.data?.length ?? 0}
        />
      </div>

      <div className={styles.sectionsGrid}>
        <Section title="Your clients" subtitle="Tenant-scoped via RLS">
          {clients.isLoading && <LoadingState />}
          {clients.data && clients.data.length === 0 && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No clients yet.
            </Body1>
          )}
          {clients.data && clients.data.length > 0 && (
            <div className={styles.list}>
              {clients.data.slice(0, 6).map((c) => (
                <Link
                  to={`/clients/${c.id}`}
                  key={c.id}
                  className={styles.listItem}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div>
                    <Text weight="semibold">{c.name}</Text>
                    <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                      {c.external_code ?? "—"} · <code>{shortId(c.id)}</code>
                    </Caption1>
                  </div>
                  <Badge appearance="tint">open →</Badge>
                </Link>
              ))}
            </div>
          )}
        </Section>

        <Section title="Recent documents">
          {docs.isLoading && <LoadingState />}
          {docs.data && docs.data.length === 0 && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No uploads yet.
            </Body1>
          )}
          {docs.data && docs.data.length > 0 && (
            <div className={styles.list}>
              {docs.data.slice(0, 6).map((d) => (
                <div className={styles.listItem} key={d.id}>
                  <div>
                    <Text weight="semibold">{d.filename ?? "(no filename)"}</Text>
                    <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                      {d.kind} · {fmtDateTime(d.received_at)}
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

        <Section title="Pending drafts" subtitle="AI-classified, awaiting your review">
          {drafts.isLoading && <LoadingState />}
          {drafts.data && drafts.data.length === 0 && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              Inbox zero — nothing waiting.
            </Body1>
          )}
          {drafts.data && drafts.data.length > 0 && (
            <div className={styles.list}>
              {drafts.data.slice(0, 6).map((d) => {
                const conf = Number.parseFloat(d.confidence);
                return (
                  <Link
                    key={d.id}
                    to={`/drafts/${d.id}`}
                    className={styles.listItem}
                    style={{ textDecoration: "none", color: "inherit" }}
                  >
                    <div>
                      <Text weight="semibold">{d.kind}</Text>
                      <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                        <code>{shortId(d.source_document_id)}</code> · {d.model}
                      </Caption1>
                    </div>
                    <Badge
                      appearance="filled"
                      color={
                        d.high_confidence
                          ? "success"
                          : conf < 0.6
                            ? "danger"
                            : "warning"
                      }
                    >
                      {(conf * 100).toFixed(0)}%
                    </Badge>
                  </Link>
                );
              })}
            </div>
          )}
        </Section>

        <Section title="Latest artifacts" subtitle="Generated statements, tax worksheets, audit packages">
          {artifacts.isLoading && <LoadingState />}
          {artifacts.data && artifacts.data.length === 0 && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No artifacts generated yet.
            </Body1>
          )}
          {artifacts.data && artifacts.data.length > 0 && (
            <div className={styles.list}>
              {artifacts.data.slice(0, 6).map((a) => (
                <div key={a.id} className={styles.listItem}>
                  <div>
                    <Text weight="semibold">{a.title}</Text>
                    <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                      {a.kind} · {a.format.toUpperCase()} · <code>{shortId(a.id)}</code>
                    </Caption1>
                  </div>
                  <Badge
                    appearance="tint"
                    color={a.status === "finalized" ? "success" : "informative"}
                  >
                    {a.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
