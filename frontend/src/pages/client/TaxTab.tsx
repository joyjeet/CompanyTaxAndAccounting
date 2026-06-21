import {
  Badge,
  Body1,
  Button,
  Dropdown,
  makeStyles,
  Option,
  Tab,
  TabList,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { CheckmarkCircleRegular, SparkleRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtMoney, shortId } from "../../lib/format";

type TaxView = "forms" | "mappings" | "worksheets";

const useStyles = makeStyles({
  toolbar: { display: "flex", gap: "12px", alignItems: "center", marginBottom: "12px" },
  num: { textAlign: "right", fontFamily: tokens.fontFamilyMonospace },
});

export default function TaxTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("tax-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [view, setView] = useState<TaxView>("forms");
  const [formCode, setFormCode] = useState<string>("");
  const [periodId, setPeriodId] = useState<string>("");

  const forms = useQuery({ queryKey: ["tax-forms"], queryFn: () => api.listTaxForms() });
  const formDetail = useQuery({
    queryKey: ["tax-form", formCode],
    queryFn: () => api.getTaxForm(formCode),
    enabled: !!formCode,
  });
  const mappings = useQuery({
    queryKey: ["tax-mappings", formCode || "all"],
    queryFn: () => api.listMappings(formCode || undefined),
  });
  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });
  const worksheets = useQuery({
    queryKey: ["worksheets", periodId, formCode],
    queryFn: () => api.listWorksheets(periodId || undefined, formCode || undefined),
  });

  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });
  const accountMap = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.id, a])),
    [accounts.data],
  );

  const generate = useMutation({
    mutationFn: () =>
      api.generateWorksheet({ period_id: periodId, form_code: formCode }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Worksheet generated</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["worksheets"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const approve = useMutation({
    mutationFn: (id: string) => api.approveWorksheet(id),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Worksheet approved</ToastTitle></Toast>, { intent: "success" });
      qc.invalidateQueries({ queryKey: ["worksheets"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />

      <TabList selectedValue={view} onTabSelect={(_, d) => setView(d.value as TaxView)}>
        <Tab value="forms">Forms</Tab>
        <Tab value="mappings">Account mappings</Tab>
        <Tab value="worksheets">Worksheets</Tab>
      </TabList>

      <div style={{ marginTop: 16 }}>
        {view === "forms" && (
          <Section title="Available tax forms">
            {forms.isLoading && <LoadingState />}
            {forms.error && <ErrorState error={forms.error} />}
            {forms.data && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Code</TableHeaderCell>
                    <TableHeaderCell>Label</TableHeaderCell>
                    <TableHeaderCell>Jurisdiction</TableHeaderCell>
                    <TableHeaderCell>Catalog</TableHeaderCell>
                    <TableHeaderCell></TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {forms.data.map((f) => (
                    <TableRow key={f.id}>
                      <TableCell><code>{f.code}</code></TableCell>
                      <TableCell>{f.label}</TableCell>
                      <TableCell>{f.jurisdiction}</TableCell>
                      <TableCell>{f.catalog_version}</TableCell>
                      <TableCell>
                        <Button
                          appearance="subtle"
                          onClick={() => setFormCode(f.code)}
                        >
                          Inspect
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {formDetail.data && (
              <div style={{ marginTop: 24 }}>
                <Text size={500} weight="semibold" block>
                  Lines for {formDetail.data.code} — {formDetail.data.label}
                </Text>
                <Table size="extra-small" style={{ marginTop: 8 }}>
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>Seq</TableHeaderCell>
                      <TableHeaderCell>Code</TableHeaderCell>
                      <TableHeaderCell>Label</TableHeaderCell>
                      <TableHeaderCell>Section</TableHeaderCell>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {formDetail.data.lines.map((ln) => (
                      <TableRow key={ln.id}>
                        <TableCell>{ln.sequence}</TableCell>
                        <TableCell><code>{ln.code}</code></TableCell>
                        <TableCell>{ln.label}</TableCell>
                        <TableCell>{ln.section}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Section>
        )}

        {view === "mappings" && (
          <Section
            title="Account → tax-line mappings"
            subtitle="Approve mappings to make accounts eligible for worksheet generation."
            toolbar={
              <Dropdown
                placeholder="All forms"
                value={formCode || "All forms"}
                selectedOptions={formCode ? [formCode] : []}
                onOptionSelect={(_, d) => setFormCode(d.optionValue ?? "")}
              >
                <Option value="">All forms</Option>
                {(forms.data ?? []).map((f) => (
                  <Option key={f.code} value={f.code}>{f.code}</Option>
                ))}
              </Dropdown>
            }
          >
            {mappings.isLoading && <LoadingState />}
            {mappings.error && <ErrorState error={mappings.error} />}
            {mappings.data && mappings.data.length === 0 && (
              <EmptyState title="No mappings yet" description="Propose mappings from the worksheet flow." />
            )}
            {mappings.data && mappings.data.length > 0 && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Account</TableHeaderCell>
                    <TableHeaderCell>Form</TableHeaderCell>
                    <TableHeaderCell>Line</TableHeaderCell>
                    <TableHeaderCell>Sign</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mappings.data.map((m) => {
                    const a = accountMap.get(m.account_id);
                    return (
                      <TableRow key={m.id}>
                        <TableCell>
                          {a ? <><code>{a.code}</code> {a.name}</> : <code>{shortId(m.account_id)}</code>}
                        </TableCell>
                        <TableCell><code>{shortId(m.form_id)}</code></TableCell>
                        <TableCell><code>{shortId(m.line_id)}</code></TableCell>
                        <TableCell>{m.sign}</TableCell>
                        <TableCell>
                          <Badge
                            appearance="tint"
                            color={
                              m.status === "approved"
                                ? "success"
                                : m.status === "rejected"
                                  ? "danger"
                                  : "warning"
                            }
                          >
                            {m.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </Section>
        )}

        {view === "worksheets" && (
          <Section
            title="Tax worksheets"
            subtitle="Immutable snapshots of taxable income per period × form."
            toolbar={
              <div className={styles.toolbar}>
                <Dropdown
                  placeholder="Period"
                  value={periods.data?.find((p) => p.id === periodId)?.name ?? ""}
                  selectedOptions={periodId ? [periodId] : []}
                  onOptionSelect={(_, d) => setPeriodId(d.optionValue ?? "")}
                >
                  {(periods.data ?? []).map((p) => (
                    <Option key={p.id} value={p.id}>{p.name}</Option>
                  ))}
                </Dropdown>
                <Dropdown
                  placeholder="Form"
                  value={formCode}
                  selectedOptions={formCode ? [formCode] : []}
                  onOptionSelect={(_, d) => setFormCode(d.optionValue ?? "")}
                >
                  {(forms.data ?? []).map((f) => (
                    <Option key={f.code} value={f.code}>{f.code}</Option>
                  ))}
                </Dropdown>
                <Button
                  appearance="primary"
                  icon={<SparkleRegular />}
                  disabled={!periodId || !formCode || generate.isPending}
                  onClick={() => generate.mutate()}
                >
                  Generate
                </Button>
              </div>
            }
          >
            {worksheets.isLoading && <LoadingState />}
            {worksheets.error && <ErrorState error={worksheets.error} />}
            {worksheets.data && worksheets.data.length === 0 && (
              <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
                No worksheets — select a period + form and click Generate.
              </Body1>
            )}
            {worksheets.data && worksheets.data.length > 0 && (
              <Table size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell>Period</TableHeaderCell>
                    <TableHeaderCell>Catalog</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Income</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>COGS</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Deductions</TableHeaderCell>
                    <TableHeaderCell className={styles.num}>Taxable</TableHeaderCell>
                    <TableHeaderCell></TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {worksheets.data.map((w) => (
                    <TableRow key={w.id}>
                      <TableCell>
                        <Badge
                          appearance="tint"
                          color={w.status === "approved" ? "success" : "warning"}
                        >
                          {w.status}
                        </Badge>
                      </TableCell>
                      <TableCell><code>{shortId(w.period_id)}</code></TableCell>
                      <TableCell>{w.catalog_version}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(w.total_income)}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(w.total_cogs)}</TableCell>
                      <TableCell className={styles.num}>{fmtMoney(w.total_deductions)}</TableCell>
                      <TableCell className={styles.num}>
                        <Text weight="semibold">{fmtMoney(w.taxable_income)}</Text>
                      </TableCell>
                      <TableCell>
                        {w.status !== "approved" && (
                          <Button
                            appearance="subtle"
                            icon={<CheckmarkCircleRegular />}
                            onClick={() => approve.mutate(w.id)}
                            disabled={approve.isPending}
                          >
                            Approve
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}
