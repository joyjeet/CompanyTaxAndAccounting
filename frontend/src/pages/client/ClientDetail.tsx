import {
  Caption1,
  makeStyles,
  Tab,
  TabList,
  tokens,
  Text,
} from "@fluentui/react-components";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

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

type TabId =
  | "overview"
  | "profile"
  | "periods"
  | "accounts"
  | "documents"
  | "journal"
  | "statements"
  | "reports"
  | "tax"
  | "artifacts";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  tabs: { marginBottom: "20px", borderBottom: `1px solid ${tokens.colorNeutralStroke2}` },
});

export default function ClientDetail() {
  const styles = useStyles();
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const [tab, setTab] = useState<TabId>("overview");

  const client = useQuery({
    queryKey: ["client", id],
    queryFn: () => api.getClient(id),
    enabled: !!id,
  });

  if (client.isLoading) return <LoadingState />;
  if (client.error) return <ErrorState error={client.error} />;
  if (!client.data) return null;

  return (
    <div>
      <div className={styles.header}>
        <Text
          size={200}
          style={{ color: tokens.colorNeutralForeground3, cursor: "pointer" }}
          onClick={() => navigate("/clients")}
        >
          ← All clients
        </Text>
        <Text size={700} weight="semibold" block>
          {client.data.name}
        </Text>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Client <code>{shortId(client.data.id)}</code>
          {client.data.external_code && <> · code {client.data.external_code}</>}
        </Caption1>
      </div>

      <TabList
        className={styles.tabs}
        selectedValue={tab}
        onTabSelect={(_, d) => setTab(d.value as TabId)}
      >
        <Tab value="overview">Overview</Tab>
        <Tab value="profile">Profile</Tab>
        <Tab value="periods">Periods</Tab>
        <Tab value="accounts">Chart of accounts</Tab>
        <Tab value="documents">Documents</Tab>
        <Tab value="journal">Journal entries</Tab>
        <Tab value="statements">Statements</Tab>
        <Tab value="reports">Reports</Tab>
        <Tab value="tax">Tax</Tab>
        <Tab value="artifacts">Artifacts</Tab>
      </TabList>

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
