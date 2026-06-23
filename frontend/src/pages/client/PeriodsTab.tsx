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
  Field,
  Input,
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
import { fmtDate, shortId } from "../../lib/format";

export default function PeriodsTab({ clientId }: { clientId: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("periods-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const periods = useQuery({
    queryKey: ["periods", clientId],
    queryFn: () => api.listPeriods(clientId),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createPeriod(clientId, { name: name.trim(), start_date: start, end_date: end }),
    onSuccess: () => {
      dispatchToast(<Toast><ToastTitle>Period created</ToastTitle></Toast>, { intent: "success" });
      setOpen(false);
      setName(""); setStart(""); setEnd("");
      qc.invalidateQueries({ queryKey: ["periods", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const lockMut = useMutation({
    mutationFn: (periodId: string) => api.lockPeriod(clientId, periodId),
    onSuccess: () => {
      dispatchToast(
        <Toast><ToastTitle>Period locked. Reports are now visible to the client portal.</ToastTitle></Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["periods", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  const unlockMut = useMutation({
    mutationFn: (periodId: string) => api.unlockPeriod(clientId, periodId),
    onSuccess: () => {
      dispatchToast(
        <Toast><ToastTitle>Period unlocked.</ToastTitle></Toast>,
        { intent: "success" },
      );
      qc.invalidateQueries({ queryKey: ["periods", clientId] });
    },
    onError: (err: Error) => {
      dispatchToast(<Toast><ToastTitle>{err.message}</ToastTitle></Toast>, { intent: "error" });
    },
  });

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <Section
        title="Accounting periods"
        subtitle="Closed periods are locked against new postings."
        help={{
          title: "What is a period?",
          body: (
            <>
              A <b>period</b> is a window of time the books are kept in —
              typically a month, quarter, or fiscal year. Journal entries
              are dated within a period and statements are generated
              "as of" a period.
              <br /><br />
              When you <b>lock</b> a period (e.g. after closing the
              month), the system rejects any new postings dated inside
              it. This is how you prevent backdated changes once books
              are closed.
              <br /><br />
              Tip: create the current fiscal year as your first period
              and add monthly periods inside it as you go.
            </>
          ),
        }}
        toolbar={
          <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="primary" icon={<AddRegular />}>New period</Button>
            </DialogTrigger>
            <DialogSurface>
              <DialogBody>
                <DialogTitle>Create accounting period</DialogTitle>
                <DialogContent>
                  <div style={{ display: "grid", rowGap: 12, marginTop: 8 }}>
                    <Field label="Name" required>
                      <Input value={name} onChange={(_, d) => setName(d.value)} placeholder="2026" />
                    </Field>
                    <Field label="Start date" required>
                      <Input type="date" value={start} onChange={(_, d) => setStart(d.value)} />
                    </Field>
                    <Field label="End date" required>
                      <Input type="date" value={end} onChange={(_, d) => setEnd(d.value)} />
                    </Field>
                  </div>
                </DialogContent>
                <DialogActions>
                  <DialogTrigger disableButtonEnhancement>
                    <Button appearance="secondary">Cancel</Button>
                  </DialogTrigger>
                  <Button
                    appearance="primary"
                    disabled={!name || !start || !end || create.isPending}
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
        {periods.isLoading && <LoadingState />}
        {periods.error && <ErrorState error={periods.error} />}
        {periods.data && periods.data.length === 0 && (
          <EmptyState title="No periods yet" description="Create one to start posting entries." />
        )}
        {periods.data && periods.data.length > 0 && (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Start</TableHeaderCell>
                <TableHeaderCell>End</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>ID</TableHeaderCell>
                <TableHeaderCell>Action</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periods.data.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>{p.name}</TableCell>
                  <TableCell>{fmtDate(p.start_date)}</TableCell>
                  <TableCell>{fmtDate(p.end_date)}</TableCell>
                  <TableCell>
                    <Badge appearance="tint" color={p.is_locked ? "danger" : "success"}>
                      {p.is_locked ? "locked" : "open"}
                    </Badge>
                  </TableCell>
                  <TableCell><code>{shortId(p.id)}</code></TableCell>
                  <TableCell>
                    {p.is_locked ? (
                      <Button
                        size="small"
                        appearance="subtle"
                        disabled={unlockMut.isPending}
                        onClick={() => unlockMut.mutate(p.id)}
                      >
                        Unlock
                      </Button>
                    ) : (
                      <Button
                        size="small"
                        appearance="primary"
                        disabled={lockMut.isPending}
                        onClick={() => lockMut.mutate(p.id)}
                      >
                        Lock (finalize)
                      </Button>
                    )}
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
