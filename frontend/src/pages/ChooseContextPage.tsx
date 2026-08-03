/**
 * Post-login context picker.
 *
 * Shown when the signed-in user holds more than one membership, and also
 * handles the "authenticated but not onboarded" case. That case deliberately
 * does NOT redirect to the identity provider: signing in again cannot create a
 * membership, so doing so produces an infinite bounce.
 */
import {
  Body1,
  Button,
  Caption1,
  Spinner,
  Subtitle1,
  Text,
  Title2,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import { BuildingBankRegular, PersonRegular } from "@fluentui/react-icons";

import { useAuth } from "../auth/AuthContext";
import { type ContextOption, useTenant } from "../auth/TenantContext";

const useStyles = makeStyles({
  shell: {
    display: "grid",
    placeItems: "center",
    minHeight: "100vh",
    backgroundColor: tokens.colorNeutralBackground2,
    ...shorthands.padding("32px"),
  },
  card: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("32px"),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    boxShadow: tokens.shadow16,
    width: "100%",
    maxWidth: "560px",
    display: "grid",
    rowGap: "16px",
  },
  list: { display: "grid", rowGap: "8px" },
  option: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
    width: "100%",
    textAlign: "left",
    ...shorthands.padding("14px", "16px"),
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    backgroundColor: tokens.colorNeutralBackground1,
    cursor: "pointer",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  optionIcon: { fontSize: "20px", color: tokens.colorBrandForeground1 },
  optionText: { display: "grid" },
  muted: { color: tokens.colorNeutralForeground3 },
});

function label(option: ContextOption): { title: string; detail: string } {
  if (option.scope === "client") {
    return {
      title: option.client_name ?? "Client portal",
      detail: `Client portal · ${option.firm_name}`,
    };
  }
  return {
    title: option.firm_name,
    detail: `Firm staff · ${option.role.replace(/_/g, " ")}`,
  };
}

export default function ChooseContextPage() {
  const styles = useStyles();
  const { status, options, error, select } = useTenant();
  const { signOut } = useAuth();

  if (status === "loading") {
    return (
      <div className={styles.shell}>
        <Spinner label="Loading your workspaces…" />
      </div>
    );
  }

  if (status === "none") {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <Title2>You&apos;re signed in, but not set up yet</Title2>
          <Body1>
            Your account isn&apos;t linked to a firm or a client company. Ask
            your firm administrator to send you an invitation, then sign in
            again.
          </Body1>
          <Caption1 className={styles.muted}>
            If you were invited recently, the invitation may still be pending —
            accepting it from the emailed link completes the link-up.
          </Caption1>
          <div>
            <Button appearance="secondary" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <Title2>We couldn&apos;t load your workspaces</Title2>
          <Body1>{error}</Body1>
          <div>
            <Button appearance="primary" onClick={() => window.location.reload()}>
              Try again
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div>
          <Title2>Choose a workspace</Title2>
          <Caption1 block className={styles.muted}>
            Your account has access to more than one. You can switch later.
          </Caption1>
        </div>
        <div className={styles.list}>
          {options.map((option) => {
            const { title, detail } = label(option);
            return (
              <button
                key={`${option.firm_id}:${option.client_id ?? "firm"}`}
                type="button"
                className={styles.option}
                onClick={() => select(option)}
              >
                <span className={styles.optionIcon}>
                  {option.scope === "client" ? (
                    <PersonRegular />
                  ) : (
                    <BuildingBankRegular />
                  )}
                </span>
                <span className={styles.optionText}>
                  <Subtitle1>{title}</Subtitle1>
                  <Caption1 className={styles.muted}>{detail}</Caption1>
                </span>
              </button>
            );
          })}
        </div>
        <Text size={200} className={styles.muted}>
          Signed in with the wrong account?{" "}
          <Button appearance="transparent" size="small" onClick={() => void signOut()}>
            Sign out
          </Button>
        </Text>
      </div>
    </div>
  );
}
