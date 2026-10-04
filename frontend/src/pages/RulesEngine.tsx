import {
  Body1,
  Button,
  Caption1,
  Field,
  Input,
  makeStyles,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { SaveRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useApi } from "../api/useApi";
import { useFirmRole } from "../auth/useFirmRole";
import InfoHint from "../components/InfoHint";
import Section from "../components/Section";
import { ErrorState, LoadingState } from "../components/States";

const useStyles = makeStyles({
  header: { marginBottom: "16px" },
  headerRow: { display: "flex", alignItems: "center", gap: "6px" },
  meta: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(180px, 1fr))",
    gap: "12px",
  },
  editor: {
    minHeight: "360px",
    fontFamily: tokens.fontFamilyMonospace,
  },
});

export default function RulesEngine() {
  const styles = useStyles();
  const api = useApi();
  const { capabilities, role } = useFirmRole();
  const qc = useQueryClient();
  const toasterId = useId("rules-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const rules = useQuery({
    queryKey: ["rules-engine"],
    queryFn: () => api.getRulesEngine(),
  });

  const [content, setContent] = useState("");

  useEffect(() => {
    if (rules.data?.content !== undefined) {
      setContent(rules.data.content);
    }
  }, [rules.data?.content]);

  const save = useMutation({
    mutationFn: () => api.updateRulesEngine(content),
    onSuccess: () => {
      dispatchToast(
        <Toast>
          <ToastTitle>Rules saved and backend runtime reloaded.</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["rules-engine"] });
    },
    onError: (err: Error) => {
      dispatchToast(
        <Toast>
          <ToastTitle>{err.message}</ToastTitle>
        </Toast>,
        { intent: "error" },
      );
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />

      <div className={styles.header}>
        <div className={styles.headerRow}>
          <Text size={700} weight="semibold">Rules Engine</Text>
          <InfoHint
            title="What this page controls"
            body={
              <>
                This editor manages the backend bank-transaction categorization
                rules (Xero-style conditions). Saving validates the document,
                writes it to the configured rules file, and reloads the
                categorizer in the running API.
              </>
            }
          />
        </div>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Edit transaction mapping conditions without code changes.
        </Caption1>
      </div>

      <Section title="Rules configuration">
        {rules.isLoading && <LoadingState />}
        {rules.error && <ErrorState error={rules.error} />}
        {rules.data && (
          <div style={{ display: "grid", gap: 12 }}>
            <div className={styles.meta}>
              <Field label="Backend">
                <Input readOnly value={rules.data.backend} />
              </Field>
              <Field label="Format">
                <Input readOnly value={rules.data.format} />
              </Field>
              <Field label="Rule count">
                <Input readOnly value={String(rules.data.rule_count)} />
              </Field>
            </div>
            <Field label="Rules file path">
              <Input readOnly value={rules.data.rules_file} />
            </Field>
            <Field label="Rules document (JSON or YAML)">
              <Textarea
                className={styles.editor}
                value={content}
                onChange={(_, d) => setContent(d.value)}
              />
            </Field>
            <div>
              <Button
                appearance="primary"
                icon={<SaveRegular />}
                onClick={() => save.mutate()}
                disabled={save.isPending || !capabilities.canEditRulesEngine}
              >
                {save.isPending ? <Spinner size="tiny" /> : "Save and reload"}
              </Button>
              {!capabilities.canEditRulesEngine && (
                <Caption1 block style={{ marginTop: 6, color: tokens.colorNeutralForeground3 }}>
                  Your current role ({role ?? "unknown"}) is read-only for rules engine changes.
                </Caption1>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section
        title="Parsed rules preview"
        help={{
          title: "Preview semantics",
          body: (
            <>
              This preview is parsed server-side from the same document in the
              editor. Rules are evaluated top to bottom, and the first matching
              rule wins.
            </>
          ),
        }}
      >
        {!rules.data ? (
          <Body1>Load rules to preview parsed output.</Body1>
        ) : rules.data.rules.length === 0 ? (
          <Body1>No parsed rules.</Body1>
        ) : (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Target code</TableHeaderCell>
                <TableHeaderCell>Match</TableHeaderCell>
                <TableHeaderCell>Conditions</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.data.rules.map((r) => (
                <TableRow key={`${r.name}-${r.target_code}`}>
                  <TableCell>{r.name}</TableCell>
                  <TableCell><code>{r.target_code}</code></TableCell>
                  <TableCell>{r.match}</TableCell>
                  <TableCell>
                    {r.conditions
                      .map((c) => `${c.field} ${c.operator} ${c.value}`)
                      .join(" | ")}
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
