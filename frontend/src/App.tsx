import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import AppShell from "./components/AppShell";
import RequireAuth from "./components/RequireAuth";
import ArtifactsLibrary from "./pages/ArtifactsLibrary";
import ClientList from "./pages/ClientList";
import ClientDetail from "./pages/client/ClientDetail";
import Dashboard from "./pages/Dashboard";
import DraftDetail from "./pages/DraftDetail";
import LoginPage from "./pages/LoginPage";
import PortalDocuments from "./pages/PortalDocuments";
import PortalHome from "./pages/PortalHome";
import PortalProfile from "./pages/PortalProfile";
import PortalReports from "./pages/PortalReports";
import ReviewQueue from "./pages/ReviewQueue";
import RulesEngine from "./pages/RulesEngine";
import TaxFormsLibrary from "./pages/TaxFormsLibrary";
import TeamMembers from "./pages/TeamMembers";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

/**
 * Routes to the role-appropriate landing page. Firm staff -> Dashboard;
 * portal users -> PortalHome.
 */
function HomeRedirect() {
  const { identity } = useAuth();
  if (!identity) return <Navigate to="/login" replace />;
  return identity.role === "firm_staff" ? <Dashboard /> : <Navigate to="/portal" replace />;
}

/**
 * Watches for token expiry and bounces to /login.
 */
function SessionWatcher() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    if (!isAuthenticated && window.location.pathname !== "/login") {
      navigate("/login", { replace: true });
    }
  }, [isAuthenticated, navigate]);
  return null;
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <SessionWatcher />
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* Firm staff routes */}
            <Route
              path="/"
              element={
                <RequireAuth>
                  <AuthenticatedShell>
                    <HomeRedirect />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/clients"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <ClientList />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            {/* The active tab lives in the URL so a client view can be
                bookmarked, shared, and survives a refresh or Back. Bare
                /clients/:id still works and lands on Overview. */}
            <Route
              path="/clients/:id"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <ClientDetail />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/clients/:id/:tab"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <ClientDetail />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/review"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <ReviewQueue />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/drafts/:id"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <DraftDetail />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/artifacts"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <ArtifactsLibrary />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/tax/forms"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <TaxFormsLibrary />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/rules-engine"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <RulesEngine />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/team"
              element={
                <RequireAuth roles={["firm_staff"]}>
                  <AuthenticatedShell>
                    <TeamMembers />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />

            {/* Portal routes */}
            <Route
              path="/portal"
              element={
                <RequireAuth>
                  <AuthenticatedShell>
                    <PortalHome />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/portal/documents"
              element={
                <RequireAuth>
                  <AuthenticatedShell>
                    <PortalDocuments />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/portal/reports"
              element={
                <RequireAuth>
                  <AuthenticatedShell>
                    <PortalReports />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />
            <Route
              path="/portal/profile"
              element={
                <RequireAuth>
                  <AuthenticatedShell>
                    <PortalProfile />
                  </AuthenticatedShell>
                </RequireAuth>
              }
            />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
