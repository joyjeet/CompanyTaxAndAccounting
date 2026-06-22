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
import { ArrowExportRegular, CheckmarkCircleRegular, SparkleRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useApi } from "../../api/useApi";
import InfoHint from "../../components/InfoHint";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fmtMoney, shortId } from "../../lib/format";
import { explainerFor } from "../../lib/taxFormExplainers";

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
  // Resolve line UUIDs -> human-readable codes for whichever form is loaded.
  const lineMap = useMemo(
    () => new Map((formDetail.data?.lines ?? []).map((ln) => [ln.id, ln])),
    [formDetail.data],
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

  // Render an approved worksheet into the Artifacts library as a PDF
  // (encrypted at rest, finalize+download from the Artifacts tab).
  const renderPdf = useMutation({
    mutationFn: (id: string) => api.renderTaxWorksheet(id, "pdf"),
    onSuccess: (art) => {
      dispatchToast(
        <Toast>
          <ToastTitle>
            PDF rendered — see it in the Artifacts tab ({(art.size_bytes / 1024).toFixed(1)} KB)
          </ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  // --- Auto-mapping mutations ---------------------------------------- //
  const autoPropose = useMutation({
    mutationFn: () => api.autoProposeMappings({ form_code: formCode }),
    onSuccess: (res) => {
      const n = res.proposed_mapping_ids.length;
      const ex = res.already_existed.length;
      dispatchToast(
        <Toast>
          <ToastTitle>
            Proposed {n} new mapping{n === 1 ? "" : "s"}
            {ex > 0 ? ` (${ex} already existed)` : ""}
          </ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["tax-mappings"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const approveAll = useMutation({
    mutationFn: () => api.approveAllMappings({ form_code: formCode }),
    onSuccess: (ids) => {
      dispatchToast(
        <Toast>
          <ToastTitle>Approved {ids.length} draft mapping{ids.length === 1 ? "" : "s"}</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["tax-mappings"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const approveOne = useMutation({
    mutationFn: (id: string) => api.approveMapping(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tax-mappings"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const rejectOne = useMutation({
    mutationFn: (id: string) => api.rejectMapping(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tax-mappings"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const autoFill = useMutation({
    mutationFn: () =>
      api.autoFillWorksheet({ period_id: periodId, form_code: formCode }),
    onSuccess: (res) => {
      dispatchToast(
        <Toast>
          <ToastTitle>
            Auto-fill done — taxable income {res.worksheet.taxable_income}
          </ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["tax-mappings"] });
      qc.invalidateQueries({ queryKey: ["worksheets"] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <TabList selectedValue={view} onTabSelect={(_, d) => setView(d.value as TaxView)}>
          <Tab value="forms">Forms</Tab>
          <Tab value="mappings">Account mappings</Tab>
          <Tab value="worksheets">Worksheets</Tab>
        </TabList>
        <InfoHint
          title="How the Tax tab works"
          body={
            <>
              The Tax tab takes you from <b>blank books → a signed tax
              worksheet</b> in three steps:
              <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
                <li>
                  <b>Forms</b> — inspect the catalog (Form 1120, Schedule C,
                  state forms, etc.) to see what lines a worksheet will
                  compute.
                </li>
                <li>
                  <b>Account mappings</b> — for each of your chart-of-accounts
                  lines, approve which tax form line it rolls up to. Only
                  approved mappings flow into a worksheet.
                </li>
                <li>
                  <b>Worksheets</b> — pick a period + form and click Generate.
                  The system aggregates posted journal entries through the
                  approved mappings and produces an immutable, signed
                  worksheet you can approve and ship to the artifact library.
                </li>
              </ol>
            </>
          }
        />
      </div>

      <div style={{ marginTop: 16 }}>
        {view === "forms" && (
          <Section
            title="Available tax forms"
            help={{
              title: "Why this list exists",
              body: (
                <>
                  This is the <b>catalog of tax forms</b> the system knows how
                  to produce for this client (federal + state, by
                  jurisdiction and catalog version).
                  <br /><br />
                  Click <b>Inspect</b> on a row to see every line on that
                  form — useful when deciding how to map an account in the
                  next tab. Nothing here changes your books; it's read-only
                  reference data.
                </>
              ),
            }}
          >
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
                        <TableCell>
                          <Button
                            appearance="subtle"
                            onClick={() => setFormCode(f.code)}
                          >
                            Inspect
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
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
            help={{
              title: "What you're doing here",
              body: (
                <>
                  A tax worksheet has to know <i>which chart-of-accounts
                  balance</i> rolls up to <i>which tax-form line</i> (e.g. is
                  account <code>4000 Sales</code> Line 1a or Line 1b of Form
                  1120?).
                  <br /><br />
                  Mappings start as <Badge appearance="tint" color="warning">proposed</Badge>{" "}
                  — review each one and either approve it (it counts toward
                  the worksheet) or reject it (excluded). Filter by form to
                  focus on one return at a time.
                  <br /><br />
                  Tip: until at least one mapping is approved, generating a
                  worksheet on the next tab will produce zeros.
                </>
              ),
            }}
            toolbar={
              <div className={styles.toolbar}>
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
                <Button
                  appearance="primary"
                  icon={<SparkleRegular />}
                  disabled={!formCode || autoPropose.isPending}
                  onClick={() => autoPropose.mutate()}
                  title={
                    formCode
                      ? `Auto-propose mappings from this client's chart of accounts onto ${formCode}.`
                      : "Pick a form first."
                  }
                >
                  Auto-propose from COA
                </Button>
                <Button
                  appearance="secondary"
                  disabled={
                    !formCode ||
                    approveAll.isPending ||
                    !(mappings.data ?? []).some((m) => m.status === "proposed" || m.status === "draft")
                  }
                  onClick={() => approveAll.mutate()}
                  title="Approve every DRAFT mapping for the selected form."
                >
                  Approve all drafts
                </Button>
              </div>
            }
          >
            {mappings.isLoading && <LoadingState />}
            {mappings.error && <ErrorState error={mappings.error} />}
            {mappings.data && mappings.data.length === 0 && (
              <EmptyState
                title="No mappings yet"
                description={
                  formCode
                    ? `Click "Auto-propose from COA" to generate draft mappings for ${formCode}, then approve them.`
                    : "Pick a form above, then click \"Auto-propose from COA\"."
                }
              />
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
                    <TableHeaderCell>Actions</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mappings.data.map((m) => {
                    const a = accountMap.get(m.account_id);
                    const ln = lineMap.get(m.line_id);
                    const isDraft = m.status === "draft" || m.status === "proposed";
                    return (
                      <TableRow key={m.id}>
                        <TableCell>
                          {a ? <><code>{a.code}</code> {a.name}</> : <code>{shortId(m.account_id)}</code>}
                        </TableCell>
                        <TableCell><code>{shortId(m.form_id)}</code></TableCell>
                        <TableCell>
                          {ln ? (
                            <>
                              <code>{ln.code}</code> {ln.label}
                            </>
                          ) : (
                            <code>{shortId(m.line_id)}</code>
                          )}
                        </TableCell>
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
                        <TableCell>
                          {isDraft && (
                            <div style={{ display: "flex", gap: 4 }}>
                              <Button
                                appearance="primary"
                                size="small"
                                icon={<CheckmarkCircleRegular />}
                                disabled={approveOne.isPending}
                                onClick={() => approveOne.mutate(m.id)}
                              >
                                Approve
                              </Button>
                              <Button
                                appearance="subtle"
                                size="small"
                                disabled={rejectOne.isPending}
                                onClick={() => rejectOne.mutate(m.id)}
                              >
                                Reject
                              </Button>
                            </div>
                          )}
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
            help={{
              title: "What a worksheet is and what to do",
              body: (
                <>
                  A <b>worksheet</b> is a point-in-time computation of
                  taxable income for one accounting period and one tax form,
                  built by walking your posted journal entries through the
                  <i> approved</i> account → tax-line mappings.
                  <br /><br />
                  <b>To use this page:</b>
                  <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
                    <li>Pick a <b>Period</b> (must be closed or in-progress).</li>
                    <li>Pick a <b>Form</b> (e.g. <code>F1120</code>).</li>
                    <li>
                      Click <b>Generate</b>. The system snapshots Income,
                      COGS, Deductions, and Taxable income.
                    </li>
                    <li>
                      Review the numbers, then click <b>Approve</b>. Approval
                      seals the worksheet and makes it eligible to be
                      packaged into a signed PDF in the Artifacts tab.
                    </li>
                  </ol>
                  Worksheets are <b>immutable</b> once generated — if a
                  number looks wrong, fix the underlying journal entry or
                  mapping and re-generate. The old worksheet stays as an
                  audit record.
                </>
              ),
            }}
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
                <Button
                  appearance="secondary"
                  icon={<SparkleRegular />}
                  disabled={!periodId || !formCode || autoFill.isPending}
                  onClick={() => autoFill.mutate()}
                  title="Heuristic-propose mappings, approve them all, and generate the worksheet in one step."
                >
                  Auto-fill (1-click)
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
                        {w.status === "approved" && (
                          <Button
                            appearance="primary"
                            size="small"
                            icon={<ArrowExportRegular />}
                            onClick={() => renderPdf.mutate(w.id)}
                            disabled={renderPdf.isPending}
                            title="Render this worksheet as a signed PDF in the Artifacts library."
                          >
                            Render to PDF
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
