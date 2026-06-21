import {
  Badge,
  Button,
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
  Option,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Toast,
  Toaster,
  ToastTitle,
  useId,
  useToastController,
} from "@fluentui/react-components";
import { AddRegular } from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../../api/useApi";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";

const ACCOUNT_TYPES = ["asset", "liability", "equity", "revenue", "expense"];
const NORMAL_BALANCES = ["debit", "credit"];

const COLORS: Record<string, "brand" | "informative" | "success" | "warning" | "danger"> = {
  asset: "brand",
  liability: "warning",
  equity: "informative",
  revenue: "success",
  expense: "danger",
};

export default function AccountsTab({ clientId }: { clientId: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("accounts-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("asset");
  const [normal, setNormal] = useState("debit");

  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createAccount(clientId, {
        code: code.trim(),
        name: name.trim(),
        account_type: type,
        normal_balance: normal,
      }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Account created</ToastTitle></Toast>, { intent: "success" });
      setOpen(false);
      setCode(""); setName("");
      qc.invalidateQueries({ queryKey: ["accounts", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <Section
        title="Chart of accounts"
        subtitle="Define the accounts used by journal entries and statements."
        toolbar={
          <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="primary" icon={<AddRegular />}>New account</Button>
            </DialogTrigger>
            <DialogSurface>
              <DialogBody>
                <DialogTitle>Create account</DialogTitle>
                <DialogContent>
                  <div style={{ display: "grid", rowGap: 12, marginTop: 8 }}>
                    <Field label="Code" required hint="Short numeric or alphanumeric identifier">
                      <Input value={code} onChange={(_, d) => setCode(d.value)} placeholder="1000" />
                    </Field>
                    <Field label="Name" required>
                      <Input value={name} onChange={(_, d) => setName(d.value)} placeholder="Cash" />
                    </Field>
                    <Field label="Account type" required>
                      <Dropdown
                        value={type}
                        selectedOptions={[type]}
                        onOptionSelect={(_, d) => d.optionValue && setType(d.optionValue)}
                      >
                        {ACCOUNT_TYPES.map((t) => (
                          <Option key={t} value={t}>{t}</Option>
                        ))}
                      </Dropdown>
                    </Field>
                    <Field label="Normal balance" required>
                      <Dropdown
                        value={normal}
                        selectedOptions={[normal]}
                        onOptionSelect={(_, d) => d.optionValue && setNormal(d.optionValue)}
                      >
                        {NORMAL_BALANCES.map((t) => (
                          <Option key={t} value={t}>{t}</Option>
                        ))}
                      </Dropdown>
                    </Field>
                  </div>
                </DialogContent>
                <DialogActions>
                  <DialogTrigger disableButtonEnhancement>
                    <Button appearance="secondary">Cancel</Button>
                  </DialogTrigger>
                  <Button
                    appearance="primary"
                    disabled={!code || !name || create.isPending}
                    onClick={() => create.mutate()}
                  >
                    Create
                  </Button>
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>
        }
      >
        {accounts.isLoading && <LoadingState />}
        {accounts.error && <ErrorState error={accounts.error} />}
        {accounts.data && accounts.data.length === 0 && (
          <EmptyState title="No accounts yet" />
        )}
        {accounts.data && accounts.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Code</TableHeaderCell>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Type</TableHeaderCell>
                <TableHeaderCell>Normal</TableHeaderCell>
                <TableHeaderCell>Active</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.data.map((a) => (
                <TableRow key={a.id}>
                  <TableCell><code>{a.code}</code></TableCell>
                  <TableCell>{a.name}</TableCell>
                  <TableCell>
                    <Badge appearance="tint" color={COLORS[a.account_type] ?? "informative"}>
                      {a.account_type}
                    </Badge>
                  </TableCell>
                  <TableCell>{a.normal_balance}</TableCell>
                  <TableCell>{a.is_active ? "yes" : "no"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
