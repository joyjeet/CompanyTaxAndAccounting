import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Dropdown,
  Field,
  Input,
  makeStyles,
  Option,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toaster,
  tokens,
  useToastController,
  useId,
  Toast,
  ToastTitle,
  ToastBody,
} from "@fluentui/react-components";
import { AddRegular, OpenRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { roleDisplayName } from "../auth/firmRole";
import type { EntityType, Industry } from "../auth/types";
import { useFirmRole } from "../auth/useFirmRole";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { shortId } from "../lib/format";

const useStyles = makeStyles({
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
    marginBottom: "16px",
  },
  form: {
    display: "grid",
    rowGap: "12px",
    marginTop: "12px",
  },
  row: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    columnGap: "12px",
    rowGap: "12px",
  },
});

const INDUSTRY_OPTIONS: Industry[] = [
  "generic",
  "construction",
  "retail_ecommerce",
  "professional_services",
];

const INDUSTRY_LABELS: Record<Industry, string> = {
  generic: "General business",
  construction: "Construction",
  retail_ecommerce: "Retail / e-commerce",
  professional_services: "Professional services",
};

const ENTITY_OPTIONS: EntityType[] = [
  "sole_prop",
  "single_member_llc",
  "partnership",
  "s_corp",
  "c_corp",
];

const ENTITY_LABELS: Record<EntityType, string> = {
  sole_prop: "Sole proprietorship (Sch. C)",
  single_member_llc: "Single-member LLC",
  partnership: "Partnership (1065)",
  s_corp: "S corporation (1120-S)",
  c_corp: "C corporation (1120)",
};

