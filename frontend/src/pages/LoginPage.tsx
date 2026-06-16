import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import config from "../config";

/**
 * Login screen.
 *
 * In dev mode we render a small form (sub / role / firm_id / client_id) so
 * the developer can hop between firm-staff and portal personas without
 * Entra ID. In msal mode we just trigger the redirect.
 */
export default function LoginPage() {
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
      <div className="content">
        <div className="card">
          <h2>Sign in</h2>
          <p>You will be redirected to Microsoft to sign in.</p>
          <button
            className="primary"
            onClick={() => client.login().catch((e) => setError(String(e)))}
          >
            Continue
          </button>
          {error && <p className="error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="content">
      <div className="card" style={{ maxWidth: 540 }}>
        <h2>Dev sign-in</h2>
        <p className="muted">
          This screen mints a test JWT against the backend's <code>/auth/dev-token</code>{" "}
          endpoint. It is only available when the backend runs with{" "}
          <code>APP_AUTH_MODE=test</code>.
        </p>
        <form
          className="form-grid"
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
          <label htmlFor="sub">Subject</label>
          <input id="sub" value={sub} onChange={(e) => setSub(e.target.value)} required />

          <label htmlFor="role">Role</label>
          <select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value as "firm_staff" | "client_portal")}
          >
            <option value="firm_staff">firm_staff (reviewer)</option>
            <option value="client_portal">client_portal (portal user)</option>
          </select>

          <label htmlFor="firmId">Firm ID</label>
          <input
            id="firmId"
            placeholder="UUID"
            value={firmId}
            onChange={(e) => setFirmId(e.target.value)}
            required
          />

          <label htmlFor="clientId">
            Client ID{role === "client_portal" ? " *" : " (optional)"}
          </label>
          <input
            id="clientId"
            placeholder={role === "client_portal" ? "UUID (required)" : "UUID (optional)"}
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            required={role === "client_portal"}
          />

          <span />
          <div>
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </div>
        </form>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
