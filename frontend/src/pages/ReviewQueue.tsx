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
  tokens,
} from "@fluentui/react-components";
import { OpenRegular } from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { roleDisplayName } from "../auth/firmRole";
import { useClientScope } from "../auth/useClientScope";
import { useFirmRole } from "../auth/useFirmRole";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  headerRow: { display: "flex", alignItems: "center", gap: "6px" },
});

export default function ReviewQueue() {
  const styles = useStyles();
  const api = useApi();
  const { capabilities, role, isLoading: roleLoading } = useFirmRole();
  const { clientId, clientName } = useClientScope();
  const drafts = useQuery({
    queryKey: ["drafts", "pending", clientId ?? "all"],
    queryFn: () => api.listDrafts(true, clientId ?? undefined),
  });

  return (
    <div>
      <div className={styles.header}>
        <div className={styles.headerRow}>
          <Text size={700} weight="semibold">Review queue</Text>
          <InfoHint
            title="What this queue is for"
            body={
              <>
                Every uploaded document is processed by the OCR + classifier
                pipeline, which produces a <b>draft journal entry</b>. This
                queue is where firm staff <b>approve, edit, or reject</b>{" "}
                those drafts before they become real, posted journal
                entries that flow into the trial balance and financial
                statements.
                <br /><br />
                The <b>Confidence</b> badge is the classifier's
                self-reported certainty. Green = high confidence (safe to
                approve as-is). Yellow = review the proposed account
                mapping carefully. Red = the classifier is unsure; you
                likely need to edit the line items before promoting.
                <br /><br />
                Click <b>Review</b> on a row to open the draft, see the
                source document's extracted fields, edit the proposed
                journal lines, and click <i>Promote to journal entry</i>{" "}
                (or <i>Reject</i>).
              </>
            }
          />
        </div>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          AI-classified drafts awaiting human review and promotion to journal entries.
        </Caption1>
        {roleLoading ? (
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            Resolving your team role...
          </Caption1>
        ) : !capabilities.canPromoteDrafts ? (
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            Your role ({role ? roleDisplayName(role) : "unknown"}) can review drafts but cannot promote or reject them.
          </Caption1>
        ) : (
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            You can review, promote, and reject drafts.
          </Caption1>
        )}
      </div>

      <Section
        title={`${drafts.data?.length ?? 0} pending drafts`}
        subtitle={
          clientId
            ? `Showing ${clientName ?? "one client"} only.`
            : undefined
        }
      >
        {drafts.isLoading && <LoadingState />}
        {drafts.error && <ErrorState error={drafts.error} />}
        {drafts.data && drafts.data.length === 0 && (
          <EmptyState title="Inbox zero" description="Nothing to review right now." />
        )}
        {drafts.data && drafts.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Kind</TableHeaderCell>
                <TableHeaderCell>Confidence</TableHeaderCell>
                <TableHeaderCell>Model</TableHeaderCell>
                <TableHeaderCell>Source document</TableHeaderCell>
                <TableHeaderCell>Posting access</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {drafts.data.map((d) => {
                const conf = Number.parseFloat(d.confidence);
                const color =
                  d.high_confidence ? "success" : conf < 0.6 ? "danger" : "warning";
                return (
                  <TableRow key={d.id}>
                    <TableCell>{d.kind}</TableCell>
                    <TableCell>
                      <Badge appearance="filled" color={color}>
                        {(conf * 100).toFixed(0)}%
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <code>{d.model}</code>
                    </TableCell>
                    <TableCell>
                      <code>{shortId(d.source_document_id)}</code>
                    </TableCell>
                    <TableCell>
                      <Badge appearance="tint" color={capabilities.canPromoteDrafts ? "success" : "warning"}>
                        {capabilities.canPromoteDrafts ? "can post" : "read only"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Link to={`/drafts/${d.id}${clientId ? `?client=${clientId}` : ""}`}>
                        <Button appearance="subtle" icon={<OpenRegular />}>
                          Review
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
