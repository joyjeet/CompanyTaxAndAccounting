import {
  Button,
  Badge,
  Body1,
  Caption1,
  makeStyles,
  shorthands,
  Text,
  tokens,
} from "@fluentui/react-components";
import {
  PeopleTeam24Regular,
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
  quickActions: {
    display: "flex",
    flexWrap: "wrap",
    gap: "8px",
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
  const team = useQuery({
    queryKey: ["team", "summary"],
    queryFn: () => api.listTeamMembers(),
  });

  const anyError = clients.error || drafts.error || docs.error || artifacts.error || team.error;
  const anyLoading =
    clients.isLoading || drafts.isLoading || docs.isLoading || artifacts.isLoading || team.isLoading;

  const clientsList = Array.isArray(clients.data) ? clients.data : [];
  const draftsList = Array.isArray(drafts.data) ? drafts.data : [];
  const docsList = Array.isArray(docs.data) ? docs.data : [];
  const artifactsList = Array.isArray(artifacts.data) ? artifacts.data : [];
  const teamMembers = Array.isArray(team.data?.members) ? team.data.members : [];
  const teamInvites = Array.isArray(team.data?.invites) ? team.data.invites : [];

  const teamMembersCount = teamMembers.length;
  const pendingInvitesCount = teamInvites.filter((i) => i.status === "pending").length;
  const disabledMembersCount = teamMembers.filter((m) => m.status === "disabled").length;

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
          value={anyLoading ? "…" : clientsList.length}
        />
        <Kpi
          icon={<ClipboardTaskListLtr24Regular />}
          label="Pending drafts"
          value={anyLoading ? "…" : draftsList.length}
        />
        <Kpi
          icon={<Document24Regular />}
          label="Documents"
          value={anyLoading ? "…" : docsList.length}
        />
        <Kpi
          icon={<DocumentBulletList24Regular />}
          label="Artifacts"
          value={anyLoading ? "…" : artifactsList.length}
        />
        <Kpi
          icon={<PeopleTeam24Regular />}
          label="Team members"
          value={anyLoading ? "…" : teamMembersCount}
        />
      </div>

      <div className={styles.sectionsGrid}>
        <Section
          title="Your clients"
          subtitle="Tenant-scoped via RLS"
          help={{
            title: "What you're seeing",
            body: (
              <>
                Every client your firm has access to in this tenant.
                Click a row to open the client workspace where you can
                manage their chart of accounts, periods, documents,
                journal entries, statements, and tax forms.
                <br /><br />
                Row-level security (RLS) in Postgres guarantees you only
                see clients belonging to your firm — no cross-tenant leak
                is possible even if the API has a bug.
              </>
            ),
          }}
        >
          {clients.isLoading && <LoadingState />}
          {clientsList.length === 0 && !clients.isLoading && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No clients yet.
            </Body1>
          )}
          {clientsList.length > 0 && (
            <div className={styles.list}>
              {clientsList.slice(0, 6).map((c) => (
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

        <Section
          title="Recent documents"
          help={{
            title: "OCR processing",
            body: (
              <>
                The 6 most-recently uploaded documents across all your
                clients. The badge shows OCR status:
                <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
                  <li><b>pending</b> — queued, not started</li>
                  <li><b>in_progress</b> — OCR running</li>
                  <li><b>complete</b> — text extracted, draft created</li>
                  <li><b>failed</b> — extraction failed, see Documents tab for details</li>
                </ul>
              </>
            ),
          }}
        >
          {docs.isLoading && <LoadingState />}
          {docsList.length === 0 && !docs.isLoading && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No uploads yet.
            </Body1>
          )}
          {docsList.length > 0 && (
            <div className={styles.list}>
              {docsList.slice(0, 6).map((d) => (
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

        <Section
          title="Pending drafts"
          subtitle="AI-classified, awaiting your review"
          help={{
            title: "What is a draft?",
            body: (
              <>
                When a document is uploaded, the AI proposes a
                <i> classification</i> (what kind of transaction it is and
                which accounts it should hit). That proposal is held as a
                <i> draft</i> until a CPA promotes it to a real journal
                entry — or rejects it.
                <br /><br />
                The confidence badge is green ≥ 0.80 (safe to promote),
                yellow 0.60–0.80 (review carefully), red &lt; 0.60
                (probably needs hand-editing). Click a row to open the
                draft and approve, edit, or reject.
              </>
            ),
          }}
        >
          {drafts.isLoading && <LoadingState />}
          {draftsList.length === 0 && !drafts.isLoading && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              Inbox zero — nothing waiting.
            </Body1>
          )}
          {draftsList.length > 0 && (
            <div className={styles.list}>
              {draftsList.slice(0, 6).map((d) => {
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

        <Section
          title="Team access"
          subtitle="Membership, invites, and role health"
          help={{
            title: "Why this matters",
            body: (
              <>
                Team access controls who can review drafts, generate final
                artifacts, and manage client records. Keep pending invites and
                disabled accounts tidy to reduce access drift.
              </>
            ),
          }}
        >
          {team.isLoading && <LoadingState />}
          {team.data && (
            <div style={{ display: "grid", gap: 10 }}>
              <div className={styles.list}>
                <div className={styles.listItem}>
                  <Text>Members</Text>
                  <Badge appearance="filled" color="brand">{teamMembersCount}</Badge>
                </div>
                <div className={styles.listItem}>
                  <Text>Pending invites</Text>
                  <Badge appearance="tint" color={pendingInvitesCount > 0 ? "warning" : "success"}>
                    {pendingInvitesCount}
                  </Badge>
                </div>
                <div className={styles.listItem}>
                  <Text>Disabled members</Text>
                  <Badge appearance="tint" color={disabledMembersCount > 0 ? "danger" : "success"}>
                    {disabledMembersCount}
                  </Badge>
                </div>
              </div>
              <div className={styles.quickActions}>
                <Link to="/team" style={{ textDecoration: "none" }}>
                  <Button appearance="primary">Open team access</Button>
                </Link>
                <Link to="/team" style={{ textDecoration: "none" }}>
                  <Button appearance="secondary">Create or accept invite</Button>
                </Link>
              </div>
            </div>
          )}
        </Section>

        <Section
          title="Latest artifacts"
          subtitle="Generated statements, tax worksheets, audit packages"
          help={{
            title: "What is an artifact?",
            body: (
              <>
                An artifact is a generated output (PDF / CSV / JSON) like
                a profit-and-loss statement, balance sheet, cash-flow
                statement, tax worksheet, or audit package.
                <br /><br />
                Artifacts start as <b>draft</b> (you can regenerate them).
                When you <b>finalize</b>, the SHA-256 footer is locked and
                the file becomes the official, immutable copy you can
                share with the client. Only finalized artifacts are
                visible to portal users.
              </>
            ),
          }}
        >
          {artifacts.isLoading && <LoadingState />}
          {artifactsList.length === 0 && !artifacts.isLoading && (
            <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
              No artifacts generated yet.
            </Body1>
          )}
          {artifactsList.length > 0 && (
            <div className={styles.list}>
              {artifactsList.slice(0, 6).map((a) => (
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
