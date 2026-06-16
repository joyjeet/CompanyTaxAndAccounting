import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

import TopBar from "./components/TopBar";
import RequireAuth from "./components/RequireAuth";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import ClientPortal from "./pages/ClientPortal";
import DraftDetail from "./pages/DraftDetail";
import LoginPage from "./pages/LoginPage";
import ReviewQueue from "./pages/ReviewQueue";
import { useEffect } from "react";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

/**
 * Routes to the role-appropriate landing page. Firm staff -> /review;
 * portal users -> /portal. We render this at "/" so a single landing URL
 * does the right thing for each persona.
 */
function HomeRedirect() {
  const { identity } = useAuth();
  if (!identity) return <Navigate to="/login" replace />;
  return identity.role === "firm_staff" ? (
    <ReviewQueue />
  ) : (
    <ClientPortal />
  );
}

/**
 * Watches for token expiry and bounces to /login. The API client also
 * gracefully fails on 401, but this avoids a stuck UI on an expired token.
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

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <div className="app-shell">
            <TopBar />
            <main className="content">
              <SessionWatcher />
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route
                  path="/"
                  element={
                    <RequireAuth>
                      <HomeRedirect />
                    </RequireAuth>
                  }
                />
                <Route
                  path="/drafts/:id"
                  element={
                    <RequireAuth roles={["firm_staff"]}>
                      <DraftDetail />
                    </RequireAuth>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
