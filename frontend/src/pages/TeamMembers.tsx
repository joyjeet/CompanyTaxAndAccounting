import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  Option,
  Spinner,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useApi } from "../api/useApi";
import { useEffectiveIdentity } from "../auth/TenantContext";
import { roleDisplayName } from "../auth/firmRole";
import type { MembershipStatus, StaffRole } from "../auth/types";
import Section from "../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

const ROLE_OPTIONS: StaffRole[] = [
  "firm_owner",
  "firm_admin",
  "manager",
  "staff",
  "read_only",
  "client_portal",
];

const STATUS_OPTIONS: MembershipStatus[] = ["active", "disabled"];

function roleLabel(role: StaffRole): string {
  return roleDisplayName(role);
}

export default function TeamMembers() {
  const api = useApi();
  const identity = useEffectiveIdentity();
  const qc = useQueryClient();
  const toasterId = useId("team-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<StaffRole>("staff");
  const [inviteDays, setInviteDays] = useState("7");
  const [acceptToken, setAcceptToken] = useState("");
  const [savedInviteToken, setSavedInviteToken] = useState<string | null>(null);

  const summary = useQuery({
    queryKey: ["team", "summary"],
    queryFn: () => api.listTeamMembers(),
  });

  const currentMembership = useMemo(() => {
    if (!identity || !summary.data?.members) return null;
    return summary.data.members.find((m) => m.subject === identity.sub) ?? null;
  }, [identity, summary.data?.members]);

  const isAdmin = currentMembership
    ? currentMembership.role === "firm_owner" || currentMembership.role === "firm_admin"
    : false;

  const invalidateTeam = () => {
    qc.invalidateQueries({ queryKey: ["team", "summary"] });
  };

  const createInvite = useMutation({
    mutationFn: async () => {
      const days = Math.max(1, Math.min(30, Number.parseInt(inviteDays || "7", 10) || 7));
      return api.createTeamInvite({
        email: inviteEmail.trim(),
        role: inviteRole,
        expires_in_days: days,
      });
    },
    onSuccess: (data) => {
      setSavedInviteToken(data.invite_token);
      setInviteEmail("");
      dispatchToast(
        <Toast>
          <ToastTitle>Invite created.</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      invalidateTeam();
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

  const acceptInvite = useMutation({
    mutationFn: async () => api.acceptTeamInvite(acceptToken.trim()),
    onSuccess: () => {
      setAcceptToken("");
      dispatchToast(
        <Toast>
          <ToastTitle>Invite accepted and membership activated.</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      invalidateTeam();
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

  const cancelInvite = useMutation({
    mutationFn: async (inviteId: string) => api.cancelTeamInvite(inviteId),
    onSuccess: () => {
      dispatchToast(
        <Toast>
          <ToastTitle>Invite canceled.</ToastTitle>
        </Toast>,
        { intent: "success" },
      );
      invalidateTeam();
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

  const updateRole = useMutation({
    mutationFn: async ({ memberId, role }: { memberId: string; role: StaffRole }) =>
      api.updateTeamMemberRole(memberId, role),
    onSuccess: () => {
      invalidateTeam();
    },
  });

  const updateStatus = useMutation({
    mutationFn: async ({ memberId, status }: { memberId: string; status: MembershipStatus }) =>
      api.updateTeamMemberStatus(memberId, status),
    onSuccess: () => {
      invalidateTeam();
    },
  });

  if (summary.isLoading) return <LoadingState label="Loading team membership..." />;
  if (summary.error) return <ErrorState error={summary.error} />;

  const members = summary.data?.members ?? [];
  const invites = summary.data?.invites ?? [];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Toaster toasterId={toasterId} />

      <div>
        <Text size={700} weight="semibold">Team access</Text>
        <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
          Manage firm roles, disabled access, and invite links.
        </Caption1>
      </div>

      <Section
        title="My membership"
        subtitle="Your effective team role for this firm"
      >
        {!currentMembership ? (
          <EmptyState title="No membership found" description="Use an invite token to join this firm." />
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Badge appearance="filled" color="brand">{roleLabel(currentMembership.role)}</Badge>
            <Badge appearance="tint" color={currentMembership.status === "active" ? "success" : "danger"}>
              {currentMembership.status}
            </Badge>
            <Body1>{currentMembership.subject}</Body1>
          </div>
        )}
      </Section>

      <Section
        title="Accept invite"
        subtitle="Paste an invite token to join this firm with the invited role"
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8 }}>
          <Field label="Invite token" required>
            <Input value={acceptToken} onChange={(_, d) => setAcceptToken(d.value)} />
          </Field>
          <div style={{ alignSelf: "end" }}>
            <Button
              appearance="primary"
              onClick={() => acceptInvite.mutate()}
              disabled={acceptInvite.isPending || acceptToken.trim().length < 20}
            >
              {acceptInvite.isPending ? <Spinner size="tiny" /> : "Accept"}
            </Button>
          </div>
        </div>
      </Section>

      <Section
        title="Invite staff"
        subtitle="Only firm owner/admin can create and cancel invites"
      >
        {!isAdmin ? (
          <Body1>You can view team access but cannot create invites with your current role.</Body1>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 220px 140px auto", gap: 8 }}>
              <Field label="Email" required>
                <Input
                  type="email"
                  value={inviteEmail}
                  onChange={(_, d) => setInviteEmail(d.value)}
                  placeholder="staff@firm.com"
                />
              </Field>
              <Field label="Role" required>
                <Dropdown
                  value={roleLabel(inviteRole)}
                  selectedOptions={[inviteRole]}
                  onOptionSelect={(_, d) => {
                    if (d.optionValue) setInviteRole(d.optionValue as StaffRole);
                  }}
                >
                  {ROLE_OPTIONS.map((r) => (
                    <Option key={r} value={r} text={roleLabel(r)}>
                      {roleLabel(r)}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label="Expires (days)">
                <Input
                  value={inviteDays}
                  onChange={(_, d) => setInviteDays(d.value)}
                  placeholder="7"
                />
              </Field>
              <div style={{ alignSelf: "end" }}>
                <Button
                  appearance="primary"
                  onClick={() => createInvite.mutate()}
                  disabled={createInvite.isPending || inviteEmail.trim().length < 3}
                >
                  {createInvite.isPending ? <Spinner size="tiny" /> : "Create invite"}
                </Button>
              </div>
            </div>
            {savedInviteToken && (
              <Field label="New invite token (copy and send securely)">
                <Input readOnly value={savedInviteToken} />
              </Field>
            )}
          </div>
        )}
      </Section>

      <Section title="Members" subtitle={`Total members: ${members.length}`}>
        {members.length === 0 ? (
          <EmptyState title="No members" description="Members appear here after first sign-in or invite acceptance." />
        ) : (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Subject</TableHeaderCell>
                <TableHeaderCell>Email</TableHeaderCell>
                <TableHeaderCell>Role</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((m) => (
                <TableRow key={m.id}>
                  <TableCell>{m.subject}</TableCell>
                  <TableCell>{m.email ?? "-"}</TableCell>
                  <TableCell>
                    {isAdmin ? (
                      <Dropdown
                        value={roleLabel(m.role)}
                        selectedOptions={[m.role]}
                        onOptionSelect={(_, d) => {
                          if (!d.optionValue) return;
                          void updateRole.mutate({ memberId: m.id, role: d.optionValue as StaffRole });
                        }}
                        disabled={updateRole.isPending}
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <Option key={r} value={r} text={roleLabel(r)}>
                            {roleLabel(r)}
                          </Option>
                        ))}
                      </Dropdown>
                    ) : (
                      roleLabel(m.role)
                    )}
                  </TableCell>
                  <TableCell>
                    {isAdmin ? (
                      <Dropdown
                        value={m.status}
                        selectedOptions={[m.status]}
                        onOptionSelect={(_, d) => {
                          if (!d.optionValue) return;
                          void updateStatus.mutate({
                            memberId: m.id,
                            status: d.optionValue as MembershipStatus,
                          });
                        }}
                        disabled={updateStatus.isPending}
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <Option key={s} value={s} text={s}>
                            {s}
                          </Option>
                        ))}
                      </Dropdown>
                    ) : (
                      <Badge appearance="tint" color={m.status === "active" ? "success" : "danger"}>
                        {m.status}
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      <Section title="Invites" subtitle={`Total invites: ${invites.length}`}>
        {invites.length === 0 ? (
          <EmptyState title="No invites" description="Create an invite to onboard staff." />
        ) : (
          <Table size="small">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Email</TableHeaderCell>
                <TableHeaderCell>Role</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Expires</TableHeaderCell>
                <TableHeaderCell>Actions</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell>{inv.email}</TableCell>
                  <TableCell>{roleLabel(inv.role)}</TableCell>
                  <TableCell>{inv.status}</TableCell>
                  <TableCell>{new Date(inv.expires_at).toLocaleString()}</TableCell>
                  <TableCell>
                    {isAdmin && inv.status === "pending" ? (
                      <Button
                        size="small"
                        appearance="secondary"
                        onClick={() => cancelInvite.mutate(inv.id)}
                        disabled={cancelInvite.isPending}
                      >
                        Cancel
                      </Button>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      <Section
        title="Role permissions"
        subtitle="UI and API behavior by firm role"
      >
        <Table size="small">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Role</TableHeaderCell>
              <TableHeaderCell>Create clients</TableHeaderCell>
              <TableHeaderCell>Edit rules engine</TableHeaderCell>
              <TableHeaderCell>Manage team invites/roles</TableHeaderCell>
              <TableHeaderCell>Promote drafts</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ROLE_OPTIONS.map((r) => {
              const canCreate = r === "firm_owner" || r === "firm_admin" || r === "manager" || r === "staff";
              const canRules = r === "firm_owner" || r === "firm_admin";
              const canTeam = r === "firm_owner" || r === "firm_admin";
              const canPromote = r === "firm_owner" || r === "firm_admin" || r === "manager" || r === "staff";
              return (
                <TableRow key={`matrix-${r}`}>
                  <TableCell>{roleLabel(r)}</TableCell>
                  <TableCell>{canCreate ? "Yes" : "No"}</TableCell>
                  <TableCell>{canRules ? "Yes" : "No"}</TableCell>
                  <TableCell>{canTeam ? "Yes" : "No"}</TableCell>
                  <TableCell>{canPromote ? "Yes" : "No"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Section>
    </div>
  );
}
