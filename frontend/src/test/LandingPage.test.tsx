import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LandingPage from "../pages/LandingPage";

const signIn = vi.fn(async () => {});

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    signIn,
    client: null,
    identity: null,
    isAuthenticated: false,
    audience: "firm" as const,
    signOut: async () => {},
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  );
}

describe("LandingPage", () => {
  beforeEach(() => {
    signIn.mockClear();
  });

  it("offers both sign-in desks", () => {
    renderPage();
    expect(screen.getByText("Accounting firm")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in to your firm/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in to your portal/i })
    ).toBeInTheDocument();
  });

  it("starts firm sign-in against the firm authority", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /sign in to your firm/i }));
    expect(signIn).toHaveBeenCalledWith("firm");
  });

  it("starts portal sign-in against the client authority", async () => {
    renderPage();
    fireEvent.click(
      screen.getByRole("button", { name: /sign in to your portal/i })
    );
    expect(signIn).toHaveBeenCalledWith("client");
  });

  it("surfaces a sign-in failure instead of failing silently", async () => {
    signIn.mockRejectedValueOnce(new Error("authority not configured"));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /sign in to your firm/i }));
    expect(await screen.findByText(/authority not configured/i)).toBeInTheDocument();
  });
});
