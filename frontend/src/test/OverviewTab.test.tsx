import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OverviewTab from "../pages/client/OverviewTab";
import { useApi } from "../api/useApi";

vi.mock("../api/useApi", () => ({ useApi: vi.fn() }));

describe("OverviewTab dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(useApi).mockReturnValue({
      listPeriods: vi.fn(async () => [
        {
          id: "period-1",
          client_id: "client-1",
          name: "FY2026",
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          is_locked: false,
        },
      ]),
      listAccounts: vi.fn(async () => [
        {
          id: "acct-cash",
          client_id: "client-1",
          code: "1000",
          name: "Cash",
          account_type: "asset",
          normal_balance: "debit",
          is_active: true,
          parent_account_id: null,
          depth: 0,
          is_leaf: true,
          journal_line_count: 0,
          child_count: 0,
        },
      ]),
      listJournalEntries: vi.fn(async () => []),
      listDocuments: vi.fn(async () => []),
      listArtifacts: vi.fn(async () => []),
      getProfitAndLoss: vi.fn(async () => ({
        kind: "profit_and_loss",
        period_start: "2026-01-01",
        period_end: "2026-12-31",
        revenue: [],
        expenses: [],
        total_revenue: "1000",
        total_expenses: "200",
        net_income: "800",
      })),
      getBalanceSheet: vi.fn(async () => ({
        kind: "balance_sheet",
        as_of: "2026-12-31",
        assets: [
          {
            account_id: "acct-cash",
            code: "1000",
            name: "Cash",
            account_type: "asset",
            debit_total: "1000",
            credit_total: "0",
            signed_balance: "1000",
          },
        ],
        liabilities: [],
        equity: [],
        total_assets: "1000",
        total_liabilities: "0",
        total_equity: "1000",
        retained_earnings_to_date: "0",
        balances: true,
      })),
      getArAging: vi.fn(async () => ({
        kind: "ar_aging",
        as_of: "2026-12-31",
        account_codes: ["1100"],
        rows: [],
        totals_by_bucket: [],
        grand_total: "300",
      })),
    } as never);
  });

  it("renders QB-style client dashboard cards", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <OverviewTab clientId="client-1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText(/client dashboard/i);
    expect(screen.getByText(/bank accounts/i)).toBeInTheDocument();
    expect(screen.getByText(/profit and loss/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload file/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /select a file/i })).toBeInTheDocument();
  });
});
