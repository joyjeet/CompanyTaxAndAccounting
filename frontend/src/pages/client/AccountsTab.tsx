/**
 * Chart of accounts.
 *
 * Rows are grouped by account type and nested by parent, because a flat
 * code-sorted list gives no sense of structure once a client has more than a
 * handful of accounts.
 *
 * Two deliberate rules drive the affordances here:
 *
 *  * `normal_balance` is not editable. It follows from `account_type`
 *    (assets/expenses are debit, the rest credit), so the backend derives it
 *    and we only display it.
 *  * Remove is offered only when the account has no journal lines and no
 *    sub-accounts; the list response carries both counts. Anything with
 *    history is deactivated instead, which keeps posted entries intact.
 */
import {
  Badge,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Option,
  Switch,
  Text,
  Toast,
  Toaster,
  ToastTitle,
  makeStyles,
  shorthands,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import {
  AddRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  MoreHorizontalRegular,
} from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ApiError } from "../../api/ApiClient";
import { useApi } from "../../api/useApi";
import type { AccountType, CoaOut } from "../../auth/types";
import Section from "../../components/Section";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";

// --------------------------------------------------------------------- //
// Reference data
// --------------------------------------------------------------------- //
/** Statement order, not alphabetical: assets → liabilities → equity → P&L. */
const TYPE_GROUPS: Array<{
  value: AccountType;
  plural: string;
  blurb: string;
  normal: string;
}> = [
  {
    value: "asset",
    plural: "Assets",
    blurb: "What the business owns — cash, receivables, equipment.",
    normal: "debit",
  },
  {
    value: "liability",
    plural: "Liabilities",
    blurb: "What the business owes — payables, loans, accrued tax.",
    normal: "credit",
  },
  {
    value: "equity",
    plural: "Equity",
    blurb: "The owners' residual stake — capital, draws, retained earnings.",
    normal: "credit",
  },
  {
    value: "revenue",
    plural: "Revenue",
    blurb: "What the business earns — sales, fees, other income.",
    normal: "credit",
  },
  {
    value: "expense",
    plural: "Expenses",
    blurb: "What the business spends to operate.",
    normal: "debit",
  },
];

const COLORS: Record<
  AccountType,
  "brand" | "informative" | "success" | "warning" | "danger"
> = {
  asset: "brand",
  liability: "warning",
  equity: "informative",
  revenue: "success",
  expense: "danger",
};

const useStyles = makeStyles({
  group: { marginBottom: "22px" },
  groupHead: {
    display: "flex",
    alignItems: "baseline",
    columnGap: "10px",
    ...shorthands.padding("6px", "0"),
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
    marginBottom: "2px",
  },
  groupTitle: { fontWeight: tokens.fontWeightSemibold },
  row: {
    display: "grid",
    gridTemplateColumns: "minmax(0,1fr) 110px 90px 40px",
    alignItems: "center",
    columnGap: "12px",
    ...shorthands.padding("7px", "8px"),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    ":hover": { backgroundColor: tokens.colorNeutralBackground2 },
  },
  nameCell: { display: "flex", alignItems: "center", columnGap: "8px", minWidth: 0 },
  code: {
    fontFamily: tokens.fontFamilyMonospace,
    color: tokens.colorNeutralForeground2,
  },
  inactive: { opacity: 0.5 },
  twisty: {
    width: "20px",
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    color: tokens.colorNeutralForeground3,
  },
  twistySpacer: { width: "20px" },
  emptyGroup: {
    ...shorthands.padding("8px"),
    color: tokens.colorNeutralForeground3,
  },
  dialogGrid: { display: "grid", rowGap: "12px", marginTop: "8px" },
  derived: { color: tokens.colorNeutralForeground3 },
});

// --------------------------------------------------------------------- //
// Tree assembly
// --------------------------------------------------------------------- //
interface TreeNode {
  account: CoaOut;
  children: TreeNode[];
}

/**
 * Build the parent/child forest for one account type.
 *
 * An account whose parent sits outside this group (possible only if data is
 * inconsistent) is surfaced at the top level rather than silently dropped —
 * an invisible account is worse than a misplaced one.
 */
