import { type ReactNode } from "react";

/**
 * Per-form explainers shown next to the form code in tax tables.
 *
 * Each entry says **what the form is** and **why a business files it** —
 * enough for a CPA-adjacent user to recognize the form at a glance.
 *
 * Keep entries short (2–4 short paragraphs). Use plain HTML/JSX; rendered
 * inside `<InfoHint>` which already wraps everything in `<Body2>`.
 */
export interface FormExplainer {
  title: string;
  body: ReactNode;
}

export const FORM_EXPLAINERS: Record<string, FormExplainer> = {
  F1120: {
    title: "Form 1120 — US C-Corporation Income Tax Return",
    body: (
      <>
        Filed annually by every <b>C-corporation</b> incorporated in or
        doing business in the US. The corporation itself pays federal
        income tax on its taxable income at the corporate rate (currently
        21%); dividends to shareholders are then taxed again on each
        shareholder's personal return ("double taxation").
        <br /><br />
        <b>Why we generate this:</b> if the client is organized as a
        traditional corporation (default for any "Inc." or "Corp." that
        didn't elect S-status), this is their primary federal return.
        Our worksheet rolls posted journal entries through approved
        account → line mappings to produce the income-statement portion
        (Income, COGS, Deductions, Taxable income).
        <br /><br />
        Due: 15th day of the 4th month after fiscal year-end (Apr 15
        for calendar-year filers).
      </>
    ),
  },
  F1120S: {
    title: "Form 1120-S — US S-Corporation Income Tax Return",
    body: (
      <>
        Filed annually by corporations that elected <b>S-corporation</b>{" "}
        status (Form 2553). The S-corp itself pays no federal income tax;
        instead, income, losses, deductions, and credits "pass through"
        to shareholders via Schedule K-1, who report them on their
        personal 1040s.
        <br /><br />
        <b>Why we generate this:</b> S-corps are common for
        owner-operated small businesses because they avoid double
        taxation while still providing liability protection. The
        worksheet computes the corporation's ordinary business income —
        the headline number that flows to Schedule K and then to each
        shareholder's K-1.
        <br /><br />
        Due: 15th day of the 3rd month after fiscal year-end (Mar 15
        for calendar-year filers).
      </>
    ),
  },
  F1065: {
    title: "Form 1065 — US Return of Partnership Income",
    body: (
      <>
        Filed annually by every <b>partnership</b> and most{" "}
        <b>multi-member LLCs</b> (which default to partnership taxation).
        Like an S-corp, a partnership pays no entity-level federal tax;
        income and losses pass through to the partners' personal returns
        via Schedule K-1.
        <br /><br />
        <b>Why we generate this:</b> if your client has two or more
        owners and hasn't elected corporate taxation, this is their
        federal return. The worksheet computes ordinary business income
        which then drives each partner's share on their K-1.
        <br /><br />
        Due: 15th day of the 3rd month after fiscal year-end (Mar 15
        for calendar-year filers).
      </>
    ),
  },
  F1040SC: {
    title: "Form 1040, Schedule C — Profit or Loss From Business",
    body: (
      <>
        Filed by a <b>sole proprietor</b> or a <b>single-member LLC</b>{" "}
        (treated as a disregarded entity by default) as an attachment to
        the individual owner's Form 1040. There is no separate business
        return — the net profit (or loss) flows onto the owner's
        personal income tax.
        <br /><br />
        <b>Why we generate this:</b> the simplest small-business
        structure. The worksheet aggregates posted journal entries into
        Gross receipts, Cost of goods sold, and the standard Schedule C
        expense lines (advertising, car &amp; truck, insurance,
        rent, utilities, wages, etc.) to produce Net profit, which the
        owner enters on Schedule 1 of their 1040.
        <br /><br />
        Due: with the owner's 1040 (Apr 15 for calendar-year).
      </>
    ),
  },
};

export function explainerFor(formCode: string): FormExplainer | undefined {
  return FORM_EXPLAINERS[formCode];
}
