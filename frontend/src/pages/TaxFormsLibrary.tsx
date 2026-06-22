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
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { explainerFor } from "../lib/taxFormExplainers";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  headerRow: { display: "flex", alignItems: "center", gap: "6px" },
});

export default function TaxFormsLibrary() {
  const styles = useStyles();
  const api = useApi();
  const forms = useQuery({ queryKey: ["tax-forms"], queryFn: () => api.listTaxForms() });

  return (
    <div>
      <div className={styles.header}>
        <div className={styles.headerRow}>
          <Text size={700} weight="semibold">Tax form catalog</Text>
          <InfoHint
            title="What is this page?"
            body={
              <>
                A read-only directory of every tax form the platform can
                produce, across all your clients. Use it to confirm a form +
                jurisdiction + catalog version is supported before you start
                mapping a client's chart of accounts to it.
                <br /><br />
                The real work — proposing mappings, generating worksheets,
                approving and packaging — happens inside a specific client
                under <b>Client &rarr; Tax</b>.
              </>
            }
          />
        </div>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Available forms across all clients. Mapping &amp; worksheets live under each client.
        </Caption1>
      </div>
      <Section
        title="Available forms"
        help={{
          title: "About catalog versions",
          body: (
            <>
              Each form has a <code>catalog_version</code> (e.g.{" "}
              <code>2024.1</code>) so worksheets are reproducible even after
              the IRS publishes new line numbers. Generating a worksheet
              snapshots the version in use, so old returns always re-render
              against the rules in force when they were filed.
            </>
          ),
        }}
      >
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
              {forms.data.map((f) => {
                const exp = explainerFor(f.code);
                return (
                  <TableRow key={f.id}>
                    <TableCell>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                        <code>{f.code}</code>
                        {exp && <InfoHint title={exp.title} body={exp.body} />}
                      </span>
                    </TableCell>
                    <TableCell>{f.label}</TableCell>
                    <TableCell>{f.jurisdiction}</TableCell>
                    <TableCell>{f.catalog_version}</TableCell>
                    <TableCell>{f.is_active ? "yes" : "no"}</TableCell>
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
