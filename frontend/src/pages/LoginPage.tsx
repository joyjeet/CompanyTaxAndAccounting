import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dropdown,
  Field,
  Input,
  makeStyles,
  Option,
  shorthands,
  Spinner,
  Text,
  tokens,
} from "@fluentui/react-components";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import config from "../config";

const useStyles = makeStyles({
  shell: {
    display: "grid",
    placeItems: "center",
    minHeight: "100vh",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  card: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("32px", "32px"),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    boxShadow: tokens.shadow16,
    minWidth: "420px",
    maxWidth: "520px",
  },
  brand: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
    marginBottom: "16px",
  },
  brandMark: {
    width: "36px",
    height: "36px",
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    display: "grid",
    placeItems: "center",
    fontWeight: tokens.fontWeightBold,
  },
  form: {
    display: "grid",
    rowGap: "12px",
    marginTop: "12px",
  },
  error: {
    color: tokens.colorPaletteRedForeground1,
    fontSize: tokens.fontSizeBase200,
  },
});

export default function LoginPage() {
  const styles = useStyles();
  const { client, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const [sub, setSub] = useState("dev-user@example.com");
  const [role, setRole] = useState<"firm_staff" | "client_portal">("firm_staff");
  const [firmId, setFirmId] = useState(config.dev.defaultFirmId);
  const [clientId, setClientId] = useState(config.dev.defaultClientId);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated) {
    navigate("/", { replace: true });
    return null;
  }

  if (config.authMode === "msal") {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.brand}>
            <div className={styles.brandMark}>C</div>
            <div>
              <Text size={600} weight="semibold">CTAA</Text>
              <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
                Company Tax &amp; Accounting
              </Caption1>
            </div>
          </div>
          <Body1>You will be redirected to Microsoft Entra ID.</Body1>
          <div style={{ marginTop: 16 }}>
            <Button
              appearance="primary"
              onClick={() => client.login().catch((e) => setError(String(e)))}
            >
              Continue
            </Button>
          </div>
          {error && <p className={styles.error}>{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <div className={styles.brandMark}>C</div>
          <div>
            <Text size={600} weight="semibold">CTAA · Dev sign-in</Text>
            <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
              Mints an HS256 test token via /auth/dev-token.
            </Caption1>
          </div>
        </div>
        <Badge appearance="tint" color="warning">APP_AUTH_MODE=test only</Badge>
        <form
          className={styles.form}
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            setBusy(true);
            try {
              await client.login({
                sub,
                role,
                firmId: firmId.trim(),
                clientId: clientId.trim() || undefined,
              });
              navigate("/", { replace: true });
            } catch (err) {
              setError(err instanceof Error ? err.message : String(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Subject" required>
            <Input value={sub} onChange={(_, d) => setSub(d.value)} />
          </Field>
          <Field label="Role" required>
            <Dropdown
              value={role === "firm_staff" ? "Firm staff" : "Client portal"}
              selectedOptions={[role]}
              onOptionSelect={(_, d) => d.optionValue && setRole(d.optionValue as typeof role)}
            >
              <Option value="firm_staff">Firm staff (reviewer)</Option>
              <Option value="client_portal">Client portal (portal user)</Option>
            </Dropdown>
          </Field>
          <Field label="Firm ID (UUID)" required>
            <Input value={firmId} onChange={(_, d) => setFirmId(d.value)} />
          </Field>
          <Field
            label={
              role === "client_portal" ? "Client ID (required)" : "Client ID (optional)"
            }
            required={role === "client_portal"}
          >
            <Input value={clientId} onChange={(_, d) => setClientId(d.value)} />
          </Field>
          <div style={{ marginTop: 8 }}>
            <Button appearance="primary" type="submit" disabled={busy}>
              {busy ? <Spinner size="tiny" /> : "Sign in"}
            </Button>
          </div>
          {error && <p className={styles.error}>{error}</p>}
        </form>
      </div>
    </div>
  );
}
