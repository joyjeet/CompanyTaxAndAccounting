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
  BookContacts24Regular,
  ChartMultipleRegular,
  ClipboardTaskListLtr24Regular,
  Document24Regular,
  DocumentBulletList24Regular,
  Home24Regular,
  PersonCircle24Regular,
  TaskListSquareLtr24Regular,
  Wrench24Regular,
} from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
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
  { to: "/rules-engine", label: "Rules engine", icon: <Wrench24Regular /> },
  { to: "/artifacts", label: "Artifacts", icon: <DocumentBulletList24Regular /> },
  { to: "/tax/forms", label: "Tax forms", icon: <TaskListSquareLtr24Regular /> },
];

const PORTAL_NAV: NavItem[] = [
  { to: "/portal", label: "Overview", icon: <Home24Regular />, end: true },
  { to: "/portal/documents", label: "My documents", icon: <Document24Regular /> },
  { to: "/portal/reports", label: "My reports", icon: <ChartMultipleRegular /> },
  { to: "/portal/profile", label: "My profile", icon: <PersonCircle24Regular /> },
];

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
  const { identity, client, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const api = useApi();

  const isFirm = identity?.role === "firm_staff";
  const nav = isFirm ? FIRM_NAV : PORTAL_NAV;

  // Drives the Review-queue badge. Shares its cache key with the Dashboard,
  // which already fetches exactly this, so it costs no extra request.
  const pending = useQuery({
    queryKey: ["drafts", "pending"],
    queryFn: () => api.listDrafts(true),
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
                  await client.logout();
                  navigate("/login", { replace: true });
                }}
              >
                Sign out
              </Button>
            </>
          ) : null}
        </div>
      </header>

      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          {isFirm ? "Workspace" : "Portal"}
        </div>
        {nav.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem
            }
          >
            {n.icon}
            <span>{n.label}</span>
            {/* How much work is waiting is the one thing worth knowing
                without clicking through. */}
            {n.to === "/review" && pendingCount > 0 && (
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
        ))}
      </aside>

      <main className={styles.content}>{children}</main>
    </div>
  );
}
