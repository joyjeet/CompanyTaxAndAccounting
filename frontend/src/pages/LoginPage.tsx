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
import { useEffect, useMemo, useState } from "react";
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

  // During dev/test we keep only a few UX defaults in storage.
  const lsFirm = typeof window !== "undefined"
    ? window.localStorage.getItem("ctaa.dev.firmId") || ""
    : "";
  const lsClient = typeof window !== "undefined"
    ? window.localStorage.getItem("ctaa.dev.clientId") || ""
    : "";
  const lsSub = typeof window !== "undefined"
    ? window.localStorage.getItem("ctaa.dev.sub") || ""
    : "";

  const [sub, setSub] = useState(lsSub || "dev-user@example.com");
  const [role, setRole] = useState<"firm_staff" | "client_portal">("firm_staff");
  const [firmId, setFirmId] = useState(lsFirm || config.dev.defaultFirmId);
  const [clientId, setClientId] = useState(lsClient || config.dev.defaultClientId);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [firms, setFirms] = useState<Array<{
    id: string;
    name: string;
    clients: Array<{ id: string; name: string }>;
  }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (config.authMode !== "dev") return;
    let cancelled = false;
    const load = async () => {
      setOptionsLoading(true);
      try {
        const resp = await fetch(`${config.apiBase}/auth/dev-login-options`);
        if (!resp.ok) throw new Error(`dev-login-options failed (${resp.status})`);
        const body = (await resp.json()) as {
          firms: Array<{
            id: string;
            name: string;
            clients: Array<{ id: string; name: string }>;
          }>;
        };
        if (cancelled) return;
        setFirms(body.firms ?? []);
      } catch {
        // Keep backward compatibility: if endpoint unavailable, login still
        // works with configured default IDs.
      } finally {
        if (!cancelled) setOptionsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (firms.length === 0) return;
    if (!firmId || !firms.some((f) => f.id === firmId)) {
      setFirmId(firms[0].id);
    }
  }, [firms, firmId]);

  const selectedFirm = useMemo(
    () => firms.find((f) => f.id === firmId) ?? null,
    [firms, firmId],
  );

  useEffect(() => {
    if (role !== "client_portal") return;
    const clients = selectedFirm?.clients ?? [];
    if (clients.length === 0) {
      setClientId("");
      return;
    }
    if (!clientId || !clients.some((c) => c.id === clientId)) {
      setClientId(clients[0].id);
    }
  }, [role, selectedFirm, clientId]);

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
              const trimmedFirm = firmId.trim();
              const trimmedClient = clientId.trim();
              // Persist so the next reload pre-fills the same values
              // (useful when the same tester switches between roles).
              try {
                window.localStorage.setItem("ctaa.dev.firmId", trimmedFirm);
                window.localStorage.setItem("ctaa.dev.clientId", trimmedClient);
                window.localStorage.setItem("ctaa.dev.sub", sub);
              } catch {
                /* storage may be disabled (incognito) — ignore */
              }
              await client.login({
                sub,
                role,
                firmId: trimmedFirm || undefined,
                clientId: trimmedClient || undefined,
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
          {firms.length > 0 ? (
            <Field label="Firm" required>
              <Dropdown
                value={selectedFirm?.name ?? ""}
                selectedOptions={firmId ? [firmId] : []}
                onOptionSelect={(_, d) => setFirmId(d.optionValue ?? "")}
              >
                {firms.map((f) => (
                  <Option key={f.id} value={f.id} text={f.name}>
                    {f.name}
                  </Option>
                ))}
              </Dropdown>
            </Field>
          ) : (
            <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
              {optionsLoading ? "Loading firm options..." : "Using default dev firm configuration."}
            </Caption1>
          )}
          {role === "client_portal" && firms.length > 0 && (
            <Field label="Client" required>
              <Dropdown
                value={selectedFirm?.clients.find((c) => c.id === clientId)?.name ?? ""}
                selectedOptions={clientId ? [clientId] : []}
                onOptionSelect={(_, d) => setClientId(d.optionValue ?? "")}
              >
                {(selectedFirm?.clients ?? []).map((c) => (
                  <Option key={c.id} value={c.id} text={c.name}>
                    {c.name}
                  </Option>
                ))}
              </Dropdown>
            </Field>
          )}
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
