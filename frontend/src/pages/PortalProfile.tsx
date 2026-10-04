/**
 * "My profile" — the portal-side page for clients to maintain their own
 * business identity & contact info. Hard-locked to the client_id baked
 * into their JWT (server-side RLS enforces it; the route picks it up
 * from useAuth).
 */
import { Text, makeStyles, tokens } from "@fluentui/react-components";

import ClientProfileForm from "../components/ClientProfileForm";
import { useEffectiveIdentity } from "../auth/TenantContext";

const useStyles = makeStyles({
  page: {
    display: "flex",
    flexDirection: "column",
    rowGap: "16px",
    maxWidth: "960px",
  },
  title: {
    fontSize: tokens.fontSizeHero700,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
});

export default function PortalProfile() {
  const styles = useStyles();
  const identity = useEffectiveIdentity();
  const clientId = identity?.clientId ?? "";

  if (!clientId) {
    return (
      <Text style={{ color: tokens.colorNeutralForeground3 }}>
        No client is associated with this account. Please contact your firm.
      </Text>
    );
  }

  return (
    <div className={styles.page}>
      <div>
        <div className={styles.title}>My profile</div>
        <Text style={{ color: tokens.colorNeutralForeground3 }}>
          Business identity, contact info, and the entity type that drives
          your tax filings.
        </Text>
      </div>
      <ClientProfileForm clientId={clientId} audience="client" />
    </div>
  );
}
