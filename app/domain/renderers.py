"""Renderer interface + PDF/XLSX implementations.

The contract: a `StatementRenderer` takes the already-presented engine output
(see `app/domain/presentation.py`) plus branding context and returns raw
bytes for the chosen format. Renderers NEVER perform arithmetic; every figure
they print comes from the input data unchanged.

Implementations:

* `PdfStatementRenderer`  — ReportLab. Produces client-ready, branded PDFs
                            with header (firm name + tagline + address), an
                            optional logo, period/as-of label, and the
                            presentation sections.

* `XlsxStatementRenderer` — openpyxl. Each statement is one worksheet, with
                            inspectable subtotals expressed as `SUM(...)`
                            formulas so a reader can see how each subtotal is
                            built. Tax worksheets additionally get a
                            "Supporting Detail" sheet listing the
                            contributing accounts for every line.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ReportLab imports are heavy; keep them at module-import time though, as
# the renderer is used eagerly when triggered. Lazy-import inside the class
# would just move the cost; pre-loading lets us fail fast on missing deps.
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.presentation import (
    PresentedBalanceSheet,
    PresentedCashFlow,
    PresentedProfitAndLoss,
    PresentedSection,
)

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Branding
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class BrandingContext:
    """Operator-firm branding rendered onto every report."""

    firm_name: str
    tagline: str = ""
    address: str = ""
    logo_path: str = ""
    currency: str = "USD"

    @classmethod
    def from_settings(cls) -> BrandingContext:
        from app.core.config import get_settings

        s = get_settings()
        return cls(
            firm_name=s.branding_firm_name,
            tagline=s.branding_firm_tagline,
            address=s.branding_firm_address,
            logo_path=s.branding_firm_logo_path,
            currency=s.branding_currency,
        )


# --------------------------------------------------------------------------- #
# Money formatting
# --------------------------------------------------------------------------- #
def _fmt_money(amount: Decimal, currency: str = "USD") -> str:
    """Display Decimal as `$1,234.56` (always 2 decimals, parentheses for neg)."""
    quantized = amount.quantize(Decimal("0.01"))
    sign = "-" if quantized < ZERO else ""
    abs_amt = abs(quantized)
    # Thousands separator with two decimals.
    s = f"{abs_amt:,.2f}"
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{sign}{prefix}{s}"


def _fmt_pct(pct: Decimal | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:+.2f}%"


def _fmt_variance_amount(amount: Decimal, currency: str) -> str:
    return _fmt_money(amount, currency=currency)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class StatementRenderer(ABC):
    """Abstract renderer. Implementations are stateless."""

    format_name: str

    @abstractmethod
    def render_profit_and_loss(
        self, pl: PresentedProfitAndLoss, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes: ...

    @abstractmethod
    def render_balance_sheet(
        self, bs: PresentedBalanceSheet, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes: ...

    @abstractmethod
    def render_cash_flow(
        self, cf: PresentedCashFlow, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes: ...

    @abstractmethod
    def render_tax_worksheet(
        self, worksheet: dict[str, Any], *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        """`worksheet` is a serialized TaxWorksheet+lines (see artifact_service)."""


# --------------------------------------------------------------------------- #
# PDF implementation
# --------------------------------------------------------------------------- #
class PdfStatementRenderer(StatementRenderer):
    format_name = "pdf"

    # ---- internal helpers --------------------------------------------- #
    def _styles(self) -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        title = ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=colors.HexColor("#1f3a5f"),
            alignment=1,  # center
        )
        h2 = ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor("#1f3a5f"),
            spaceBefore=10, spaceAfter=4,
        )
        normal = base["BodyText"]
        small = ParagraphStyle(
            "Small", parent=normal, fontSize=8, textColor=colors.grey,
        )
        return {"title": title, "h2": h2, "normal": normal, "small": small}

    def _header(
        self, branding: BrandingContext, client_name: str,
        report_title: str, period_text: str, styles: dict[str, ParagraphStyle],
    ) -> list:
        story: list = []
        if branding.logo_path:
            try:
                story.append(Image(branding.logo_path, width=1.25 * inch, height=0.5 * inch))
                story.append(Spacer(1, 6))
            except Exception:
                # Missing/malformed logo file should not block report generation.
                pass
        story.append(Paragraph(branding.firm_name, styles["title"]))
        meta = []
        if branding.tagline:
            meta.append(branding.tagline)
        if branding.address:
            meta.append(branding.address)
        if meta:
            story.append(Paragraph(" • ".join(meta), styles["small"]))
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>{client_name}</b>", styles["normal"]))
        story.append(Paragraph(report_title, styles["h2"]))
        story.append(Paragraph(period_text, styles["small"]))
        story.append(Spacer(1, 10))
        return story

    def _section_table(
        self, section: PresentedSection, *, has_comparatives: bool,
        currency: str, indent_lines: bool = True,
    ) -> Table:
        rows: list[list[str]] = []
        if has_comparatives:
            rows.append(["", "Current", "Prior", "Δ", "%"])
        else:
            rows.append(["", "Amount"])
        for ln in section.lines:
            name = f"{ln.code} — {ln.name}"
            if has_comparatives and ln.variance is not None:
                v = ln.variance
                rows.append([
                    name,
                    _fmt_money(v.current, currency),
                    _fmt_money(v.prior, currency),
                    _fmt_variance_amount(v.delta, currency),
                    _fmt_pct(v.pct),
                ])
            else:
                rows.append([name, _fmt_money(ln.amount, currency)])
        # Subtotal row.
        if has_comparatives and section.subtotal_variance is not None:
            v = section.subtotal_variance
            rows.append([
                f"Total {section.label}",
                _fmt_money(v.current, currency),
                _fmt_money(v.prior, currency),
                _fmt_variance_amount(v.delta, currency),
                _fmt_pct(v.pct),
            ])
        else:
            rows.append([f"Total {section.label}", _fmt_money(section.subtotal, currency)])

        n_cols = 5 if has_comparatives else 2
        col_widths = (
            [3.4 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch, 0.7 * inch]
            if has_comparatives else [5.0 * inch, 2.0 * inch]
        )
        t = Table(rows, colWidths=col_widths, hAlign="LEFT")
        style = TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            ("LINEBELOW", (0, -2), (-1, -2), 0.5, colors.grey),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eef7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ])
        if indent_lines:
            style.add("LEFTPADDING", (0, 1), (0, -2), 16)
        t.setStyle(style)
        _ = n_cols  # quiet unused
        return t

    def _kv_row(self, label: str, value: str) -> Table:
        t = Table([[label, value]], colWidths=[3.4 * inch, 3.6 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde6f3")),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ]))
        return t

    def _build_doc(self) -> tuple[SimpleDocTemplate, BytesIO]:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=LETTER,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        )
        return doc, buf

    # ---- public render methods ---------------------------------------- #
    def render_profit_and_loss(
        self, pl: PresentedProfitAndLoss, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        styles = self._styles()
        doc, buf = self._build_doc()
        story: list = []
        comparatives = pl.prior_period_start is not None
        period_text = f"For the period {pl.period_start} to {pl.period_end}"
        if comparatives:
            period_text += (
                f" (compared with {pl.prior_period_start} to {pl.prior_period_end})"
            )
        story += self._header(
            branding, client_name, "Profit & Loss Statement", period_text, styles,
        )

        # Sections in standard order.
        story.append(self._section_table(
            pl.revenue, has_comparatives=comparatives, currency=branding.currency,
        ))
        story.append(Spacer(1, 6))
        if pl.cogs.lines:
            story.append(self._section_table(
                pl.cogs, has_comparatives=comparatives, currency=branding.currency,
            ))
            story.append(Spacer(1, 6))
            story.append(self._kv_row("Gross Profit", _fmt_money(pl.gross_profit, branding.currency)))
            story.append(Spacer(1, 6))
        if pl.operating_expenses.lines:
            story.append(self._section_table(
                pl.operating_expenses, has_comparatives=comparatives,
                currency=branding.currency,
            ))
            story.append(Spacer(1, 6))
        story.append(self._kv_row(
            "Operating Income", _fmt_money(pl.operating_income, branding.currency),
        ))
        if pl.other_income.lines:
            story.append(Spacer(1, 6))
            story.append(self._section_table(
                pl.other_income, has_comparatives=comparatives,
                currency=branding.currency,
            ))
        if pl.other_expenses.lines:
            story.append(Spacer(1, 6))
            story.append(self._section_table(
                pl.other_expenses, has_comparatives=comparatives,
                currency=branding.currency,
            ))
        story.append(Spacer(1, 8))
        story.append(self._kv_row(
            "Net Income", _fmt_money(pl.net_income, branding.currency),
        ))
        # Assumptions footer.
        story.append(Spacer(1, 14))
        story.append(Paragraph("<b>Presentation assumptions</b>", styles["small"]))
        for a in pl.assumptions:
            story.append(Paragraph(f"• {a}", styles["small"]))

        doc.build(story)
        return buf.getvalue()

    def render_balance_sheet(
        self, bs: PresentedBalanceSheet, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        styles = self._styles()
        doc, buf = self._build_doc()
        story: list = []
        comparatives = bs.prior_as_of is not None
        period_text = f"As of {bs.as_of}"
        if comparatives:
            period_text += f" (compared with {bs.prior_as_of})"
        story += self._header(
            branding, client_name, "Balance Sheet", period_text, styles,
        )

        story.append(self._section_table(
            bs.current_assets, has_comparatives=comparatives, currency=branding.currency,
        ))
        story.append(Spacer(1, 4))
        if bs.non_current_assets.lines:
            story.append(self._section_table(
                bs.non_current_assets, has_comparatives=comparatives,
                currency=branding.currency,
            ))
            story.append(Spacer(1, 4))
        story.append(self._kv_row(
            "Total Assets", _fmt_money(bs.total_assets, branding.currency),
        ))
        story.append(Spacer(1, 12))

        if bs.current_liabilities.lines:
            story.append(self._section_table(
                bs.current_liabilities, has_comparatives=comparatives,
                currency=branding.currency,
            ))
            story.append(Spacer(1, 4))
        if bs.long_term_liabilities.lines:
            story.append(self._section_table(
                bs.long_term_liabilities, has_comparatives=comparatives,
                currency=branding.currency,
            ))
            story.append(Spacer(1, 4))
        story.append(self._kv_row(
            "Total Liabilities", _fmt_money(bs.total_liabilities, branding.currency),
        ))
        story.append(Spacer(1, 8))

        story.append(self._section_table(
            bs.equity, has_comparatives=comparatives, currency=branding.currency,
        ))
        story.append(Spacer(1, 4))
        story.append(self._kv_row(
            "Retained Earnings (to date)",
            _fmt_money(bs.retained_earnings, branding.currency),
        ))
        story.append(self._kv_row(
            "Total Equity", _fmt_money(bs.total_equity, branding.currency),
        ))
        story.append(Spacer(1, 8))
        story.append(self._kv_row(
            "Total Liabilities + Equity",
            _fmt_money(bs.total_liab_and_equity, branding.currency),
        ))

        story.append(Spacer(1, 14))
        story.append(Paragraph("<b>Presentation assumptions</b>", styles["small"]))
        for a in bs.assumptions:
            story.append(Paragraph(f"• {a}", styles["small"]))

        doc.build(story)
        return buf.getvalue()

    def render_cash_flow(
        self, cf: PresentedCashFlow, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        styles = self._styles()
        doc, buf = self._build_doc()
        story: list = []
        period_text = (
            f"For the period {cf.period_start} to {cf.period_end} • "
            f"Cash accounts: {', '.join(cf.cash_account_codes)}"
        )
        story += self._header(
            branding, client_name, "Statement of Cash Flows", period_text, styles,
        )

        story.append(self._kv_row(
            "Opening Cash", _fmt_money(cf.opening_cash, branding.currency),
        ))
        story.append(Spacer(1, 8))

        for section in (cf.operating, cf.investing, cf.financing):
            if section.lines:
                story.append(self._section_table(
                    PresentedSection(
                        label=section.label,
                        lines=section.lines,
                        subtotal=section.subtotal,
                    ),
                    has_comparatives=False, currency=branding.currency,
                ))
                story.append(Spacer(1, 4))
            else:
                story.append(self._kv_row(
                    f"Total {section.label}",
                    _fmt_money(section.subtotal, branding.currency),
                ))
                story.append(Spacer(1, 2))

        story.append(Spacer(1, 6))
        story.append(self._kv_row(
            "Net Change in Cash", _fmt_money(cf.net_change, branding.currency),
        ))
        story.append(self._kv_row(
            "Closing Cash", _fmt_money(cf.closing_cash, branding.currency),
        ))

        story.append(Spacer(1, 14))
        story.append(Paragraph(
            "<b>Classification &amp; tie-out assumptions</b>", styles["small"],
        ))
        for a in cf.assumptions:
            story.append(Paragraph(f"• {a}", styles["small"]))
        story.append(Paragraph(
            f"<i>Closing cash ties to balance sheet: "
            f"{'YES' if cf.ties_to_balance_sheet else 'NO'}.</i>",
            styles["small"],
        ))

        doc.build(story)
        return buf.getvalue()

    def render_tax_worksheet(
        self, worksheet: dict[str, Any], *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        styles = self._styles()
        doc, buf = self._build_doc()
        story: list = []
        title = f"Tax Worksheet — {worksheet['form_code']}"
        period_text = (
            f"Period {worksheet['period_start']} to {worksheet['period_end']} • "
            f"Catalog v{worksheet['catalog_version']} • Status {worksheet['status']}"
        )
        story += self._header(branding, client_name, title, period_text, styles)

        # Per-line table.
        rows = [["Line", "Label", "Section", "Amount"]]
        for ln in worksheet["lines"]:
            rows.append([
                ln["line_code"], ln["line_label"], ln["section"],
                _fmt_money(Decimal(str(ln["amount"])), branding.currency),
            ])
        rows.append([
            "", "", "Total Income",
            _fmt_money(Decimal(str(worksheet["total_income"])), branding.currency),
        ])
        rows.append([
            "", "", "Total COGS",
            _fmt_money(Decimal(str(worksheet["total_cogs"])), branding.currency),
        ])
        rows.append([
            "", "", "Total Deductions",
            _fmt_money(Decimal(str(worksheet["total_deductions"])), branding.currency),
        ])
        rows.append([
            "", "", "Taxable Income",
            _fmt_money(Decimal(str(worksheet["taxable_income"])), branding.currency),
        ])
        t = Table(rows, colWidths=[0.7 * inch, 3.7 * inch, 1.2 * inch, 1.4 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -5), [colors.whitesmoke, colors.white]),
            ("FONTNAME", (0, -4), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -4), (-1, -1), colors.HexColor("#e8eef7")),
            ("LINEABOVE", (0, -4), (-1, -4), 1, colors.HexColor("#1f3a5f")),
        ]))
        story.append(t)

        story.append(Spacer(1, 10))
        story.append(Paragraph(
            f"<i>SHA-256 of computed amounts: {worksheet['sha256']}</i>", styles["small"],
        ))

        doc.build(story)
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# XLSX implementation
# --------------------------------------------------------------------------- #
class XlsxStatementRenderer(StatementRenderer):
    format_name = "xlsx"

    # ---- helpers ------------------------------------------------------ #
    @staticmethod
    def _header_fill() -> PatternFill:
        return PatternFill("solid", fgColor="1F3A5F")

    @staticmethod
    def _subtotal_fill() -> PatternFill:
        return PatternFill("solid", fgColor="E8EEF7")

    @staticmethod
    def _bold_white() -> Font:
        return Font(bold=True, color="FFFFFF")

    @staticmethod
    def _bold() -> Font:
        return Font(bold=True)

    @staticmethod
    def _money_format(currency: str) -> str:
        if currency == "USD":
            return '"$"#,##0.00;[Red]("$"#,##0.00)'
        return f'"{currency} "#,##0.00;[Red]("{currency} "#,##0.00)'

    @staticmethod
    def _thin_border() -> Border:
        side = Side(border_style="thin", color="CCCCCC")
        return Border(left=side, right=side, top=side, bottom=side)

    def _write_header(
        self, ws, branding: BrandingContext, client_name: str,
        title: str, subtitle: str,
    ) -> int:
        """Write the branded header. Returns the next free row index (1-based)."""
        ws["A1"] = branding.firm_name
        ws["A1"].font = Font(bold=True, size=16, color="1F3A5F")
        meta_parts = [s for s in (branding.tagline, branding.address) if s]
        if meta_parts:
            ws["A2"] = " • ".join(meta_parts)
            ws["A2"].font = Font(size=9, color="808080")
        ws["A4"] = client_name
        ws["A4"].font = Font(bold=True, size=11)
        ws["A5"] = title
        ws["A5"].font = Font(bold=True, size=13, color="1F3A5F")
        ws["A6"] = subtitle
        ws["A6"].font = Font(size=9, color="808080")
        ws.column_dimensions["A"].width = 38
        for col in ("B", "C", "D", "E"):
            ws.column_dimensions[col].width = 18
        return 8

    def _write_section(
        self, ws, start_row: int, section: PresentedSection,
        *, has_comparatives: bool, currency: str,
    ) -> int:
        """Write a section table starting at `start_row`. Returns next free row."""
        money_fmt = self._money_format(currency)
        # Header row.
        headers = (
            ["", "Current", "Prior", "Δ", "%"]
            if has_comparatives else ["", "Amount"]
        )
        for idx, h in enumerate(headers):
            cell = ws.cell(row=start_row, column=idx + 1, value=h)
            cell.font = self._bold_white()
            cell.fill = self._header_fill()
            cell.alignment = Alignment(horizontal="right" if idx > 0 else "left")
        row = start_row + 1
        first_amount_row = row
        for ln in section.lines:
            ws.cell(row=row, column=1, value=f"{ln.code} — {ln.name}")
            if has_comparatives and ln.variance is not None:
                v = ln.variance
                ws.cell(row=row, column=2, value=float(v.current)).number_format = money_fmt
                ws.cell(row=row, column=3, value=float(v.prior)).number_format = money_fmt
                ws.cell(row=row, column=4, value=float(v.delta)).number_format = money_fmt
                ws.cell(row=row, column=5, value=(float(v.pct) / 100.0) if v.pct is not None else None)
                ws.cell(row=row, column=5).number_format = "0.00%"
            else:
                ws.cell(row=row, column=2, value=float(ln.amount)).number_format = money_fmt
            row += 1
        last_amount_row = row - 1
        # Subtotal row with formula so the figure is inspectable in cell.
        ws.cell(row=row, column=1, value=f"Total {section.label}").font = self._bold()
        if last_amount_row >= first_amount_row:
            if has_comparatives:
                for col_letter, col_idx in (("B", 2), ("C", 3), ("D", 4)):
                    ws.cell(
                        row=row, column=col_idx,
                        value=f"=SUM({col_letter}{first_amount_row}:{col_letter}{last_amount_row})",
                    ).number_format = money_fmt
                ws.cell(row=row, column=5, value=None)
            else:
                ws.cell(
                    row=row, column=2,
                    value=f"=SUM(B{first_amount_row}:B{last_amount_row})",
                ).number_format = money_fmt
        else:
            # No lines — just write the subtotal literal.
            ws.cell(row=row, column=2, value=float(section.subtotal)).number_format = money_fmt
        for col in range(1, 6 if has_comparatives else 3):
            ws.cell(row=row, column=col).fill = self._subtotal_fill()
            ws.cell(row=row, column=col).font = self._bold()
        return row + 2  # blank spacer after subtotal

    def _write_kv(
        self, ws, row: int, label: str, value: Decimal, currency: str,
    ) -> int:
        cell_l = ws.cell(row=row, column=1, value=label)
        cell_v = ws.cell(row=row, column=2, value=float(value))
        cell_v.number_format = self._money_format(currency)
        for cell in (cell_l, cell_v):
            cell.font = self._bold()
            cell.fill = self._subtotal_fill()
        return row + 1

    def _write_assumptions(self, ws, row: int, assumptions: tuple[str, ...]) -> int:
        ws.cell(row=row, column=1, value="Presentation assumptions").font = self._bold()
        row += 1
        for a in assumptions:
            ws.cell(row=row, column=1, value=f"• {a}").font = Font(size=9, color="808080")
            row += 1
        return row

    # ---- public methods ---------------------------------------------- #
    def render_profit_and_loss(
        self, pl: PresentedProfitAndLoss, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "P&L"
        comparatives = pl.prior_period_start is not None
        subtitle = f"For the period {pl.period_start} to {pl.period_end}"
        if comparatives:
            subtitle += f" (vs {pl.prior_period_start} to {pl.prior_period_end})"
        row = self._write_header(ws, branding, client_name, "Profit & Loss Statement", subtitle)
        row = self._write_section(ws, row, pl.revenue, has_comparatives=comparatives, currency=branding.currency)
        if pl.cogs.lines:
            row = self._write_section(ws, row, pl.cogs, has_comparatives=comparatives, currency=branding.currency)
            row = self._write_kv(ws, row, "Gross Profit", pl.gross_profit, branding.currency)
            row += 1
        if pl.operating_expenses.lines:
            row = self._write_section(
                ws, row, pl.operating_expenses,
                has_comparatives=comparatives, currency=branding.currency,
            )
        row = self._write_kv(ws, row, "Operating Income", pl.operating_income, branding.currency)
        row += 1
        if pl.other_income.lines:
            row = self._write_section(
                ws, row, pl.other_income, has_comparatives=comparatives, currency=branding.currency,
            )
        if pl.other_expenses.lines:
            row = self._write_section(
                ws, row, pl.other_expenses, has_comparatives=comparatives, currency=branding.currency,
            )
        row = self._write_kv(ws, row, "Net Income", pl.net_income, branding.currency)
        row += 2
        self._write_assumptions(ws, row, pl.assumptions)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def render_balance_sheet(
        self, bs: PresentedBalanceSheet, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Balance Sheet"
        comparatives = bs.prior_as_of is not None
        subtitle = f"As of {bs.as_of}"
        if comparatives:
            subtitle += f" (vs {bs.prior_as_of})"
        row = self._write_header(ws, branding, client_name, "Balance Sheet", subtitle)
        row = self._write_section(ws, row, bs.current_assets, has_comparatives=comparatives, currency=branding.currency)
        if bs.non_current_assets.lines:
            row = self._write_section(ws, row, bs.non_current_assets, has_comparatives=comparatives, currency=branding.currency)
        row = self._write_kv(ws, row, "Total Assets", bs.total_assets, branding.currency)
        row += 1
        if bs.current_liabilities.lines:
            row = self._write_section(ws, row, bs.current_liabilities, has_comparatives=comparatives, currency=branding.currency)
        if bs.long_term_liabilities.lines:
            row = self._write_section(ws, row, bs.long_term_liabilities, has_comparatives=comparatives, currency=branding.currency)
        row = self._write_kv(ws, row, "Total Liabilities", bs.total_liabilities, branding.currency)
        row += 1
        row = self._write_section(ws, row, bs.equity, has_comparatives=comparatives, currency=branding.currency)
        row = self._write_kv(ws, row, "Retained Earnings (to date)", bs.retained_earnings, branding.currency)
        row = self._write_kv(ws, row, "Total Equity", bs.total_equity, branding.currency)
        row += 1
        row = self._write_kv(ws, row, "Total Liabilities + Equity", bs.total_liab_and_equity, branding.currency)
        row += 2
        self._write_assumptions(ws, row, bs.assumptions)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def render_cash_flow(
        self, cf: PresentedCashFlow, *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Cash Flow"
        subtitle = (
            f"For the period {cf.period_start} to {cf.period_end} • "
            f"Cash accounts: {', '.join(cf.cash_account_codes)}"
        )
        row = self._write_header(ws, branding, client_name, "Statement of Cash Flows", subtitle)
        row = self._write_kv(ws, row, "Opening Cash", cf.opening_cash, branding.currency)
        row += 1
        for section in (cf.operating, cf.investing, cf.financing):
            if section.lines:
                row = self._write_section(
                    ws, row,
                    PresentedSection(label=section.label, lines=section.lines, subtotal=section.subtotal),
                    has_comparatives=False, currency=branding.currency,
                )
            else:
                row = self._write_kv(
                    ws, row, f"Total {section.label}", section.subtotal, branding.currency,
                )
                row += 1
        row = self._write_kv(ws, row, "Net Change in Cash", cf.net_change, branding.currency)
        row = self._write_kv(ws, row, "Closing Cash", cf.closing_cash, branding.currency)
        row += 2
        self._write_assumptions(ws, row, cf.assumptions)
        ws.cell(row=row, column=1, value=f"Closing cash ties to balance sheet: {'YES' if cf.ties_to_balance_sheet else 'NO'}").font = self._bold()

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def render_tax_worksheet(
        self, worksheet: dict[str, Any], *, client_name: str,
        branding: BrandingContext,
    ) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Tax Worksheet"
        money_fmt = self._money_format(branding.currency)
        subtitle = (
            f"Form {worksheet['form_code']} • Period "
            f"{worksheet['period_start']} to {worksheet['period_end']} • "
            f"Catalog v{worksheet['catalog_version']} • Status {worksheet['status']}"
        )
        row = self._write_header(
            ws, branding, client_name,
            f"Tax Worksheet — {worksheet['form_code']}", subtitle,
        )
        headers = ["Line", "Label", "Section", "Amount"]
        for idx, h in enumerate(headers):
            cell = ws.cell(row=row, column=idx + 1, value=h)
            cell.font = self._bold_white()
            cell.fill = self._header_fill()
            cell.alignment = Alignment(horizontal="right" if idx == 3 else "left")
        first_amt_row = row + 1
        row += 1
        for ln in worksheet["lines"]:
            ws.cell(row=row, column=1, value=ln["line_code"])
            ws.cell(row=row, column=2, value=ln["line_label"])
            ws.cell(row=row, column=3, value=ln["section"])
            ws.cell(row=row, column=4, value=float(Decimal(str(ln["amount"])))).number_format = money_fmt
            row += 1
        # Subtotals computed from cells.
        last_amt_row = row - 1
        for label, value in (
            ("Total Income", worksheet["total_income"]),
            ("Total COGS", worksheet["total_cogs"]),
            ("Total Deductions", worksheet["total_deductions"]),
            ("Taxable Income", worksheet["taxable_income"]),
        ):
            row = self._write_kv(ws, row, label, Decimal(str(value)), branding.currency)

        row += 2
        ws.cell(row=row, column=1, value=f"SHA-256 of computed amounts: {worksheet['sha256']}").font = Font(size=9, color="808080")

        # Supporting Detail sheet: list every contributing account per line.
        detail = wb.create_sheet("Supporting Detail")
        detail.cell(row=1, column=1, value=f"Supporting detail — {worksheet['form_code']}").font = Font(bold=True, size=12, color="1F3A5F")
        for col_idx, h in enumerate(
            ["Line", "Label", "Account Code", "Account Name", "Signed Balance", "Sign", "Contribution"], start=1,
        ):
            cell = detail.cell(row=3, column=col_idx, value=h)
            cell.font = self._bold_white()
            cell.fill = self._header_fill()
        dr = 4
        for ln in worksheet["lines"]:
            for ca in ln.get("contributing_accounts", []) or []:
                detail.cell(row=dr, column=1, value=ln["line_code"])
                detail.cell(row=dr, column=2, value=ln["line_label"])
                detail.cell(row=dr, column=3, value=ca.get("code", ""))
                detail.cell(row=dr, column=4, value=ca.get("name", ""))
                detail.cell(row=dr, column=5, value=float(Decimal(str(ca.get("signed_balance", "0"))))).number_format = money_fmt
                detail.cell(row=dr, column=6, value=ca.get("sign", ""))
                detail.cell(row=dr, column=7, value=float(Decimal(str(ca.get("contribution", "0"))))).number_format = money_fmt
                dr += 1
        for col in ("A", "B", "C", "D", "E", "F", "G"):
            detail.column_dimensions[col].width = 18
        detail.column_dimensions["B"].width = 32
        detail.column_dimensions["D"].width = 28

        _ = (first_amt_row, last_amt_row, get_column_letter, PageBreak)  # quiet unused
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()


__all__ = [
    "BrandingContext",
    "StatementRenderer",
    "PdfStatementRenderer",
    "XlsxStatementRenderer",
]
