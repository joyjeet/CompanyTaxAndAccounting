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
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
});

export default function ReviewQueue() {
  const styles = useStyles();
  const api = useApi();
  const drafts = useQuery({
    queryKey: ["drafts", "pending"],
    queryFn: () => api.listDrafts(true),
  });

  return (
    <div>
      <div className={styles.header}>
        <Text size={700} weight="semibold">Review queue</Text>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          AI-classified drafts awaiting human review and promotion to journal entries.
        </Caption1>
      </div>

      <Section title={`${drafts.data?.length ?? 0} pending drafts`}>
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
                      <Link to={`/drafts/${d.id}`}>
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
