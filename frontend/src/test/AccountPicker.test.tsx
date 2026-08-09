import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AccountPicker } from "../pages/DraftDetail";
import type { CoaOut } from "../auth/types";

function acct(id: string, code: string, name: string): CoaOut {
  return {
    id,
    client_id: "c1",
    code,
    name,
    account_type: "revenue",
    sub_type: "operating_revenue",
    normal_balance: "credit",
    is_active: true,
    parent_account_id: null,
    depth: 0,
    is_leaf: true,
    journal_line_count: 0,
    child_count: 0,
  };
}

const groups = [
  { type: "asset", label: "Assets", accounts: [acct("a1", "1000", "Cash")] },
  {
    type: "revenue",
    label: "Income",
    accounts: [
      acct("r1", "4000", "Revenue"),
      acct("r2", "4010", "Consulting Income"),
    ],
  },
];

function open() {
  const input = screen.getByRole("combobox");
  fireEvent.click(input);
  return input;
}

describe("AccountPicker search", () => {
  it("matches a mid-string substring, not just the prefix", () => {
    render(
      <AccountPicker
        groups={groups}
        label=""
        allowCreate={false}
        onPick={vi.fn()}
        onCreateNew={vi.fn()}
      />,
    );
    const input = open();
    // "evenue" is inside "Revenue" but is NOT a prefix of "4000 — Revenue".
    fireEvent.change(input, { target: { value: "evenue" } });

    expect(screen.getByText(/4000 — Revenue/)).toBeInTheDocument();
    expect(screen.queryByText(/1000 — Cash/)).toBeNull();
  });

  it("matches on the account code too", () => {
    render(
      <AccountPicker
        groups={groups}
        label=""
        allowCreate={false}
        onPick={vi.fn()}
        onCreateNew={vi.fn()}
      />,
    );
    const input = open();
    fireEvent.change(input, { target: { value: "4010" } });

    expect(screen.getByText(/4010 — Consulting Income/)).toBeInTheDocument();
    expect(screen.queryByText(/4000 — Revenue/)).toBeNull();
  });

  it("keeps filtering by name even when an account is already selected", () => {
    // With a selection present, Fluent auto-clears it on any keystroke that
    // doesn't prefix-match the option text (i.e. typing a name). The picker
    // must ignore that clear and keep the typed search alive.
    render(
      <AccountPicker
        groups={groups}
        selectedId="r1"
        label="4000 — Revenue"
        allowCreate={false}
        onPick={vi.fn()}
        onCreateNew={vi.fn()}
      />,
    );
    const input = open();
    fireEvent.change(input, { target: { value: "consult" } });

    expect(screen.getByText(/4010 — Consulting Income/)).toBeInTheDocument();
    expect(screen.queryByText(/1000 — Cash/)).toBeNull();
    expect(screen.queryByText(/4000 — Revenue/)).toBeNull();
  });
});
