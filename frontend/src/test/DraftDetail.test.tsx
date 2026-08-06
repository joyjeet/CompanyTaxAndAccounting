import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DraftDetail from "../pages/DraftDetail";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useFirmRole } from "../auth/useFirmRole";

vi.mock("../api/useApi", () => ({ useApi: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../auth/useFirmRole", () => ({ useFirmRole: vi.fn() }));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useParams: () => ({ id: "draft-1" }),
    useNavigate: () => vi.fn(),
  };
});

describe("DraftDetail role gating", () => {
  let apiMock: Record<string, ReturnType<typeof vi.fn>>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:mock"),
        revokeObjectURL: vi.fn(),
      }),
    );

    apiMock = {
      listDrafts: vi.fn(async () => [
        {
          id: "draft-1",
          source_document_id: "doc-1",
          kind: "bank_transaction",
          status: "pending",
          confidence: "0.77",
          high_confidence: false,
          needs_review: true,
          model: "mock-model",
          prompt_version: "v1",
          payload: { amount: "100.00", memo: "Office supplies" },
        },
      ]),
      getDocument: vi.fn(async () => ({
        id: "doc-1",
        client_id: "client-1",
        kind: "receipt",
        filename: "receipt.pdf",
        content_type: "application/pdf",
        sha256: "abc",
        storage_uri: "blob://doc-1",
        size_bytes: 123,
        ocr_status: "complete",
        ocr_completed_at: null,
        ocr_error: null,
        received_at: "2026-07-19T00:00:00Z",
        uploaded_by: null,
        extracted: null,
        drafts: [],
        journal_entries: [],
      })),
      downloadDocumentBlob: vi.fn(async () => new Blob(["pdf"], { type: "application/pdf" })),
      listClients: vi.fn(async () => [{ id: "client-1", firm_id: "firm-1", name: "Client 1", external_code: null }]),
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
          id: "acct-1000",
          client_id: "client-1",
          code: "1000",
          name: "Cash",
          account_type: "asset",
          normal_balance: "debit",
          is_active: true,
          parent_account_id: null,
        },
        {
          id: "acct-5000",
          client_id: "client-1",
          code: "5000",
          name: "Office Expense",
          account_type: "expense",
          normal_balance: "debit",
          is_active: true,
          parent_account_id: null,
        },
      ]),
      promoteDraft: vi.fn(),
      rejectDraft: vi.fn(),
      promoteStatementDraft: vi.fn(),
      createAccount: vi.fn(async () => ({
        id: "acct-6150",
        client_id: "client-1",
        code: "6150",
        name: "Software subscriptions",
        account_type: "expense",
        normal_balance: "debit",
        is_active: true,
        parent_account_id: null,
      })),
    };

    vi.mocked(useApi).mockReturnValue(apiMock as never);
    vi.mocked(useAuth).mockReturnValue({
      identity: {
        sub: "staff@example.com",
        firmId: "firm-1",
        clientId: "client-1",
        role: "firm_staff",
        expiresAt: 9999999999,
      },
    } as never);
    vi.mocked(useFirmRole).mockReturnValue({
      role: "read_only",
      isAdmin: false,
      capabilities: {
        canManageTeam: false,
        canCreateClient: false,
        canEditRulesEngine: false,
        canPromoteDrafts: false,
      },
      isLoading: false,
    });
  });

  it("disables promote/reject actions for read-only role and shows reason", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DraftDetail />
      </QueryClientProvider>,
    );

    await screen.findByText(/Draft · bank_transaction/i);

    const promote = screen.getByRole("button", { name: /Promote to journal entry/i });
    const reject = screen.getByRole("button", { name: /Reject draft/i });

    expect(promote).toBeDisabled();
    expect(reject).toBeDisabled();
    expect(
      screen.getAllByText(/read-only for draft posting actions/i).length,
    ).toBeGreaterThan(0);
  });

  it("hides the inline new-account option from roles that cannot post", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DraftDetail />
      </QueryClientProvider>,
    );

    await screen.findByText(/Draft · bank_transaction/i);
    fireEvent.click(screen.getAllByRole("combobox", { name: /account/i })[0]);

    expect(screen.queryByRole("option", { name: /new account/i })).toBeNull();
  });

  it("creates an account inline and selects it without leaving the draft", async () => {
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

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DraftDetail />
      </QueryClientProvider>,
    );

    await screen.findByText(/Draft · bank_transaction/i);

    fireEvent.click(screen.getAllByRole("combobox", { name: /account/i })[0]);
    fireEvent.click(await screen.findByRole("option", { name: /new account/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("6150"), {
      target: { value: "6150" },
    });
    fireEvent.change(within(dialog).getByPlaceholderText("Software subscriptions"), {
      target: { value: "Software subscriptions" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /create and select/i }));

    await waitFor(() => {
      expect(apiMock.createAccount).toHaveBeenCalledWith("client-1", {
        code: "6150",
        name: "Software subscriptions",
        account_type: "expense",
        parent_account_id: null,
      });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("creates a sub-account inline when a parent account is chosen", async () => {
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

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DraftDetail />
      </QueryClientProvider>,
    );

    await screen.findByText(/Draft · bank_transaction/i);

    fireEvent.click(screen.getAllByRole("combobox", { name: /account/i })[0]);
    fireEvent.click(await screen.findByRole("option", { name: /new account/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("6150"), {
      target: { value: "6151" },
    });
    fireEvent.change(within(dialog).getByPlaceholderText("Software subscriptions"), {
      target: { value: "Cloud backup" },
    });

    fireEvent.click(within(dialog).getByRole("combobox", { name: /parent account/i }));
    fireEvent.click(await screen.findByRole("option", { name: /5000 — Office Expense/i }));
    fireEvent.click(within(dialog).getByRole("button", { name: /create and select/i }));

    await waitFor(() => {
      expect(apiMock.createAccount).toHaveBeenCalledWith("client-1", {
        code: "6151",
        name: "Cloud backup",
        account_type: "expense",
        parent_account_id: "acct-5000",
      });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
