import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useEffectiveIdentity, useTenant } from "../auth/TenantContext";
import type { Role } from "../auth/types";
import ChooseContextPage from "../pages/ChooseContextPage";

/**
 * Renders `children` only if the caller is authenticated, has settled on a
 * tenant context, AND (optionally) holds one of the required roles. Otherwise
 * redirects or shows the context picker.
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
  const { isAuthenticated } = useAuth();
  const { status } = useTenant();
  const identity = useEffectiveIdentity();

  if (!isAuthenticated) {
    return <Navigate to="/welcome" replace />;
  }
  // Authenticated but the workspace is unresolved (still loading, ambiguous,
  // or absent). Rendering the app now would fire requests with no context.
  if (status !== "ready" || !identity) {
    return <ChooseContextPage />;
  }
  if (roles && !roles.includes(identity.role)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
