/**
 * Editable client profile — business identity + entity type + contact &
 * address. Shared between the firm-side client detail page and the
 * client-portal "My profile" page. The backend allows both scopes to
 * write (RLS confines portal users to their own client).
 *
 * The form uses PATCH semantics: we send only the keys the user touched,
 * which lines up with the backend's _UNSET sentinel and avoids
 * clobbering fields the other side just updated.
 */
import {
  Body1,
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  Text,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { useApi } from "../api/useApi";
import type {
  ClientProfileOut,
  ClientProfileUpsertIn,
  EntityType,
  Industry,
} from "../auth/types";
import DashboardCard from "./DashboardCard";

// --------------------------------------------------------------------- //
// Reference data
// --------------------------------------------------------------------- //
const ENTITY_TYPES: Array<{ value: EntityType; label: string; form: string }> = [
  { value: "c_corp", label: "C Corporation", form: "IRS Form 1120" },
  { value: "s_corp", label: "S Corporation", form: "IRS Form 1120-S" },
  { value: "partnership", label: "Partnership / Multi-member LLC", form: "IRS Form 1065" },
  {
    value: "single_member_llc",
    label: "Single-member LLC",
    form: "Schedule C (Form 1040)",
  },
  { value: "sole_prop", label: "Sole Proprietor", form: "Schedule C (Form 1040)" },
];

const INDUSTRIES: Array<{ value: Industry; label: string }> = [
  { value: "generic", label: "Other / General" },
  { value: "construction", label: "Construction" },
  { value: "retail_ecommerce", label: "Retail / E-commerce" },
  { value: "professional_services", label: "Professional Services" },
];

const FYE_MONTHS = [
  { value: 1, label: "January" },
  { value: 2, label: "February" },
  { value: 3, label: "March" },
  { value: 4, label: "April" },
  { value: 5, label: "May" },
  { value: 6, label: "June" },
  { value: 7, label: "July" },
  { value: 8, label: "August" },
  { value: 9, label: "September" },
  { value: 10, label: "October" },
  { value: 11, label: "November" },
  { value: 12, label: "December" },
];

const US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
  "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY","DC",
];

// --------------------------------------------------------------------- //
// Form state
// --------------------------------------------------------------------- //
type Draft = {
  business_legal_name: string;
  dba_name: string;
  ein: string;
  entity_type: EntityType | "";
  industry: Industry;
  fiscal_year_end_month: number | "";
  tax_year: string;
  home_state: string;
  phone: string;
  email: string;
  website: string;
  address_line1: string;
  address_line2: string;
  city: string;
  address_state: string;
  postal_code: string;
  country: string;
};

const EMPTY: Draft = {
  business_legal_name: "",
  dba_name: "",
  ein: "",
  entity_type: "",
  industry: "generic",
  fiscal_year_end_month: "",
  tax_year: "",
  home_state: "",
  phone: "",
  email: "",
  website: "",
  address_line1: "",
  address_line2: "",
  city: "",
  address_state: "",
  postal_code: "",
  country: "US",
};

function fromServer(p: ClientProfileOut | null): Draft {
  if (!p) return EMPTY;
  return {
    business_legal_name: p.business_legal_name ?? "",
    dba_name: p.dba_name ?? "",
    ein: p.ein ?? "",
    entity_type: p.entity_type ?? "",
    industry: p.industry ?? "generic",
    fiscal_year_end_month: p.fiscal_year_end_month ?? "",
    tax_year: p.tax_year ? String(p.tax_year) : "",
    home_state: p.home_state ?? "",
    phone: p.phone ?? "",
    email: p.email ?? "",
    website: p.website ?? "",
    address_line1: p.address_line1 ?? "",
    address_line2: p.address_line2 ?? "",
    city: p.city ?? "",
    address_state: p.address_state ?? "",
    postal_code: p.postal_code ?? "",
    country: p.country ?? "US",
  };
}

/** Build a PATCH body containing only fields the user changed.
 * A blank-string in the draft for a previously-set field is treated as
 * "clear it" (we send ``null``). */
function diff(
  before: Draft,
  after: Draft,
): ClientProfileUpsertIn {
  const out: ClientProfileUpsertIn = {};
  const send = (key: keyof Draft, val: unknown) => {
    (out as Record<string, unknown>)[key] = val;
  };
  const strFields: Array<keyof Draft> = [
    "business_legal_name",
    "dba_name",
    "ein",
    "home_state",
    "phone",
    "email",
    "website",
    "address_line1",
    "address_line2",
    "city",
    "address_state",
    "postal_code",
    "country",
  ];
  for (const k of strFields) {
    if (before[k] === after[k]) continue;
    const v = (after[k] as string).trim();
    send(k, v === "" ? null : v);
  }
  if (before.entity_type !== after.entity_type) {
    send("entity_type", after.entity_type === "" ? null : after.entity_type);
  }
  if (before.industry !== after.industry) {
    send("industry", after.industry);
  }
  if (before.fiscal_year_end_month !== after.fiscal_year_end_month) {
    send(
      "fiscal_year_end_month",
      after.fiscal_year_end_month === "" ? null : after.fiscal_year_end_month,
    );
  }
  if (before.tax_year !== after.tax_year) {
    const v = after.tax_year.trim();
    send("tax_year", v === "" ? null : Number(v));
  }
  return out;
}

