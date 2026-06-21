import {
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
import { useQuery } from "@tanstack/react-query";

import { useApi } from "../api/useApi";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
});

export default function TaxFormsLibrary() {
  const styles = useStyles();
  const api = useApi();
  const forms = useQuery({ queryKey: ["tax-forms"], queryFn: () => api.listTaxForms() });

  return (
    <div>
      <div className={styles.header}>
        <Text size={700} weight="semibold">Tax form catalog</Text>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Available forms across all clients. Mapping &amp; worksheets live under each client.
        </Caption1>
      </div>
      <Section title="Available forms">
        {forms.isLoading && <LoadingState />}
        {forms.error && <ErrorState error={forms.error} />}
        {forms.data && forms.data.length === 0 && <EmptyState title="No tax forms seeded" />}
        {forms.data && forms.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Code</TableHeaderCell>
                <TableHeaderCell>Label</TableHeaderCell>
                <TableHeaderCell>Jurisdiction</TableHeaderCell>
                <TableHeaderCell>Catalog</TableHeaderCell>
                <TableHeaderCell>Active</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {forms.data.map((f) => (
                <TableRow key={f.id}>
                  <TableCell><code>{f.code}</code></TableCell>
                  <TableCell>{f.label}</TableCell>
                  <TableCell>{f.jurisdiction}</TableCell>
                  <TableCell>{f.catalog_version}</TableCell>
                  <TableCell>{f.is_active ? "yes" : "no"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
