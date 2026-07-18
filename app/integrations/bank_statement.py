"""Bank-statement text parsing.

Detects whether a chunk of OCR/PDF text looks like a US business bank
statement (TD, Chase, BoA, etc. style) and extracts a list of individual
transactions: `(date, description, amount, direction)`.

The parser is deliberately heuristic — it is NOT a substitute for Azure
Document Intelligence's `prebuilt-bankStatement.us` model in production.
It exists to give the demo a non-trivial end-to-end flow: a real PDF goes
in, real journal-entry proposals come out, real trial balance updates.

Returned shape (see `parse_statement()`):
    {
        "is_statement": True,
        "account_holder": "M AND M FINANCIAL CONSULTANTS LLC",
        "statement_period": "Jul 01 2025-Jul 31 2025",
        "beginning_balance": "6918.32",
        "ending_balance": "14483.88",
        "transactions": [
            {
                "date": "2025-07-09",          # ISO 8601 if year inferable
                "raw_date": "07/09",           # whatever was in the doc
                "description": "SBB MDEPOSIT",
                "amount": "350.00",            # always positive
                "direction": "deposit",        # deposit | payment
                "section": "Deposits",
                "proposed_account_code": "4000",
                "merchant": "MDEPOSIT",
            },
            ...
        ],
    }

Direction → suggested chart-of-accounts mapping uses the demo seed COA:
    deposit  -> DR 1000 Cash / CR 4000 Sales Revenue  (or 9999 if unknown)
    payment  -> DR <expense> / CR 1000 Cash
"""
from __future__ import annotations

import re
from typing import Any

# Markers that, taken together, indicate this is a bank statement and not a
# random invoice or PDF.
_STATEMENT_MARKERS = (
    "statement of account",
    "statement period",
    "beginning balance",
    "ending balance",
    "daily account activity",
    "account summary",
    "deposits and additions",  # Chase
    "withdrawals and other debits",  # Chase
)

# Section headers we know about. Order matters: a transaction line is
# tagged with the most recently seen section header.
_SECTIONS = (
    "deposits",
    "electronic deposits",
    "electronic payments",
    "checks paid",
    "service charges",
    "other credits",
    "other withdrawals",
    "atm withdrawals",
    "withdrawals",
)

# Direction inference: payments are everything that decreases the account
# balance; deposits everything that increases it.
_PAYMENT_SECTIONS = {
    "electronic payments",
    "checks paid",
    "service charges",
    "other withdrawals",
    "atm withdrawals",
    "withdrawals",
}
_DEPOSIT_SECTIONS = {
    "deposits",
    "electronic deposits",
    "other credits",
}

# Vendor/keyword -> proposed COA code. Lower-case substring match.
# Codes must exist in the demo seed COA (_SEED_ACCOUNTS).
_VENDOR_TO_CODE: tuple[tuple[str, str], ...] = (
    # Cash inflows
    ("mdeposit", "4000"),       # Mobile deposit -> Sales Revenue
    ("square", "4000"),         # Square card payouts -> Sales Revenue
    ("zelle received", "4000"),
    # Software / SaaS
    ("dropbox", "5000"),
    ("autobooks", "5000"),
    ("google", "5000"),
    ("microsoft", "5000"),
    ("zoom", "5000"),
    ("intuit", "5000"),
    ("adobe", "5000"),
    # Office / supplies
    ("staples", "5000"),
    ("office depot", "5000"),
    ("dollar tr", "5000"),
    ("amazon", "5000"),
    # Banking
    ("service charge", "5100"),
    ("monthly fee", "5100"),
    ("nsf", "5100"),
    ("overdraft", "5100"),
    # Rent
    ("rent", "5200"),
    # Loans
    # Any transaction description containing LOAN should hit 2400 so
    # loan proceeds/payments post against Loan Payable.
    ("loan", "2400"),
    ("sba", "2400"),
    # Transfers / P2P
    ("transfer to", "9999"),
    ("zelle sent", "9999"),
    ("venmo", "9999"),
)

# Money-amount regex: 1,234.56 or 4.25.
_AMOUNT_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b")