function buildForest(rows: CoaOut[]): TreeNode[] {
  const byId = new Map(rows.map((a) => [a.id, { account: a, children: [] } as TreeNode]));
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parentId = node.account.parent_account_id;
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => a.account.code.localeCompare(b.account.code));
    nodes.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

function flatten(
  nodes: TreeNode[],
  collapsed: Set<string>,
  depth = 0,
): Array<{ account: CoaOut; depth: number; hasChildren: boolean }> {
  const out: Array<{ account: CoaOut; depth: number; hasChildren: boolean }> = [];
  for (const n of nodes) {
    const hasChildren = n.children.length > 0;
    out.push({ account: n.account, depth, hasChildren });
    if (hasChildren && !collapsed.has(n.account.id)) {
      out.push(...flatten(n.children, collapsed, depth + 1));
    }
  }
  return out;
}

// --------------------------------------------------------------------- //
// Create / edit dialog
// --------------------------------------------------------------------- //
interface DialogState {
  mode: "create" | "edit";
  id?: string;
  code: string;
  name: string;
  accountType: AccountType;
  parentId: string | null;
  isSub: boolean;
}

const BLANK: DialogState = {
  mode: "create",
  code: "",
  name: "",
  accountType: "asset",
  parentId: null,
  isSub: false,
};

