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
});

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

  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients() });
  const create = useMutation({
    mutationFn: () =>
      api.createClient({ name: name.trim(), external_code: code.trim() || null }),
    onSuccess: (c) => {
      dispatchToast(
        <Toast>
          <ToastTitle>Client created</ToastTitle>
          <ToastBody>{c.name}</ToastBody>
        </Toast>,
        { intent: "success" },
      );
      setOpen(false);
      setName("");
      setCode("");
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
                  <Field label="External code" hint="Optional accounting-system ID">
                    <Input
                      value={code}
                      onChange={(_, d) => setCode(d.value)}
                      placeholder="ACME-001"
                    />
                  </Field>
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