const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export default function ClientList() {
  const styles = useStyles();
  const api = useApi();
  const { capabilities, role } = useFirmRole();
  const qc = useQueryClient();
  const toasterId = useId("clients-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [legalName, setLegalName] = useState("");
  const [entityType, setEntityType] = useState<EntityType | "">("");
  const [industry, setIndustry] = useState<Industry>("generic");
  const [taxYear, setTaxYear] = useState(String(new Date().getFullYear()));
  const [fyeMonth, setFyeMonth] = useState("12");
  const [homeState, setHomeState] = useState("");
  const [ein, setEin] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  function resetForm() {
    setName("");
    setCode("");
    setLegalName("");
    setEntityType("");
    setIndustry("generic");
    setTaxYear(String(new Date().getFullYear()));
    setFyeMonth("12");
    setHomeState("");
    setEin("");
    setEmail("");
    setPhone("");
  }

  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients() });
  const create = useMutation({
    mutationFn: () =>
      api.createClient({
        name: name.trim(),
        external_code: code.trim() || null,
        industry,
        entity_type: entityType || null,
        tax_year: taxYear.trim() ? Number(taxYear) : null,
        fiscal_year_end_month: Number(fyeMonth),
        home_state: homeState.trim().toUpperCase() || null,
        business_legal_name: legalName.trim() || null,
        ein: ein.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
      }),
    onSuccess: (c) => {
      dispatchToast(
        <Toast>
          <ToastTitle>Client created</ToastTitle>
          <ToastBody>
            {c.coa_seeded
              ? `${c.name} — default chart of accounts added`
              : c.name}
          </ToastBody>
        </Toast>,
        { intent: "success" },
      );
      if (c.coa_seed_error) {
        // The client exists; only the chart seeding failed. Surface it so
        // the CPA knows a manual step is still outstanding.
        dispatchToast(
          <Toast>
            <ToastTitle>Chart of accounts not created</ToastTitle>
            <ToastBody>{c.coa_seed_error}</ToastBody>
          </Toast>,
          { intent: "warning" },
        );
      }
      setOpen(false);
      resetForm();
      qc.invalidateQueries({ queryKey: ["clients"] });
    },
    onError: (err: Error) => {
      dispatchToast(
        <Toast>
          <ToastTitle>Create failed</ToastTitle>
          <ToastBody>{err.message}</ToastBody>
        </Toast>,
        { intent: "error" },
      );
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <div className={styles.header}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Text size={700} weight="semibold">
              Clients
            </Text>
            <InfoHint
              title="What is a client?"
              body={
                <>
                  Each <b>client</b> is one of your firm's customers —
                  the business whose books you keep. Everything else in
                  the app (chart of accounts, periods, documents,
                  journal entries, statements, tax forms) lives <i>under
                  a client</i>.
                  <br /><br />
                  Click <b>Open</b> on a row to enter that client's
                  workspace. Click <b>New client</b> to onboard a new one
                  — you'll only need a name and (optionally) an external
                  code that matches your accounting system.
                </>
              }
            />
          </div>
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            All clients in your firm. Row-level security enforces tenant boundaries.
          </Caption1>
        </div>
        <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
          <DialogTrigger disableButtonEnhancement>
            <Button
              appearance="primary"
              icon={<AddRegular />}
              disabled={!capabilities.canCreateClient}
            >
              New client
            </Button>
          </DialogTrigger>
          <DialogSurface>
            <DialogBody>
              <DialogTitle>Create a new client</DialogTitle>
              <DialogContent>
                <div className={styles.form}>
                  <Field label="Name" required>
                    <Input
                      value={name}
                      onChange={(_, d) => setName(d.value)}
                      placeholder="Acme LLC"
                    />
                  </Field>
                  <div className={styles.row}>
                    <Field
                      label="Legal name"
                      hint="As registered with the IRS, if different"
                    >
                      <Input
                        value={legalName}
                        onChange={(_, d) => setLegalName(d.value)}
                        placeholder="Acme Holdings LLC"
                      />
                    </Field>
                    <Field label="External code" hint="Optional accounting-system ID">
                      <Input
                        value={code}
                        onChange={(_, d) => setCode(d.value)}
                        placeholder="ACME-001"
                      />
                    </Field>
                  </div>

                  <div className={styles.row}>
                    <Field
                      label="Industry"
                      hint="Adds an industry overlay to the chart of accounts"
                    >
                      <Dropdown
                        value={INDUSTRY_LABELS[industry]}
                        selectedOptions={[industry]}
                        onOptionSelect={(_, d) =>
                          setIndustry(d.optionValue as Industry)
                        }
                      >
                        {INDUSTRY_OPTIONS.map((i) => (
                          <Option key={i} value={i}>
                            {INDUSTRY_LABELS[i]}
                          </Option>
                        ))}
                      </Dropdown>
                    </Field>
                    <Field label="Entity type" hint="Determines which return is filed">
                      <Dropdown
                        value={entityType ? ENTITY_LABELS[entityType] : ""}
                        selectedOptions={entityType ? [entityType] : []}
                        placeholder="Not set yet"
                        onOptionSelect={(_, d) =>
                          setEntityType(d.optionValue as EntityType)
                        }
                      >
                        {ENTITY_OPTIONS.map((e) => (
                          <Option key={e} value={e}>
                            {ENTITY_LABELS[e]}
                          </Option>
                        ))}
                      </Dropdown>
                    </Field>
                  </div>

                  <div className={styles.row}>
                    <Field label="Tax year">
                      <Input
                        type="number"
                        value={taxYear}
                        onChange={(_, d) => setTaxYear(d.value)}
                      />
                    </Field>
                    <Field
                      label="Fiscal year end"
                      hint="Month the books close. 12 for a calendar year."
                    >
                      <Dropdown
                        value={MONTH_LABELS[Number(fyeMonth) - 1]}
                        selectedOptions={[fyeMonth]}
                        onOptionSelect={(_, d) => setFyeMonth(d.optionValue as string)}
                      >
                        {MONTH_LABELS.map((label, idx) => (
                          <Option key={label} value={String(idx + 1)}>
                            {label}
                          </Option>
                        ))}
                      </Dropdown>
                    </Field>
                    <Field label="Home state" hint="2-letter code">
                      <Input
                        value={homeState}
                        maxLength={2}
                        onChange={(_, d) => setHomeState(d.value.toUpperCase())}
                        placeholder="CA"
                      />
                    </Field>
                  </div>

                  <div className={styles.row}>
                    <Field label="EIN">
                      <Input
                        value={ein}
                        onChange={(_, d) => setEin(d.value)}
                        placeholder="12-3456789"
                      />
                    </Field>
                    <Field label="Email">
                      <Input
                        type="email"
                        value={email}
                        onChange={(_, d) => setEmail(d.value)}
                        placeholder="owner@acme.com"
                      />
                    </Field>
                    <Field label="Phone">
                      <Input
                        value={phone}
                        onChange={(_, d) => setPhone(d.value)}
                        placeholder="(555) 010-1234"
                      />
                    </Field>
                  </div>

                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    A standard chart of accounts is created automatically —
                    assets 1xxx, liabilities 2xxx, equity 3xxx, revenue 4xxx,
                    cost of goods sold 5xxx, and operating expenses 6xxx–9xxx.
                    You can edit it afterwards.
                  </Caption1>
                </div>
              </DialogContent>
              <DialogActions>
                <DialogTrigger disableButtonEnhancement>
                  <Button appearance="secondary">Cancel</Button>
                </DialogTrigger>
                <Button
                  appearance="primary"
                  disabled={!name.trim() || create.isPending}
                  onClick={() => create.mutate()}
                >
                  {create.isPending ? <Spinner size="tiny" /> : "Create"}
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      </div>

      {!capabilities.canCreateClient && (
        <Caption1 block style={{ marginBottom: 12, color: tokens.colorNeutralForeground3 }}>
          Your role ({role ? roleDisplayName(role) : "unknown"}) cannot create clients.
        </Caption1>
      )}

      <Section title={`${clients.data?.length ?? 0} clients`}>
        {clients.isLoading && <LoadingState />}
        {clients.error && <ErrorState error={clients.error} />}
        {clients.data && clients.data.length === 0 && (
          <EmptyState
            title="No clients yet"
            description="Create your first client to start managing books."
          />
        )}
        {clients.data && clients.data.length > 0 && (
          <Table size="small" arial-label="Clients">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>External code</TableHeaderCell>
                <TableHeaderCell>Client ID</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {clients.data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <Text weight="semibold">{c.name}</Text>
                  </TableCell>
                  <TableCell>{c.external_code ?? "—"}</TableCell>
                  <TableCell>
                    <code>{shortId(c.id)}</code>
                  </TableCell>
                  <TableCell>
                    <Link to={`/clients/${c.id}`}>
                      <Button appearance="subtle" icon={<OpenRegular />}>
                        Open
                      </Button>
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
