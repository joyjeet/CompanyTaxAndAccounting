import {
  Avatar,
  Badge,
  Button,
  Caption1,
  makeStyles,
  shorthands,
  Text,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowExitRegular,
  ArrowLeft24Regular,
  BookContacts24Regular,
  BuildingBank24Regular,
  Calendar24Regular,
  ChartMultipleRegular,
  ClipboardTaskListLtr24Regular,
  DataUsage24Regular,
  Document24Regular,
  DocumentBulletList24Regular,
  Home24Regular,
  PersonCircle24Regular,
  PeopleTeam24Regular,
  ReceiptMoney24Regular,
  TaskListSquareLtr24Regular,
  Wrench24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useEffectiveIdentity } from "../auth/TenantContext";
import { shortId } from "../lib/format";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
}

const FIRM_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <Home24Regular />, end: true },
  { to: "/clients", label: "Clients", icon: <BookContacts24Regular /> },
  { to: "/review", label: "Review queue", icon: <ClipboardTaskListLtr24Regular /> },
  { to: "/bank-transactions", label: "Bank transactions", icon: <DataUsage24Regular /> },
  { to: "/rules-engine", label: "Rules engine", icon: <Wrench24Regular /> },
  { to: "/team", label: "Team access", icon: <PeopleTeam24Regular /> },
  { to: "/artifacts", label: "Artifacts", icon: <DocumentBulletList24Regular /> },
  { to: "/tax/forms", label: "Tax forms", icon: <TaskListSquareLtr24Regular /> },
];

const PORTAL_NAV: NavItem[] = [
  { to: "/portal", label: "Overview", icon: <Home24Regular />, end: true },
  { to: "/portal/documents", label: "My documents", icon: <Document24Regular /> },
  { to: "/portal/reports", label: "My reports", icon: <ChartMultipleRegular /> },
  { to: "/portal/profile", label: "My profile", icon: <PersonCircle24Regular /> },
];

/** Matches `/clients/<uuid>` and anything nested under it. */
const CLIENT_PATH = /^\/clients\/([0-9a-f-]{36})(?:\/|$)/i;

/**
 * The client id the user is currently working inside, or null at firm level.
 *
 * Firm staff can see every client in the firm, which is correct for a
 * CPA — but once they open a client they are, in effect, standing in that
 * client's books, and firm-wide lists are noise at best and confusing at
 * worst. Two ways to be "inside" a client: the URL path (the client
 * workspace) or an explicit `?client=` filter on a firm-wide page.
 */
function activeClientId(pathname: string, search: string): string | null {
  const m = CLIENT_PATH.exec(pathname);
  if (m) return m[1];
  return new URLSearchParams(search).get("client");
}

function clientNav(id: string): NavItem[] {
  return [
    { to: `/clients/${id}/overview`, label: "Overview", icon: <Home24Regular /> },
    { to: `/clients/${id}/profile`, label: "Profile", icon: <PersonCircle24Regular /> },
    { to: `/clients/${id}/periods`, label: "Periods", icon: <Calendar24Regular /> },
    { to: `/clients/${id}/accounts`, label: "Chart of accounts", icon: <BuildingBank24Regular /> },
    { to: `/clients/${id}/documents`, label: "Documents", icon: <Document24Regular /> },
    { to: `/review?client=${id}`, label: "Review queue", icon: <ClipboardTaskListLtr24Regular /> },
    { to: `/bank-transactions?client=${id}`, label: "Bank transactions", icon: <DataUsage24Regular /> },
    { to: `/clients/${id}/journal`, label: "Journal entries", icon: <ReceiptMoney24Regular /> },
    { to: `/clients/${id}/statements`, label: "Statements", icon: <ChartMultipleRegular /> },
    { to: `/clients/${id}/reports`, label: "Reports", icon: <DocumentBulletList24Regular /> },
    { to: `/clients/${id}/tax`, label: "Tax", icon: <TaskListSquareLtr24Regular /> },
    { to: `/clients/${id}/artifacts`, label: "Artifacts", icon: <DocumentBulletList24Regular /> },
  ];
}

const useStyles = makeStyles({
  root: {
    display: "grid",
    gridTemplateColumns: "260px 1fr",
    gridTemplateRows: "56px 1fr",
    minHeight: "100vh",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  topbar: {
    gridColumn: "1 / 3",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    ...shorthands.padding("0", "20px"),
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
    boxShadow: tokens.shadow4,
    zIndex: 10,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
  },
  brandMark: {
    width: "32px",
    height: "32px",
    borderRadius: "8px",
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    display: "grid",
    placeItems: "center",
    fontWeight: tokens.fontWeightBold,
  },
  topbarRight: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
  },
  identity: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    lineHeight: tokens.lineHeightBase200,
  },
  sidebar: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.borderRight("1px", "solid", tokens.colorNeutralStroke2),
    ...shorthands.padding("16px", "12px"),
    display: "flex",
    flexDirection: "column",
    rowGap: "4px",
    overflowY: "auto",
  },
  navItem: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
    ...shorthands.padding("10px", "12px"),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    color: tokens.colorNeutralForeground2,
    textDecoration: "none",
    fontWeight: tokens.fontWeightRegular,
    fontSize: tokens.fontSizeBase300,
    cursor: "pointer",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
      color: tokens.colorNeutralForeground1,
    },
  },
  navItemActive: {
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
    ":hover": {
      backgroundColor: tokens.colorBrandBackground2Hover,
      color: tokens.colorBrandForeground1,
    },
  },
  sidebarHeader: {
    ...shorthands.padding("8px", "12px", "4px", "12px"),
    color: tokens.colorNeutralForeground3,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
  },
  content: {
    ...shorthands.padding("24px", "32px"),
    overflowY: "auto",
  },
});