# Date regex: MM/DD or MM/DD/YYYY. Year is optional and frequently absent
# on TD statements (one-year statement implies year from the period header).
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# Statement-period header: "Statement Period: Jul 01 2025-Jul 31 2025"
_PERIOD_RE = re.compile(
    r"Statement Period[:\s]+([A-Za-z]+\s+\d{1,2}\s+\d{4})\s*-\s*([A-Za-z]+\s+\d{1,2}\s+\d{4})",
    re.IGNORECASE,
)

_BAL_RE = re.compile(
    r"(beginning balance|ending balance)\s+([\d,]+\.\d{2})", re.IGNORECASE
)


def looks_like_bank_statement(text: str | None) -> bool:
    """Return True if `text` contains enough bank-statement markers to be
    worth running the full parser against. Cheap to call."""
    if not text:
        return False
    lower = text.lower()
    hits = sum(1 for m in _STATEMENT_MARKERS if m in lower)
    return hits >= 2


def _infer_year_from_period(text: str) -> int | None:
    """Pull the year out of the 'Statement Period: ... <year>' line."""
    m = _PERIOD_RE.search(text)
    if not m:
        return None
    try:
        # "Jul 31 2025" -> 2025
        return int(m.group(2).strip().split()[-1])
    except (IndexError, ValueError):
        return None


def _propose_account_code(description: str, direction: str) -> str:
    """Look up an account code for a transaction.

    `9999` (Suspense) is the safe default when no merchant pattern matches —
    the reviewer reassigns it in the UI.

    Short keywords (≤4 chars) like "sba" or "nsf" are matched with word
    boundaries to avoid false positives such as "nsf" hitting "tra**nsf**er"
    or "sba" hitting some random "sba…" substring.
    """
    desc = description.lower()
    for keyword, code in _VENDOR_TO_CODE:
        if len(keyword) <= 4:
            if re.search(rf"\b{re.escape(keyword)}\b", desc):
                return code
        elif keyword in desc:
            return code
    return "4000" if direction == "deposit" else "9999"


def _detect_section(line: str, current: str) -> str:
    """Return the section header that this line belongs to.

    Section headers are short standalone lines like 'Electronic Payments'
    or 'Electronic Payments (continued)' on multi-page TD statements.
    """
    s = line.strip().lower().rstrip(":")
    # Strip "(continued)" / "(cont.)" suffixes seen on page-break headers.
    s = re.sub(r"\s*\((continued|cont\.?)\)\s*$", "", s).strip()
    if len(s) > 40:
        # Body paragraphs frequently contain the word "withdrawals" inline;
        # only short standalone lines are real section headers.
        return current
    for known in _SECTIONS:
        if s == known:
            return known
    return current


def _parse_amount(token: str) -> str:
    return token.replace(",", "")


def _format_date(m_raw: str, d_raw: str, year: int | None) -> tuple[str, str]:
    """Return (iso_date_or_empty, raw_date). Year inferred from period."""
    raw = f"{m_raw.zfill(2)}/{d_raw.zfill(2)}"
    if year is None:
        return "", raw
    try:
        return f"{year:04d}-{int(m_raw):02d}-{int(d_raw):02d}", raw
    except ValueError:
        return "", raw