// --------------------------------------------------------------------- //
// Styles
// --------------------------------------------------------------------- //
const useStyles = makeStyles({
  page: {
    display: "flex",
    flexDirection: "column",
    rowGap: "16px",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    columnGap: "16px",
    rowGap: "12px",
  },
  wide: { gridColumn: "1 / -1" },
  footer: {
    display: "flex",
    justifyContent: "flex-end",
    alignItems: "center",
    columnGap: "12px",
    marginTop: "8px",
    paddingTop: "12px",
    ...shorthands.borderTop("1px", "solid", tokens.colorNeutralStroke2),
  },
  hint: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    marginTop: "4px",
  },
  formNote: {
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
  },
});

// --------------------------------------------------------------------- //
// Main component
// --------------------------------------------------------------------- //
export default function ClientProfileForm({
  clientId,
  clientName,
  audience,
}: {
  clientId: string;
  /** Display name used in headings (firm-side passes the legal/short name,
   * portal-side just passes "your business" or similar). */
  clientName?: string;
  /** Adjusts microcopy. Firm staff get neutral wording; portal users see
   * "what is this for" hints. */
  audience: "firm" | "client";
}) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();

  const profile = useQuery({
    queryKey: ["client-profile", clientId],
    queryFn: () => api.getClientProfile(clientId),
  });

  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Reset draft when the server data arrives or changes.
  const serverDraft = useMemo(
    () => fromServer(profile.data ?? null),
    [profile.data],
  );
  useEffect(() => {
    setDraft(serverDraft);
  }, [serverDraft]);

  const mutation = useMutation({
    mutationFn: (body: ClientProfileUpsertIn) =>
      api.upsertClientProfile(clientId, body),
    onSuccess: (next) => {
      qc.setQueryData(["client-profile", clientId], next);
      setSavedAt(Date.now());
      setErrorMsg(null);
    },
    onError: (err: unknown) => {
      setErrorMsg(err instanceof Error ? err.message : "Save failed.");
    },
  });

  const dirty = useMemo(() => {
    return JSON.stringify(serverDraft) !== JSON.stringify(draft);
  }, [serverDraft, draft]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  if (profile.isLoading) {
    return <Spinner label="Loading profile…" />;
  }

  // Picked entity type → friendly form name for the inline hint.
  const formForEntity = ENTITY_TYPES.find(
    (e) => e.value === draft.entity_type,
  )?.form;

  const onSave = () => {
    const body = diff(serverDraft, draft);
    if (Object.keys(body).length === 0) return;
    mutation.mutate(body);
  };

  const onReset = () => {
    setDraft(serverDraft);
    setErrorMsg(null);
  };

  return (
    <div className={styles.page}>
      {audience === "client" && (
        <Body1 style={{ color: tokens.colorNeutralForeground2 }}>
          Keep your business profile current so we can prepare the right tax
          forms and reach you when we need a signature. Your CPA will review
          anything you change.
        </Body1>
      )}

      {errorMsg && (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>Couldn't save profile</MessageBarTitle>
            {errorMsg}
          </MessageBarBody>
        </MessageBar>
      )}
      {!errorMsg && savedAt && !dirty && (
        <MessageBar intent="success">
          <MessageBarBody>Profile saved.</MessageBarBody>
        </MessageBar>
      )}

      {/* ----------- Business identity ----------- */}
      <DashboardCard
        overline="Business identity"
        subtitle={
          clientName ? `Filing details for ${clientName}` : "Filing details"
        }
      >
        <div className={styles.grid}>
          <Field label="Legal name (as shown on tax filings)">
            <Input
              value={draft.business_legal_name}
              onChange={(_, d) => set("business_legal_name", d.value)}
              placeholder="Acme Industries LLC"
            />
          </Field>
          <Field label="Doing-business-as (optional)">
            <Input
              value={draft.dba_name}
              onChange={(_, d) => set("dba_name", d.value)}
              placeholder="Acme"
            />
          </Field>
          <Field
            label="Federal EIN"
            hint="Format: 12-3456789"
          >
            <Input
              value={draft.ein}
              onChange={(_, d) => set("ein", d.value)}
              placeholder="12-3456789"
            />
          </Field>
          <Field label="Industry">
            <Dropdown
              value={
                INDUSTRIES.find((i) => i.value === draft.industry)?.label ?? ""
              }
              selectedOptions={[draft.industry]}
              onOptionSelect={(_, d) =>
                set("industry", (d.optionValue as Industry) ?? "generic")
              }
            >
              {INDUSTRIES.map((i) => (
                <Option key={i.value} value={i.value}>
                  {i.label}
                </Option>
              ))}
            </Dropdown>
          </Field>
          <Field
            label="Entity type"
            hint={
              formForEntity
                ? `We'll prepare ${formForEntity} for this client.`
                : "Determines which IRS tax form we'll prepare."
            }
          >
            <Dropdown
              value={
                draft.entity_type
                  ? ENTITY_TYPES.find((e) => e.value === draft.entity_type)
                      ?.label ?? ""
                  : ""
              }
              placeholder="Select entity type…"
              selectedOptions={draft.entity_type ? [draft.entity_type] : []}
              onOptionSelect={(_, d) =>
                set("entity_type", (d.optionValue as EntityType) ?? "")
              }
            >
              {ENTITY_TYPES.map((e) => (
                <Option key={e.value} value={e.value} text={e.label}>
                  <div>
                    <div>{e.label}</div>
                    <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                      {e.form}
                    </Caption1>
                  </div>
                </Option>
              ))}
            </Dropdown>
          </Field>
          <Field label="Fiscal year-end month">
            <Dropdown
              value={
                draft.fiscal_year_end_month
                  ? FYE_MONTHS.find(
                      (m) => m.value === draft.fiscal_year_end_month,
                    )?.label ?? ""
                  : ""
              }
              placeholder="December (calendar year)"
              selectedOptions={
                draft.fiscal_year_end_month
                  ? [String(draft.fiscal_year_end_month)]
                  : []
              }
              onOptionSelect={(_, d) => {
                const v = d.optionValue ? Number(d.optionValue) : "";
                set("fiscal_year_end_month", v as Draft["fiscal_year_end_month"]);
              }}
            >
              {FYE_MONTHS.map((m) => (
                <Option key={m.value} value={String(m.value)}>
                  {m.label}
                </Option>
              ))}
            </Dropdown>
          </Field>
          <Field label="Tax year (current filing)">
            <Input
              value={draft.tax_year}
              onChange={(_, d) => set("tax_year", d.value.replace(/[^0-9]/g, ""))}
              placeholder="2025"
              maxLength={4}
            />
          </Field>
          <Field label="Home state">
            <Dropdown
              value={draft.home_state}
              placeholder="Select state…"
              selectedOptions={draft.home_state ? [draft.home_state] : []}
              onOptionSelect={(_, d) =>
                set("home_state", (d.optionValue ?? "").toUpperCase())
              }
            >
              {US_STATES.map((s) => (
                <Option key={s} value={s}>
                  {s}
                </Option>
              ))}
            </Dropdown>
          </Field>
        </div>
      </DashboardCard>

      {/* ----------- Contact & address ----------- */}
      <DashboardCard
        overline="Contact & address"
        subtitle="How we reach you, and the address that prints on official forms"
      >
        <div className={styles.grid}>
          <Field label="Phone">
            <Input
              type="tel"
              value={draft.phone}
              onChange={(_, d) => set("phone", d.value)}
              placeholder="(555) 123-4567"
            />
          </Field>
          <Field label="Email">
            <Input
              type="email"
              value={draft.email}
              onChange={(_, d) => set("email", d.value)}
              placeholder="owner@acme.com"
            />
          </Field>
          <Field label="Website" className={styles.wide}>
            <Input
              value={draft.website}
              onChange={(_, d) => set("website", d.value)}
              placeholder="https://acme.com"
            />
          </Field>
          <Field label="Address line 1" className={styles.wide}>
            <Input
              value={draft.address_line1}
              onChange={(_, d) => set("address_line1", d.value)}
              placeholder="123 Main St"
            />
          </Field>
          <Field label="Address line 2 (suite, etc.)" className={styles.wide}>
            <Input
              value={draft.address_line2}
              onChange={(_, d) => set("address_line2", d.value)}
              placeholder="Suite 200"
            />
          </Field>
          <Field label="City">
            <Input
              value={draft.city}
              onChange={(_, d) => set("city", d.value)}
              placeholder="San Francisco"
            />
          </Field>
          <Field label="State">
            <Dropdown
              value={draft.address_state}
              placeholder="State"
              selectedOptions={
                draft.address_state ? [draft.address_state] : []
              }
              onOptionSelect={(_, d) =>
                set("address_state", (d.optionValue ?? "").toUpperCase())
              }
            >
              {US_STATES.map((s) => (
                <Option key={s} value={s}>
                  {s}
                </Option>
              ))}
            </Dropdown>
          </Field>
          <Field label="ZIP / postal code">
            <Input
              value={draft.postal_code}
              onChange={(_, d) => set("postal_code", d.value)}
              placeholder="94105"
            />
          </Field>
          <Field label="Country">
            <Input
              value={draft.country}
              onChange={(_, d) =>
                set("country", d.value.toUpperCase().slice(0, 2))
              }
              maxLength={2}
              placeholder="US"
            />
          </Field>
        </div>

        <div className={styles.footer}>
          {dirty && (
            <Text className={styles.formNote}>You have unsaved changes</Text>
          )}
          <Button
            appearance="secondary"
            disabled={!dirty || mutation.isPending}
            onClick={onReset}
          >
            Discard
          </Button>
          <Button
            appearance="primary"
            disabled={!dirty || mutation.isPending}
            onClick={onSave}
          >
            {mutation.isPending ? "Saving…" : "Save profile"}
          </Button>
        </div>
      </DashboardCard>
    </div>
  );
}
