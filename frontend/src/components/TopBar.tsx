import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function TopBar() {
  const { identity, client, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="topbar">
      <div>
        <h1>CTAA</h1>
        <nav style={{ marginTop: 4 }}>
          {identity?.role === "firm_staff" && (
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              Review queue
            </NavLink>
          )}
          {identity?.role === "client_portal" && (
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              My documents
            </NavLink>
          )}
        </nav>
      </div>
      <div>
        {isAuthenticated && identity ? (
          <>
            <span className="who">
              {identity.sub} · {identity.role} · firm{" "}
              <code>{identity.firmId.slice(0, 8)}…</code>
              {identity.clientId && (
                <>
                  {" · client "}
                  <code>{identity.clientId.slice(0, 8)}…</code>
                </>
              )}
            </span>
            <button
              style={{ marginLeft: 12 }}
              onClick={async () => {
                await client.logout();
                navigate("/login", { replace: true });
              }}
            >
              Sign out
            </button>
          </>
        ) : (
          <span className="who">not signed in</span>
        )}
      </div>
    </header>
  );
}