def parse_statement(text: str) -> dict[str, Any]:
    """Parse a US bank-statement text into the structured shape documented
    at the top of this module. Returns `{is_statement: False}` if the text
    doesn't look like a bank statement.
    """
    if not looks_like_bank_statement(text):
        return {"is_statement": False}

    year = _infer_year_from_period(text)
    period_match = _PERIOD_RE.search(text)
    period = (
        f"{period_match.group(1).strip()} - {period_match.group(2).strip()}"
        if period_match
        else None
    )

    beginning = ending = None
    for m in _BAL_RE.finditer(text):
        label = m.group(1).lower()
        amt = _parse_amount(m.group(2))
        if "beginning" in label and beginning is None:
            beginning = amt
        elif "ending" in label and ending is None:
            ending = amt

    transactions: list[dict[str, Any]] = []
    current_section = ""

    # Walk line by line. A "transaction line" starts with a MM/DD date and
    # ends with a money amount; the description sits between them. Lines
    # may wrap onto continuation lines (the description is on the next
    # line) — we merge those when the wrapped line has no date.
    raw_lines = [ln.strip() for ln in text.splitlines()]
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if not line:
            i += 1
            continue

        new_section = _detect_section(line, current_section)
        if new_section != current_section:
            current_section = new_section
            i += 1
            continue

        date_m = _DATE_RE.match(line)
        if not date_m:
            i += 1
            continue

        # Capture amount — prefer the LAST money token on the line (avoids
        # picking up date fragments like '04/25').
        amounts = list(_AMOUNT_RE.finditer(line))
        amount_line_idx = i
        if not amounts:
            # The transaction's amount may be on a continuation line up to
            # ~4 lines later (TD POS / DBCRD entries wrap merchant address
            # across 2-3 lines before the amount). Find the next line that
            # (a) contains an amount and (b) does NOT start with its own
            # date (which would mean it's a different transaction).
            j = i + 1
            limit = min(i + 5, len(raw_lines))
            while j < limit:
                nxt = raw_lines[j]
                if not nxt:
                    j += 1
                    continue
                if _DATE_RE.match(nxt):
                    break  # next transaction starts here
                hits = list(_AMOUNT_RE.finditer(nxt))
                if hits:
                    amounts = hits
                    amount_line_idx = j
                    break
                j += 1
            if not amounts:
                i += 1
                continue

        amount_line = raw_lines[amount_line_idx]
        next_i = amount_line_idx + 1

        amount_match = amounts[-1]
        # Build description: everything between the date and the amount on
        # the originating line, plus any wrapped continuation lines.
        desc = line[date_m.end():].strip()
        # Strip the amount from the desc if it's there.
        desc = _AMOUNT_RE.sub("", desc).strip()

        # If the amount lived on a continuation line, the description may
        # span multiple lines; collect them up to amount_line_idx - 1.
        if amount_line_idx != i:
            for k in range(i + 1, amount_line_idx):
                if raw_lines[k]:
                    desc += " " + raw_lines[k]
            # And anything on the amount line before the amount itself.
            head = amount_line[: amount_match.start()].strip()
            if head:
                desc += " " + head
            desc = desc.strip()

        # Some statements (TD) have a 'POSTING DATE  DESCRIPTION  AMOUNT'
        # header row that matches the date regex by coincidence — skip if
        # description contains both "POSTING" and "DATE" or is empty.
        if not desc or ("POSTING" in desc and "DATE" in desc):
            i = next_i
            continue

        # Skip the daily-balance summary section (it doesn't list transactions).
        if "balance" in current_section.lower():
            i = next_i
            continue

        # Skip Subtotal rows.
        if desc.lower().startswith("subtotal"):
            i = next_i
            continue

        # Skip lines that look like the daily-balance grid (a date followed
        # by just a balance number, no descriptive text). Heuristic: very
        # short description AND amount < $10M AND no letters.
        if not re.search(r"[A-Za-z]", desc):
            i = next_i
            continue

        amount = _parse_amount(amount_match.group(0))

        direction = (
            "deposit"
            if current_section in _DEPOSIT_SECTIONS
            else "payment"
            if current_section in _PAYMENT_SECTIONS
            else "deposit"  # fallback if no section header was seen yet
        )
        iso_date, raw_date = _format_date(date_m.group(1), date_m.group(2), year)
        code = _propose_account_code(desc, direction)

        transactions.append(
            {
                "date": iso_date,
                "raw_date": raw_date,
                "description": desc[:200],
                "amount": amount,
                "direction": direction,
                "section": current_section,
                "proposed_account_code": code,
            }
        )
        i = next_i

    # Pull the account-holder name: the line right above "STATEMENT OF
    # ACCOUNT" or the first ALL-CAPS line in the header block. Best-effort.
    holder = None
    for ln in raw_lines[:40]:
        if ln.isupper() and 5 < len(ln) <= 80 and "STATEMENT" not in ln and "BANK" not in ln:
            holder = ln
            break

    return {
        "is_statement": True,
        "account_holder": holder,
        "statement_period": period,
        "beginning_balance": beginning,
        "ending_balance": ending,
        "transactions": transactions,
    }


__all__ = ["looks_like_bank_statement", "parse_statement"]
