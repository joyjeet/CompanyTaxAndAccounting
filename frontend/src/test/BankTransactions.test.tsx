import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BankTransactions from "../pages/BankTransactions";
import { useApi } from "../api/useApi";
import { useFirmRole } from "../auth/useFirmRole";

vi.mock("../api/useApi", () => ({ useApi: vi.fn() }));
vi.mock("../auth/useFirmRole", () => ({ useFirmRole: vi.fn() }));

describe("BankTransactions", () => {
  let apiMock: {
    listDrafts: ReturnType<typeof vi.fn>;
    learnStatementRule: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();

    apiMock = {
      listDrafts: vi.fn(async () => [
        {
          id: "draft-1",
          source_document_id: "doc-1",
          kind: "bank_transaction",
          status: "pending_review",
          confidence: "0.9",
          high_confidence: true,
          needs_review: false,
          model: "mock",
          prompt_version: "v1",
          payload: {
            is_statement: true,
            transactions: [
              {
                raw_date: "07/10",
                date: "2026-07-10",
                description: "Facebook Ads",
                direction: "payment",
                amount: "100.00",
                proposed_account_code: "8010",
              },
            ],
          },
        },
      ]),
      learnStatementRule: vi.fn(async () => ({ learned_rule_count: 1 })),
    };

    vi.mocked(useApi).mockReturnValue(apiMock as never);
    vi.mocked(useFirmRole).mockReturnValue({
      role: "staff",
      isAdmin: false,
      capabilities: {
        canManageTeam: false,
        canCreateClient: true,
        canEditRulesEngine: false,
        canPromoteDrafts: true,
      },
      isLoading: false,
    });
  });

  it("learns a rule from a transaction row", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <BankTransactions />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText(/bank transactions/i);
    const learnButtons = await screen.findAllByRole("button", { name: /learn rule/i });
    fireEvent.click(learnButtons[0]);

    await waitFor(() => {
      expect(apiMock.learnStatementRule).toHaveBeenCalledWith("draft-1", {
        transaction_index: 0,
        target_account_code: "8010",
      });
    });
  });
});
