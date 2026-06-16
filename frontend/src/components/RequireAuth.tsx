import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import type { Role } from "../auth/types";

/**
 * Renders `children` only if the caller is authenticated AND (optionally)
 * holds one of the required roles. Otherwise redirects.
 *
 * This is a UX guard ONLY — the backend re-enforces authz on every call,
 * so a tampered/expired token can never bypass actual permissions.
 */
export default function RequireAuth({
  children,
  roles,
}: {
  children: ReactNode;
  roles?: Role[];
}) {
  const { isAuthenticated, identity } = useAuth();
  if (!isAuthenticated || !identity) {
    return <Navigate to="/login" replace />;
  }
  if (roles && !roles.includes(identity.role)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