export default function AppShell({ children }: { children: ReactNode }) {
  const styles = useStyles();
  const api = useApi();
  const { isAuthenticated, signOut } = useAuth();
  const identity = useEffectiveIdentity();
  const navigate = useNavigate();
  const location = useLocation();

  const isFirm = identity?.role === "firm_staff";
  const inClient = isFirm
    ? activeClientId(location.pathname, location.search)
    : null;
  const nav = !isFirm ? PORTAL_NAV : inClient ? clientNav(inClient) : FIRM_NAV;

  // Only to label the sidebar. The client list is already cached by the
  // Clients page, so this is usually free.
  const activeClient = useQuery({
    queryKey: ["client", inClient],
    queryFn: () => api.getClient(inClient as string),
    enabled: Boolean(inClient),
    staleTime: 60_000,
  });

  const team = useQuery({
    queryKey: ["team", "summary", "shell"],
    queryFn: () => api.listTeamMembers(),
    enabled: Boolean(isFirm),
    staleTime: 60_000,
  });
  const effectiveRole = isFirm && identity && team.data
    ? team.data.members.find((m) => m.subject === identity.sub)?.role ?? null
    : null;

  // Drives the Review-queue badge. Shares its cache key with the Dashboard,
  // which already fetches exactly this, so it costs no extra request. Inside
  // a client workspace it counts only that client's work.
  const pending = useQuery({
    queryKey: ["drafts", "pending", inClient ?? "all"],
    queryFn: () => api.listDrafts(true, inClient ?? undefined),
    enabled: isFirm && isAuthenticated,
  });
  const pendingCount = pending.data?.length ?? 0;

  return (
    <div className={styles.root}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <div className={styles.brandMark}>C</div>
          <div>
            <Text weight="semibold">CTAA</Text>
            <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
              Company Tax &amp; Accounting
            </Caption1>
          </div>
        </div>
        <div className={styles.topbarRight}>
          {isAuthenticated && identity ? (
            <>
              <Badge appearance="tint" color={isFirm ? "brand" : "informative"}>
                {isFirm ? "Firm staff" : "Client portal"}
              </Badge>
              {effectiveRole && (
                <Badge appearance="outline" color="brand">
                  {effectiveRole.replaceAll("_", " ")}
                </Badge>
              )}
              <div className={styles.identity}>
                <Text size={200} weight="semibold">
                  {identity.sub}
                </Text>
                <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                  Firm <code>{shortId(identity.firmId)}</code>
                  {identity.clientId && (
                    <>
                      {" · Client "}
                      <code>{shortId(identity.clientId)}</code>
                    </>
                  )}
                </Caption1>
              </div>
              <Avatar icon={<PersonCircle24Regular />} color="colorful" name={identity.sub} />
              <Button
                appearance="subtle"
                icon={<ArrowExitRegular />}
                onClick={async () => {
                  // Via signOut (not client.logout) so the stored tenant
                  // selection is dropped — otherwise the next person to sign
                  // in on this tab inherits the previous workspace hint.
                  await signOut();
                  navigate("/welcome", { replace: true });
                }}
              >
                Sign out
              </Button>
            </>
          ) : null}
        </div>
      </header>

      <aside className={styles.sidebar}>
        {inClient ? (
          <>
            <NavLink to="/clients" className={styles.navItem}>
              <ArrowLeft24Regular />
              <span>All clients</span>
            </NavLink>
            <div className={styles.sidebarHeader}>
              {activeClient.data?.name ?? "Client"}
            </div>
          </>
        ) : (
          <div className={styles.sidebarHeader}>
            {isFirm ? "Workspace" : "Portal"}
          </div>
        )}
        {nav.map((n) => {
          const navPath = n.to.split("?")[0];
          // NavLink matches on pathname only, so the `?client=` links
          // highlight correctly on their own. The one gap is `/clients/:id`
          // with no tab, which renders Overview.
          const forceActive =
            inClient !== null &&
            navPath === `/clients/${inClient}/overview` &&
            location.pathname === `/clients/${inClient}`;
          return (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                isActive || forceActive
                  ? `${styles.navItem} ${styles.navItemActive}`
                  : styles.navItem
              }
            >
              {n.icon}
              <span>{n.label}</span>
              {/* How much work is waiting is the one thing worth knowing
                  without clicking through. */}
              {navPath === "/review" && pendingCount > 0 && (
                <Badge
                  appearance="filled"
                  color="danger"
                  size="small"
                  style={{ marginLeft: "auto" }}
                >
                  {pendingCount}
                </Badge>
              )}
            </NavLink>
          );
        })}
      </aside>

      <main className={styles.content}>{children}</main>
    </div>
  );
}
