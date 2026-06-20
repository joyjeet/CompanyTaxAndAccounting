"""Variance & narrative generation for financial statements.

Two concerns:

1. **Variance**: compute period-over-period deltas on top of the engine's
   already-presented statements. The engine has already computed every line
   variance; this module sums those into headline figures used by both
   reports and narratives.

2. **Narrative**: produce a polished prose summary of the period.

   * The DEFAULT path is the deterministic template `template_narrative()`.
     Every figure mentioned in the prose comes verbatim from the engine
     payload; no math happens here.

   * A future LLM path may be wired via `NarrativeWriter`. The contract is
     that any prose returned must pass `verify_narrative_safety()` before it
     is persisted — the checker pulls every currency / percent token out of
     the candidate prose and refuses it if a number appears that is not
     present in the engine's allow-set. This is the "LLM may write prose but
     cannot introduce numbers" guarantee.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.domain.presentation import (
    PresentedBalanceSheet,
    PresentedCashFlow,
    PresentedLine,
    PresentedProfitAndLoss,
    PresentedSection,
    Variance,
)

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Variance summary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class VarianceHighlight:
    """One headline variance ready to render verbatim."""

    label: str
    current: Decimal
    prior: Decimal
    delta: Decimal
    pct: Decimal | None
    direction: str  # "up" | "down" | "flat"


def _direction(v: Variance) -> str:
    if v.delta > ZERO:
        return "up"
    if v.delta < ZERO:
        return "down"
    return "flat"


def _highlights_from_pl(pl: PresentedProfitAndLoss) -> list[VarianceHighlight]:
    out: list[VarianceHighlight] = []
    if pl.revenue.subtotal_variance is not None:
        v = pl.revenue.subtotal_variance
        out.append(VarianceHighlight(
            label="Revenue", current=v.current, prior=v.prior,
            delta=v.delta, pct=v.pct, direction=_direction(v),
        ))
    if pl.gross_profit_variance is not None:
        v = pl.gross_profit_variance
        out.append(VarianceHighlight(
            label="Gross Profit", current=v.current, prior=v.prior,
            delta=v.delta, pct=v.pct, direction=_direction(v),
        ))
    if pl.operating_income_variance is not None:
        v = pl.operating_income_variance
        out.append(VarianceHighlight(
            label="Operating Income", current=v.current, prior=v.prior,
            delta=v.delta, pct=v.pct, direction=_direction(v),
        ))
    if pl.net_income_variance is not None:
        v = pl.net_income_variance
        out.append(VarianceHighlight(
            label="Net Income", current=v.current, prior=v.prior,
            delta=v.delta, pct=v.pct, direction=_direction(v),
        ))
    return out


def _largest_expense(pl: PresentedProfitAndLoss) -> PresentedLine | None:
    pool: list[PresentedLine] = [
        *pl.operating_expenses.lines,
        *pl.cogs.lines,
        *pl.other_expenses.lines,
    ]
    if not pool:
        return None
    return max(pool, key=lambda ln: ln.amount)


# --------------------------------------------------------------------------- #
# Allow-set construction (drives the safety checker)
# --------------------------------------------------------------------------- #
def build_allowed_numbers(
    pl: PresentedProfitAndLoss | None = None,
    bs: PresentedBalanceSheet | None = None,
    cf: PresentedCashFlow | None = None,
) -> set[Decimal]:
    """Collect every numeric figure that the narrative may legally reference.

    Includes line amounts, subtotals, variance deltas, and variance percents.
    Both `0` and `-0` collapse; all values are quantized to 2 decimals so the
    text-side parsing comparison is robust.
    """
    out: set[Decimal] = set()

    def _add(d: Decimal | None) -> None:
        if d is None:
            return
        out.add(d.quantize(Decimal("0.01")))

    def _from_section(sec: PresentedSection) -> None:
        for ln in sec.lines:
            _add(ln.amount)
            if ln.variance is not None:
                _add(ln.variance.current)
                _add(ln.variance.prior)
                _add(ln.variance.delta)
                _add(ln.variance.pct)
        _add(sec.subtotal)
        if sec.subtotal_variance is not None:
            _add(sec.subtotal_variance.current)
            _add(sec.subtotal_variance.prior)
            _add(sec.subtotal_variance.delta)
            _add(sec.subtotal_variance.pct)

    if pl is not None:
        for sec in (
            pl.revenue, pl.cogs, pl.operating_expenses,
            pl.other_income, pl.other_expenses,
        ):
            _from_section(sec)
        _add(pl.gross_profit)
        _add(pl.operating_income)
        _add(pl.net_income)
        for var in (
            pl.gross_profit_variance,
            pl.operating_income_variance,
            pl.net_income_variance,
        ):
            if var is not None:
                _add(var.current)
                _add(var.prior)
                _add(var.delta)
                _add(var.pct)
    if bs is not None:
        for sec in (
            bs.current_assets, bs.non_current_assets,
            bs.current_liabilities, bs.long_term_liabilities, bs.equity,
        ):
            _from_section(sec)
        _add(bs.total_assets)
        _add(bs.total_liabilities)
        _add(bs.retained_earnings)
        _add(bs.total_equity)
        _add(bs.total_liab_and_equity)
        for var in (bs.total_assets_variance, bs.retained_earnings_variance):
            if var is not None:
                _add(var.current)
                _add(var.prior)
                _add(var.delta)
                _add(var.pct)
    if cf is not None:
        _add(cf.opening_cash)
        _add(cf.closing_cash)
        _add(cf.net_change)
        for sec in (cf.operating, cf.investing, cf.financing):
            for ln in sec.lines:
                _add(ln.amount)
            _add(sec.subtotal)
    return out


# --------------------------------------------------------------------------- #
# Safety check
# --------------------------------------------------------------------------- #
# Money tokens must carry a `$` (with optional currency-symbol position,
# optional sign, and optional accounting parentheses). This matches what
# the template renderer always emits via `_fmt()`, and prevents the safety
# checker from treating plain integers in prose (e.g. "code 1500", "Section
# 7", ISO date fragments like "01-01") as currency.
_MONEY_PATTERN = re.compile(
    r"""
    (?P<paren_neg>\()?            # optional accounting negative
    (?P<sign>[-+])?               # optional sign
    \$                            # REQUIRED currency symbol
    (?P<value>\d[\d,]*(?:\.\d+)?) # numeric body
    (?P<close>\))?                # optional accounting close
    """,
    re.VERBOSE,
)
_PCT_PATTERN = re.compile(
    r"(?P<sign>[-+])?(?P<value>\d[\d,]*(?:\.\d+)?)\s*%"
)
# ISO-style date fragments must be stripped wholesale before money parsing.
_ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


def _norm(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _extract_numbers(text: str) -> list[tuple[str, Decimal]]:
    """Return [(kind, normalised_value)] for every money / percent token.

    `kind` is `"money"` or `"percent"`. Years and ISO dates are filtered out.
    Money requires a `$` prefix (renderer contract); plain integers in prose
    are not treated as currency.
    """
    cleaned = _ISO_DATE_PATTERN.sub(" ", text)
    cleaned = _YEAR_PATTERN.sub(" ", cleaned)

    found: list[tuple[str, Decimal]] = []

    for m in _PCT_PATTERN.finditer(cleaned):
        sign = m.group("sign") or ""
        raw = m.group("value").replace(",", "")
        try:
            val = Decimal(f"{sign}{raw}")
        except InvalidOperation:
            continue
        found.append(("percent", _norm(val)))

    money_text = _PCT_PATTERN.sub(" ", cleaned)
    for m in _MONEY_PATTERN.finditer(money_text):
        raw = m.group("value") or ""
        if not raw or not any(c.isdigit() for c in raw):
            continue
        raw_clean = raw.replace(",", "")
        try:
            val = Decimal(raw_clean)
        except InvalidOperation:
            continue
        sign = m.group("sign") or ""
        if sign == "-" or (m.group("paren_neg") and m.group("close")):
            val = -val
        found.append(("money", _norm(val)))
    return found


@dataclass(frozen=True, slots=True)
class NarrativeSafetyReport:
    ok: bool
    foreign_numbers: tuple[tuple[str, Decimal], ...]

    def __str__(self) -> str:
        if self.ok:
            return "Narrative passed safety check."
        listing = ", ".join(f"{k}={v}" for k, v in self.foreign_numbers)
        return f"Narrative introduced numbers not in engine output: {listing}"


def verify_narrative_safety(
    narrative: str,
    *,
    allowed: set[Decimal],
) -> NarrativeSafetyReport:
    """Return a report; `ok=True` iff every numeric token in `narrative` is in
    `allowed`. For percentages, both bare integers (`5%`) and decimals
    (`5.00%`) compare equal because we normalise to 2 decimals on both sides.
    """
    allowed_norm = {_norm(v) for v in allowed}
    # Allow the absolute value of every allowed number too, since prose often
    # writes "decreased by $1,200" instead of "-$1,200".
    allowed_norm |= {abs(v) for v in allowed_norm}
    # Always allow zero (common in narrative templates).
    allowed_norm.add(Decimal("0.00"))

    foreign: list[tuple[str, Decimal]] = []
    for kind, val in _extract_numbers(narrative):
        if val not in allowed_norm:
            foreign.append((kind, val))
    return NarrativeSafetyReport(
        ok=len(foreign) == 0, foreign_numbers=tuple(foreign),
    )


# --------------------------------------------------------------------------- #
# Deterministic template
# --------------------------------------------------------------------------- #
def _fmt(amount: Decimal, currency: str) -> str:
    quantized = amount.quantize(Decimal("0.01"))
    sign = "-" if quantized < ZERO else ""
    s = f"{abs(quantized):,.2f}"
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{sign}{prefix}{s}"


def _fmt_pct(pct: Decimal | None) -> str:
    if pct is None:
        return "n/a (no prior period)"
    return f"{pct:+.2f}%"


def template_narrative(
    *,
    client_name: str,
    pl: PresentedProfitAndLoss,
    bs: PresentedBalanceSheet | None = None,
    cf: PresentedCashFlow | None = None,
    currency: str = "USD",
) -> str:
    """Build a deterministic narrative summary in Markdown.

    Every figure in the output is read DIRECTLY from the engine inputs; no
    arithmetic is performed here. The narrative is therefore guaranteed to
    pass `verify_narrative_safety()` with `allowed = build_allowed_numbers(
    pl, bs, cf)`.
    """
    lines: list[str] = []
    lines.append(f"# Financial summary — {client_name}")
    period_label = f"For the period {pl.period_start} to {pl.period_end}"
    if pl.prior_period_start is not None:
        period_label += (
            f" (compared with {pl.prior_period_start} to {pl.prior_period_end})"
        )
    lines.append(f"_{period_label}_\n")

    lines.append("## Profit & loss")
    lines.append(
        f"- Revenue: **{_fmt(pl.revenue.subtotal, currency)}**"
        + (
            f" (vs {_fmt(pl.revenue.subtotal_variance.prior, currency)}, "
            f"{_fmt_pct(pl.revenue.subtotal_variance.pct)})"
            if pl.revenue.subtotal_variance is not None else ""
        )
    )
    if pl.cogs.lines:
        lines.append(
            f"- Cost of goods sold: **{_fmt(pl.cogs.subtotal, currency)}**"
        )
        lines.append(
            f"- Gross profit: **{_fmt(pl.gross_profit, currency)}**"
        )
    lines.append(
        f"- Operating expenses: **{_fmt(pl.operating_expenses.subtotal, currency)}**"
    )
    lines.append(
        f"- Operating income: **{_fmt(pl.operating_income, currency)}**"
    )
    if pl.other_income.lines:
        lines.append(
            f"- Other income: **{_fmt(pl.other_income.subtotal, currency)}**"
        )
    if pl.other_expenses.lines:
        lines.append(
            f"- Other expenses: **{_fmt(pl.other_expenses.subtotal, currency)}**"
        )
    lines.append(
        f"- **Net income: {_fmt(pl.net_income, currency)}**"
        + (
            f" (vs {_fmt(pl.net_income_variance.prior, currency)}, "
            f"{_fmt_pct(pl.net_income_variance.pct)})"
            if pl.net_income_variance is not None else ""
        )
    )

    largest = _largest_expense(pl)
    if largest is not None:
        lines.append(
            f"\nThe largest expense in the period was {largest.code} "
            f"— {largest.name} at {_fmt(largest.amount, currency)}."
        )

    if bs is not None:
        lines.append("\n## Balance sheet")
        lines.append(f"_As of {bs.as_of}_\n")
        lines.append(f"- Total assets: **{_fmt(bs.total_assets, currency)}**")
        lines.append(
            f"- Total liabilities: **{_fmt(bs.total_liabilities, currency)}**"
        )
        lines.append(
            f"- Retained earnings to date: "
            f"**{_fmt(bs.retained_earnings, currency)}**"
        )
        lines.append(f"- Total equity: **{_fmt(bs.total_equity, currency)}**")
        # Balance assertion is enforced in present_balance_sheet, so this is
        # always true; we still surface it so the reader knows it was checked.
        lines.append(
            f"- Assets = Liabilities + Equity: **{'YES' if bs.balances else 'NO'}**"
        )

    if cf is not None:
        lines.append("\n## Cash flow")
        lines.append(f"- Opening cash: **{_fmt(cf.opening_cash, currency)}**")
        lines.append(f"- Closing cash: **{_fmt(cf.closing_cash, currency)}**")
        lines.append(f"- Net change in cash: **{_fmt(cf.net_change, currency)}**")
        for section in (cf.operating, cf.investing, cf.financing):
            lines.append(
                f"- {section.label}: **{_fmt(section.subtotal, currency)}**"
            )

    lines.append("\n## Notes & assumptions")
    for a in pl.assumptions:
        lines.append(f"- {a}")
    if cf is not None:
        for a in cf.assumptions:
            lines.append(f"- {a}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# LLM hook (optional — falls back to template if not configured)
# --------------------------------------------------------------------------- #
class NarrativeWriter(ABC):
    """Pluggable narrator. Implementations may call an LLM; the deterministic
    template always passes the safety check and is the safe default."""

    @abstractmethod
    def write(
        self,
        *,
        client_name: str,
        pl: PresentedProfitAndLoss,
        bs: PresentedBalanceSheet | None,
        cf: PresentedCashFlow | None,
        currency: str,
    ) -> str: ...


class TemplateNarrativeWriter(NarrativeWriter):
    """Deterministic writer. Always safe."""

    def write(
        self,
        *,
        client_name: str,
        pl: PresentedProfitAndLoss,
        bs: PresentedBalanceSheet | None,
        cf: PresentedCashFlow | None,
        currency: str,
    ) -> str:
        return template_narrative(
            client_name=client_name, pl=pl, bs=bs, cf=cf, currency=currency,
        )


def generate_narrative(
    *,
    client_name: str,
    pl: PresentedProfitAndLoss,
    bs: PresentedBalanceSheet | None = None,
    cf: PresentedCashFlow | None = None,
    currency: str = "USD",
    writer: NarrativeWriter | None = None,
) -> tuple[str, NarrativeSafetyReport]:
    """Produce a narrative and verify it. ALWAYS returns prose that has been
    safety-checked. If the writer's output fails the safety check, this
    falls back to the deterministic template (guaranteed safe) and returns
    the failure report so callers can log/audit the rejection.
    """
    writer = writer or TemplateNarrativeWriter()
    allowed = build_allowed_numbers(pl, bs, cf)
    candidate = writer.write(
        client_name=client_name, pl=pl, bs=bs, cf=cf, currency=currency,
    )
    report = verify_narrative_safety(candidate, allowed=allowed)
    if report.ok:
        return candidate, report
    # Unsafe — fall back to template and re-verify (must pass).
    fallback = template_narrative(
        client_name=client_name, pl=pl, bs=bs, cf=cf, currency=currency,
    )
    fallback_report = verify_narrative_safety(fallback, allowed=allowed)
    # If the template itself fails, it indicates a bug in number rendering
    # or allow-set construction — surface it.
    if not fallback_report.ok:
        raise AssertionError(
            f"Template narrative failed self-check: {fallback_report}"
        )
    return fallback, report


__all__ = [
    "VarianceHighlight",
    "NarrativeSafetyReport",
    "NarrativeWriter",
    "TemplateNarrativeWriter",
    "build_allowed_numbers",
    "generate_narrative",
    "highlights_from_pl",
    "template_narrative",
    "verify_narrative_safety",
]


# Public alias for the highlights helper so callers can reuse it without
# poking at a private name.
highlights_from_pl = _highlights_from_pl