export default function AccountsTab({ clientId }: { clientId: string }) {
  const styles = useStyles();
  const api = useApi();
  const qc = useQueryClient();
  const toasterId = useId("accounts-toaster");
  const { dispatchToast } = useToastController(toasterId);

  const [dlg, setDlg] = useState<DialogState | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [showInactive, setShowInactive] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState<CoaOut | null>(null);

  const accounts = useQuery({
    queryKey: ["accounts", clientId],
    queryFn: () => api.listAccounts(clientId),
  });

  const rows = useMemo(() => accounts.data ?? [], [accounts.data]);

  const toast = (msg: string, intent: "success" | "error") =>
    dispatchToast(
      <Toast>
        <ToastTitle>{msg}</ToastTitle>
      </Toast>,
      { intent },
    );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["accounts", clientId] });
    // Other surfaces read the COA too (journal entry form, reports pickers).
    qc.invalidateQueries({ queryKey: ["coa", clientId] });
  };

  // ----- Duplicate-code check, client side so it shows as you type ---- //
  const codeTaken = useMemo(() => {
    if (!dlg) return false;
    const code = dlg.code.trim();
    if (!code) return false;
    return rows.some((a) => a.code === code && a.id !== dlg.id);
  }, [dlg, rows]);

  /**
   * Candidate parents: same type, and never the account itself or anything
   * beneath it. The backend rejects a cycle with 422 regardless, but an
   * option that can only fail should not be offered — and the descendant set
   * has to be walked, not just the direct children, or a grandchild would
   * still appear.
   */
  const parentChoices = useMemo(() => {
    if (!dlg) return [];
    const banned = new Set<string>();
    if (dlg.id) {
      banned.add(dlg.id);
      let grew = true;
      while (grew) {
        grew = false;
        for (const a of rows) {
          if (
            a.parent_account_id &&
            banned.has(a.parent_account_id) &&
            !banned.has(a.id)
          ) {
            banned.add(a.id);
            grew = true;
          }
        }
      }
    }
    return rows
      .filter((a) => a.account_type === dlg.accountType)
      .filter((a) => !banned.has(a.id))
      .sort((a, b) => a.code.localeCompare(b.code));
  }, [dlg, rows]);

  const save = useMutation({
    mutationFn: async () => {
      if (!dlg) return;
      const parent = dlg.isSub ? dlg.parentId : null;
      if (dlg.mode === "create") {
        return api.createAccount(clientId, {
          code: dlg.code.trim(),
          name: dlg.name.trim(),
          account_type: dlg.accountType,
          parent_account_id: parent,
        });
      }
      return api.updateAccount(clientId, dlg.id!, {
        code: dlg.code.trim(),
        name: dlg.name.trim(),
        account_type: dlg.accountType,
        parent_account_id: parent,
      });
    },
    onSuccess: () => {
      toast(dlg?.mode === "create" ? "Account created" : "Account updated", "success");
      setDlg(null);
      refresh();
    },
    onError: (err: unknown) =>
      toast(err instanceof ApiError ? err.message : "Save failed", "error"),
  });

  const setActive = useMutation({
    mutationFn: ({ account, active }: { account: CoaOut; active: boolean }) =>
      api.updateAccount(clientId, account.id, { is_active: active }),
    onSuccess: (_d, v) => {
      toast(v.active ? "Account reactivated" : "Account deactivated", "success");
      refresh();
    },
    onError: (err: unknown) =>
      toast(err instanceof ApiError ? err.message : "Update failed", "error"),
  });

  const remove = useMutation({
    mutationFn: (account: CoaOut) => api.deleteAccount(clientId, account.id),
    onSuccess: () => {
      toast("Account removed", "success");
      setConfirmDelete(null);
      refresh();
    },
    onError: (err: unknown) => {
      // 409 carries the real reason (has journal lines / has sub-accounts).
      toast(err instanceof ApiError ? err.message : "Remove failed", "error");
      setConfirmDelete(null);
    },
  });

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const openCreate = (accountType: AccountType) =>
    setDlg({ ...BLANK, mode: "create", accountType });

  const openSubAccount = (parent: CoaOut) =>
    setDlg({
      ...BLANK,
      mode: "create",
      accountType: parent.account_type,
      parentId: parent.id,
      isSub: true,
    });

  const openEdit = (a: CoaOut) =>
    setDlg({
      mode: "edit",
      id: a.id,
      code: a.code,
      name: a.name,
      accountType: a.account_type,
      parentId: a.parent_account_id,
      isSub: !!a.parent_account_id,
    });

  const visible = showInactive ? rows : rows.filter((a) => a.is_active);

  return (
    <div>
      <Toaster toasterId={toasterId} />
      <Section
        title="Chart of accounts"
        subtitle="Grouped by type. Sub-accounts roll up into their parent."
        help={{
          title: "What is a chart of accounts?",
          body: (
            <>
              The chart of accounts (COA) is the list of every "bucket" the
              business uses to record money. Every journal-entry line must
              reference one account here.
              <br />
              <br />
              Each account has:
              <ul style={{ marginTop: 6, marginBottom: 6, paddingLeft: 18 }}>
                <li>
                  <b>Code</b> — short identifier (e.g. <code>1000</code> for
                  Cash), unique within the client. Convention: 1xxx assets,
                  2xxx liabilities, 3xxx equity, 4xxx revenue, 5xxx+ expenses.
                </li>
                <li>
                  <b>Type</b> — determines which statement it appears on, and
                  fixes its normal balance (assets and expenses are debit, the
                  rest credit). You don't set the normal balance by hand.
                </li>
                <li>
                  <b>Parent</b> — optional. A sub-account must be the same type
                  as its parent.
                </li>
              </ul>
              <b>Removing vs deactivating.</b> An account can only be removed
              while nothing points at it. Once journal lines exist, removing it
              would break their history, so deactivate instead — it disappears
              from pickers but every posted entry stays intact.
            </>
          ),
        }}
        toolbar={
          <div style={{ display: "flex", alignItems: "center", columnGap: 12 }}>
            <Switch
              checked={showInactive}
              onChange={(_, d) => setShowInactive(d.checked)}
              label="Show inactive"
            />
            <Button
              appearance="primary"
              icon={<AddRegular />}
              onClick={() => openCreate("asset")}
            >
              New account
            </Button>
          </div>
        }
      >
        {accounts.isLoading && <LoadingState />}
        {accounts.error && <ErrorState error={accounts.error} />}
        {accounts.data && accounts.data.length === 0 && (
          <EmptyState title="No accounts yet" />
        )}

        {accounts.data &&
          accounts.data.length > 0 &&
          TYPE_GROUPS.map((g) => {
            const groupRows = visible.filter((a) => a.account_type === g.value);
            const forest = buildForest(groupRows);
            const flat = flatten(forest, collapsed);
            return (
              <div key={g.value} className={styles.group}>
                <div className={styles.groupHead}>
                  <Text className={styles.groupTitle}>{g.plural}</Text>
                  <Badge appearance="tint" color={COLORS[g.value]}>
                    {groupRows.length}
                  </Badge>
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    {g.blurb} Normal balance: {g.normal}.
                  </Caption1>
                  <div style={{ marginLeft: "auto" }}>
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<AddRegular />}
                      onClick={() => openCreate(g.value)}
                    >
                      Add
                    </Button>
                  </div>
                </div>

                {flat.length === 0 ? (
                  <Caption1 className={styles.emptyGroup}>
                    No {g.plural.toLowerCase()} yet.
                  </Caption1>
                ) : (
                  flat.map(({ account: a, depth, hasChildren }) => {
                    const removable =
                      a.journal_line_count === 0 && a.child_count === 0;
                    return (
                      <div
                        key={a.id}
                        className={`${styles.row} ${
                          a.is_active ? "" : styles.inactive
                        }`}
                      >
                        <div
                          className={styles.nameCell}
                          style={{ paddingLeft: depth * 22 }}
                        >
                          {hasChildren ? (
                            <span
                              className={styles.twisty}
                              onClick={() => toggle(a.id)}
                              role="button"
                              aria-label={
                                collapsed.has(a.id) ? "Expand" : "Collapse"
                              }
                            >
                              {collapsed.has(a.id) ? (
                                <ChevronRightRegular />
                              ) : (
                                <ChevronDownRegular />
                              )}
                            </span>
                          ) : (
                            <span className={styles.twistySpacer} />
                          )}
                          <span className={styles.code}>{a.code}</span>
                          <Text truncate>{a.name}</Text>
                          {!a.is_active && (
                            <Badge appearance="outline" color="informative">
                              inactive
                            </Badge>
                          )}
                        </div>

                        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                          {a.journal_line_count > 0
                            ? `${a.journal_line_count} line${
                                a.journal_line_count === 1 ? "" : "s"
                              }`
                            : "unused"}
                        </Caption1>

                        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                          {a.normal_balance}
                        </Caption1>

                        <Menu>
                          <MenuTrigger disableButtonEnhancement>
                            <Button
                              size="small"
                              appearance="subtle"
                              icon={<MoreHorizontalRegular />}
                              aria-label={`Actions for ${a.code} ${a.name}`}
                            />
                          </MenuTrigger>
                          <MenuPopover>
                            <MenuList>
                              <MenuItem onClick={() => openEdit(a)}>Edit</MenuItem>
                              <MenuItem onClick={() => openSubAccount(a)}>
                                Add sub-account
                              </MenuItem>
                              <MenuItem
                                onClick={() =>
                                  setActive.mutate({
                                    account: a,
                                    active: !a.is_active,
                                  })
                                }
                              >
                                {a.is_active ? "Deactivate" : "Reactivate"}
                              </MenuItem>
                              <MenuItem
                                disabled={!removable}
                                onClick={() => setConfirmDelete(a)}
                              >
                                {removable
                                  ? "Remove"
                                  : a.child_count > 0
                                    ? "Remove (has sub-accounts)"
                                    : "Remove (has transactions)"}
                              </MenuItem>
                            </MenuList>
                          </MenuPopover>
                        </Menu>
                      </div>
                    );
                  })
                )}
              </div>
            );
          })}
      </Section>

      {/* ---------------- Create / edit ---------------- */}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {dlg?.mode === "edit" ? "Edit account" : "New account"}
            </DialogTitle>
            <DialogContent>
              {dlg && (
                <div className={styles.dialogGrid}>
                  <Field label="Account type" required>
                    <Dropdown
                      value={
                        TYPE_GROUPS.find((t) => t.value === dlg.accountType)
                          ?.plural ?? ""
                      }
                      selectedOptions={[dlg.accountType]}
                      onOptionSelect={(_, d) =>
                        d.optionValue &&
                        setDlg({
                          ...dlg,
                          accountType: d.optionValue as AccountType,
                          // Parent must share the type, so a type change
                          // invalidates any parent already picked.
                          parentId: null,
                        })
                      }
                    >
                      {TYPE_GROUPS.map((t) => (
                        <Option key={t.value} value={t.value} text={t.plural}>
                          {t.plural}
                        </Option>
                      ))}
                    </Dropdown>
                  </Field>

                  <Caption1 className={styles.derived}>
                    Normal balance:{" "}
                    <b>
                      {TYPE_GROUPS.find((t) => t.value === dlg.accountType)?.normal}
                    </b>{" "}
                    — set automatically from the type.
                  </Caption1>

                  <Field label="Account name" required>
                    <Input
                      value={dlg.name}
                      onChange={(_, d) => setDlg({ ...dlg, name: d.value })}
                      placeholder="Cash"
                    />
                  </Field>

                  <Switch
                    checked={dlg.isSub}
                    onChange={(_, d) =>
                      setDlg({
                        ...dlg,
                        isSub: d.checked,
                        parentId: d.checked ? dlg.parentId : null,
                      })
                    }
                    label="Make this a sub-account"
                  />

                  {dlg.isSub && (
                    <Field
                      label="Parent account"
                      required
                      hint="Only accounts of the same type can be a parent."
                      validationState={
                        dlg.isSub && !dlg.parentId ? "warning" : "none"
                      }
                      validationMessage={
                        dlg.isSub && !dlg.parentId
                          ? "Pick a parent, or turn off sub-account."
                          : undefined
                      }
                    >
                      <Dropdown
                        value={
                          parentChoices.find((p) => p.id === dlg.parentId)
                            ? `${
                                parentChoices.find((p) => p.id === dlg.parentId)!
                                  .code
                              } — ${
                                parentChoices.find((p) => p.id === dlg.parentId)!
                                  .name
                              }`
                            : ""
                        }
                        selectedOptions={dlg.parentId ? [dlg.parentId] : []}
                        onOptionSelect={(_, d) =>
                          setDlg({ ...dlg, parentId: d.optionValue ?? null })
                        }
                      >
                        {parentChoices.length === 0 && (
                          <Option value="" disabled text="">
                            No other {dlg.accountType} accounts yet
                          </Option>
                        )}
                        {parentChoices.map((p) => (
                          <Option
                            key={p.id}
                            value={p.id}
                            text={`${p.code} — ${p.name}`}
                          >
                            {p.code} — {p.name}
                          </Option>
                        ))}
                      </Dropdown>
                    </Field>
                  )}

                  <Field
                    label="Account code"
                    required
                    hint="Unique within this client."
                    validationState={codeTaken ? "error" : "none"}
                    validationMessage={
                      codeTaken
                        ? `Code ${dlg.code.trim()} is already used by another account.`
                        : undefined
                    }
                  >
                    <Input
                      value={dlg.code}
                      onChange={(_, d) => setDlg({ ...dlg, code: d.value })}
                      placeholder="1000"
                    />
                  </Field>
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setDlg(null)}>
                Cancel
              </Button>
              <Button
                appearance="primary"
                disabled={
                  !dlg ||
                  !dlg.code.trim() ||
                  !dlg.name.trim() ||
                  codeTaken ||
                  (dlg.isSub && !dlg.parentId) ||
                  save.isPending
                }
                onClick={() => save.mutate()}
              >
                Save
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* ---------------- Confirm remove ---------------- */}
      <Dialog
        open={!!confirmDelete}
        onOpenChange={(_, d) => !d.open && setConfirmDelete(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Remove account?</DialogTitle>
            <DialogContent>
              <MessageBar intent="warning">
                <MessageBarBody>
                  <b>
                    {confirmDelete?.code} {confirmDelete?.name}
                  </b>{" "}
                  will be permanently removed. This cannot be undone.
                </MessageBarBody>
              </MessageBar>
              <Caption1
                style={{
                  display: "block",
                  marginTop: 10,
                  color: tokens.colorNeutralForeground3,
                }}
              >
                Nothing currently posts to this account. If you might need it
                again, deactivate it instead.
              </Caption1>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </Button>
              <Button
                appearance="primary"
                disabled={remove.isPending}
                onClick={() => confirmDelete && remove.mutate(confirmDelete)}
              >
                Remove
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
