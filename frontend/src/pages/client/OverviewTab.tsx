import { Body1, Caption1, makeStyles, tokens, Text } from "@fluentui/react-components";
import { useQuery } from "@tanstack/react-query";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { ErrorState, LoadingState } from "../../components/States";
import { fmtDate } from "../../lib/format";

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: "16px",
  },
  stat: {
    backgroundColor: tokens.colorNeutralBackground2,
    padding: "16px",
    borderRadius: tokens.borderRadiusMedium,
  },
  statValue: {
    fontSize: tokens.fontSizeHero700,
    fontWeight: tokens.fontWeightSemibold,
  },
});

export default function OverviewTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });
  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });
  const entries = useQuery({
    queryKey: ["entries", clientId],
    queryFn: () => api.listJournalEntries(clientId),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts"],
    queryFn: () => api.listArtifacts(),
  });

  const err = periods.error || accounts.error || entries.error;
  if (err) return <ErrorState error={err} />;
  const loading =
    periods.isLoading || accounts.isLoading || entries.isLoading || artifacts.isLoading;
  if (loading) return <LoadingState />;

  const clientArtifacts = (artifacts.data ?? []).filter((a) => a.client_id === clientId);
  const latestPeriod = periods.data?.[0];

  return (
    <Section
      title="At a glance"
      help={{
        title: "What you're seeing",
        body: (
          <>
            A quick snapshot of this client's bookkeeping state:
            <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
              <li><b>Periods</b> — accounting periods you've defined (e.g. months, quarters, years).</li>
              <li><b>Accounts</b> — entries in the chart of accounts.</li>
              <li><b>Journal entries</b> — posted double-entry transactions.</li>
              <li><b>Artifacts</b> — generated documents (statements, tax forms) for this client.</li>
            </ul>
            Use the tabs above to drill into each area. <b>Latest period</b>
            shows the period that statements default to.
          </>
        ),
      }}
    >
      <div className={styles.grid}>
        <div className={styles.stat}>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Periods</Caption1>
          <div className={styles.statValue}>{periods.data?.length ?? 0}</div>
        </div>
        <div className={styles.stat}>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Accounts</Caption1>
          <div className={styles.statValue}>{accounts.data?.length ?? 0}</div>
        </div>
        <div className={styles.stat}>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Journal entries</Caption1>
          <div className={styles.statValue}>{entries.data?.length ?? 0}</div>
        </div>
        <div className={styles.stat}>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Artifacts</Caption1>
          <div className={styles.statValue}>{clientArtifacts.length}</div>
        </div>
      </div>

      {latestPeriod && (
        <div style={{ marginTop: "20px" }}>
          <Text weight="semibold">Latest period</Text>
          <Body1 block>
            {latestPeriod.name} — {fmtDate(latestPeriod.start_date)} → {fmtDate(latestPeriod.end_date)}{" "}
            {latestPeriod.is_locked && (
              <span style={{ color: tokens.colorPaletteRedForeground1 }}>(locked)</span>
            )}
          </Body1>
        </div>
      )}
    </Section>
  );
}
