/**
 * One client, ten surfaces.
 *
 * Two things shape this page:
 *
 *  * The active tab lives in the URL (`/clients/:id/:tab`), not in component
 *    state. Previously a refresh dropped you back on Overview, Back walked
 *    out of the client entirely, and no client view could be linked to.
 *  * The tabs are grouped by when you need them — Setup before Work before
 *    Output — because a flat strip of ten gave no hint that periods and a
 *    chart of accounts must exist before a document can be posted.
 */
import {
  Caption1,
  Divider,
  Tab,
  TabList,
  Text,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../../api/useApi";
import { ErrorState, LoadingState } from "../../components/States";
import { shortId } from "../../lib/format";
import AccountsTab from "./AccountsTab";
import ArtifactsTab from "./ArtifactsTab";
import DocumentsTab from "./DocumentsTab";
import JournalEntriesTab from "./JournalEntriesTab";
import OverviewTab from "./OverviewTab";
import PeriodsTab from "./PeriodsTab";
import ProfileTab from "./ProfileTab";
import ReportsTab from "./ReportsTab";
import StatementsTab from "./StatementsTab";
import TaxTab from "./TaxTab";

interface TabDef {
  id: string;
  label: string;
}

const TAB_GROUPS: Array<{ label: string; hint: string; tabs: TabDef[] }> = [
  {
    label: "Set up",
    hint: "Do these first — everything else depends on them",
    tabs: [
      { id: "profile", label: "Profile" },
      { id: "periods", label: "Periods" },
      { id: "accounts", label: "Chart of accounts" },
    ],
  },
  {
    label: "Day-to-day",
    hint: "Where the bookkeeping actually happens",
    tabs: [
      { id: "documents", label: "Documents" },
      { id: "journal", label: "Journal entries" },
    ],
  },
  {
    label: "Results",
    hint: "What comes out the other end",
    tabs: [
      { id: "statements", label: "Statements" },
      { id: "reports", label: "Reports" },
      { id: "tax", label: "Tax" },
      { id: "artifacts", label: "Artifacts" },
    ],
  },
];

const ALL_TABS: string[] = [
  "overview",
  ...TAB_GROUPS.flatMap((g) => g.tabs.map((t) => t.id)),
];
type TabId = string;

const TAB_IDS: TabId[] = [
  "overview",
  "profile",
  "periods",
  "accounts",
  "documents",
  "journal",
  "statements",
  "reports",
  "tax",
  "artifacts",
];

function isTabId(value: string | null): value is TabId {
  return !!value && TAB_IDS.includes(value as TabId);
}

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  crumbs: {
    display: "flex",
    alignItems: "center",
    columnGap: "6px",
    marginBottom: "2px",
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
  crumbLink: {
    cursor: "pointer",
    color: tokens.colorBrandForeground1,
    ":hover": { textDecoration: "underline" },
  },
  nav: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    columnGap: "4px",
    rowGap: "4px",
    marginBottom: "20px",
    paddingBottom: "4px",
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
  },
  groupLabel: {
    ...shorthands.padding("0", "10px", "0", "4px"),
    color: tokens.colorNeutralForeground3,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
    whiteSpace: "nowrap",
  },
  sep: { height: "22px", alignSelf: "center" },
});

export default function ClientDetail() {
  const styles = useStyles();
  const { id = "", tab: tabParam } = useParams<{ id: string; tab?: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const api = useApi();
  const qTab = searchParams.get("tab");
  const pathTab: TabId | null =
    tabParam && ALL_TABS.includes(tabParam) ? (tabParam as TabId) : null;
  const tab: TabId = isTabId(qTab) ? qTab : pathTab ?? "overview";

  const selectTab = (next: string) => {
    setSearchParams((prev) => {
      const nextParams = new URLSearchParams(prev);
      nextParams.set("tab", next);
      return nextParams;
    });
    navigate(next === "overview" ? `/clients/${id}` : `/clients/${id}/${next}`);
  };

  const client = useQuery({
    queryKey: ["client", id],
    queryFn: () => api.getClient(id),
    enabled: !!id,
  });

  if (client.isLoading) return <LoadingState />;
  if (client.error) return <ErrorState error={client.error} />;
  if (!client.data) return null;

  const activeLabel =
    tab === "overview"
      ? "Overview"
      : TAB_GROUPS.flatMap((g) => g.tabs).find((t) => t.id === tab)?.label ?? "";

  return (
    <div>
      <div className={styles.header}>
        <div className={styles.crumbs}>
          <span className={styles.crumbLink} onClick={() => navigate("/clients")}>
            Clients
          </span>
          <span>/</span>
          <span
            className={styles.crumbLink}
            onClick={() => navigate(`/clients/${id}`)}
          >
            {client.data.name}
          </span>
          {tab !== "overview" && (
            <>
              <span>/</span>
              <span>{activeLabel}</span>
            </>
          )}
        </div>
        <Text size={700} weight="semibold" block>
          {client.data.name}
        </Text>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Client <code>{shortId(client.data.id)}</code>
          {client.data.external_code && <> · code {client.data.external_code}</>}
        </Caption1>
      </div>

      <div className={styles.nav}>
        <TabList selectedValue={tab} onTabSelect={(_, d) => selectTab(String(d.value))}>
          <Tab value="overview">Overview</Tab>
        </TabList>
        {TAB_GROUPS.map((g) => (
          <div key={g.label} style={{ display: "flex", alignItems: "center" }}>
            <Divider vertical className={styles.sep} />
            <span className={styles.groupLabel} title={g.hint}>
              {g.label}
            </span>
            <TabList
              selectedValue={tab}
              onTabSelect={(_, d) => selectTab(String(d.value))}
            >
              {g.tabs.map((t) => (
                <Tab key={t.id} value={t.id}>
                  {t.label}
                </Tab>
              ))}
            </TabList>
          </div>
        ))}
      </div>

      {tab === "overview" && <OverviewTab clientId={id} />}
      {tab === "profile" && (
        <ProfileTab clientId={id} clientName={client.data.name} />
      )}
      {tab === "periods" && <PeriodsTab clientId={id} />}
      {tab === "accounts" && <AccountsTab clientId={id} />}
      {tab === "documents" && <DocumentsTab clientId={id} />}
      {tab === "journal" && <JournalEntriesTab clientId={id} />}
      {tab === "statements" && <StatementsTab clientId={id} />}
      {tab === "reports" && <ReportsTab clientId={id} />}
      {tab === "tax" && <TaxTab clientId={id} />}
      {tab === "artifacts" && <ArtifactsTab clientId={id} />}
    </div>
  );
}
