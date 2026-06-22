"""Fill official IRS PDF templates with tax-worksheet values.

`IrsFormFiller.render(worksheet, client_name, period_start, period_end)`
opens the bundled IRS PDF for the form, fills every mapped header and
line field with our computed values, marks the fields read-only so the
output cannot be edited in Acrobat / Preview, and returns the bytes.

Decimal money values are formatted as plain integers (IRS forms expect
whole dollars rounded). Lines whose amount is exactly zero are left
blank so the form looks like a hand-filled return rather than a
diagnostic dump.

Coverage is Page 1 only (income statement + deductions). Schedules,
balance-sheet pages, K-1 etc. are intentionally not filled — they
require data the worksheet engine does not compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, NumberObject

from app.domain import irs_form_fields as ff
from app.models.enums import TaxFormCode


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class IrsFormTemplateMissingError(Exception):
    """The bundled IRS PDF template for the requested form is missing."""


class IrsFormFieldMissingError(Exception):
    """A worksheet line has no matching field in the IRS template field map.

    Surfaces loudly so an unmapped line in our catalog cannot silently
    drop a number on the rendered return.
    """


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fmt_amount(value: str | Decimal | float | int) -> str:
    """Format an amount as a whole-dollar IRS-style string.

    Returns "" for exactly zero so the form looks naturally blank where
    a taxpayer would not have filled in a value.
    """
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    if d == 0:
        return ""
    rounded = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    # IRS forms do not use comma separators inside the printed amount,
    # but Acrobat-style widgets render cleanly with commas — keep them.
    return f"{int(rounded):,}"


def _fmt_date_mmdd(d: date | None) -> str:
    return d.strftime("%m/%d") if d else ""


def _fmt_year(d: date | None) -> str:
    return d.strftime("%y") if d else ""


def _flatten_writer_fields(writer: PdfWriter) -> None:
    """Set the ReadOnly bit on every AcroForm field so values cannot be
    edited after rendering. pypdf does not implement true flattening
    (which would burn the values into the page content stream), so we
    rely on the viewer respecting the /Ff ReadOnly flag (bit 1).
    """
    READ_ONLY_FLAG = 1
    for page in writer.pages:
        annots = page.get("/Annots") or []
        for annot in annots:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            flags = int(obj.get("/Ff") or 0)
            obj[NameObject("/Ff")] = NumberObject(flags | READ_ONLY_FLAG)
            # NeedAppearances ensures viewers regenerate appearance streams
            # for any field whose value we changed.
    root_acroform = writer._root_object.get("/AcroForm")
    if root_acroform is not None:
        root_acroform.update({NameObject("/NeedAppearances"): BooleanObject(True)})


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TaxFillerContext:
    """Everything the filler needs that is not the worksheet payload."""

    client_name: str
    period_start: date | None
    period_end: date | None
    # The following are optional — IRS templates allow blank values and we
    # don't (yet) store EIN / address on the Client model.
    ein: str = ""
    address_line: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    date_incorporated: str = ""
    total_assets: str = ""  # printable, e.g. "1,234,567"
    ssn: str = ""  # F1040SC only


# --------------------------------------------------------------------------- #
# Filler
# --------------------------------------------------------------------------- #
class IrsFormFiller:
    """Fill the bundled IRS template for `form_code` and return PDF bytes."""

    def render(
        self,
        *,
        form_code: TaxFormCode,
        worksheet: dict[str, Any],
        ctx: TaxFillerContext,
    ) -> bytes:
        path = ff.template_path(form_code)
        if not path.exists():
            raise IrsFormTemplateMissingError(
                f"IRS template for {form_code.value} not found at {path}",
            )
        line_map = ff.LINES.get(form_code) or {}
        if not line_map:
            raise IrsFormFieldMissingError(
                f"No AcroForm line map registered for {form_code.value}",
            )

        # Build the {acroform_field_path: value} dict.
        values = self._build_header_values(form_code, ctx)
        values.update(self._build_line_values(form_code, worksheet))

        # Resolve our suffix paths (e.g. `Page1[0].f1_14[0]`) against the
        # PDF's actual fully-qualified field names. We do a substring
        # match because pypdf prefixes every key with `topmostSubform[0].`.
        reader = PdfReader(str(path))
        writer = PdfWriter(clone_from=reader)
        all_field_paths = list((reader.get_fields() or {}).keys())
        resolved: dict[str, str] = {}
        for suffix, val in values.items():
            full = self._resolve_field(suffix, all_field_paths)
            if full is None:
                raise IrsFormFieldMissingError(
                    f"AcroForm field for suffix {suffix!r} not found in "
                    f"{form_code.value} template; field map is stale.",
                )
            resolved[full] = val

        # Apply to every page that has form widgets. Empty strings ARE valid
        # values and explicitly blank the field.
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(
                    page, resolved, auto_regenerate=False,
                )
            except Exception:  # noqa: BLE001
                # update_page_form_field_values raises if the page has no
                # form fields at all — fine, just skip.
                continue

        _flatten_writer_fields(writer)
        buf = BytesIO()
        writer.write(buf)
        return buf.getvalue()

    # --- internals ------------------------------------------------------ #

    @staticmethod
    def _resolve_field(suffix: str, all_paths: list[str]) -> str | None:
        """Match a `Page<n>[0].<leaf>[<i>]` suffix against full paths.

        IRS PDFs group fields under varying intermediate nodes
        (`PgHeader[0]`, `NameFieldsReadOrder[0]`,
        `HeaderAddress_ReadOrder[0].CalendarName_ReadOrder[0]`, ...) that
        differ per form. To stay tolerant of those wrappers we match on
        the page tag + leaf field name only.
        """
        # Expect suffix in the form "PageN[0].<leaf>"
        try:
            page_tag, leaf = suffix.split(".", 1)
        except ValueError:
            page_tag, leaf = "", suffix
        for full in all_paths:
            if page_tag and page_tag not in full:
                continue
            if full.endswith("." + leaf):
                return full
        return None

    @staticmethod
    def _build_header_values(
        form_code: TaxFormCode, ctx: TaxFillerContext,
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        hdr = ff.HEADERS.get(form_code) or {}
        for key, val in (
            (ff.HK_NAME,            ctx.client_name),
            (ff.HK_BUSINESS_NAME,   ctx.client_name),  # F1040SC re-uses client name
            (ff.HK_ADDRESS,         ctx.address_line),
            (ff.HK_CITY,            ctx.city),
            (ff.HK_STATE,           ctx.state),
            (ff.HK_ZIP,             ctx.zip_code),
            (ff.HK_EIN,             ctx.ein),
            (ff.HK_SSN,             ctx.ssn),
            (ff.HK_TAX_YEAR_BEGIN,  _fmt_date_mmdd(ctx.period_start)),
            (ff.HK_TAX_YEAR_END,    _fmt_date_mmdd(ctx.period_end)),
            (ff.HK_TAX_YEAR_4DIGIT, _fmt_year(ctx.period_end)),
            (ff.HK_DATE_INCORP,     ctx.date_incorporated),
            (ff.HK_TOTAL_ASSETS,    ctx.total_assets),
        ):
            field_path = hdr.get(key)
            if field_path and val:
                out[field_path] = val
        return out

    @staticmethod
    def _build_line_values(
        form_code: TaxFormCode, worksheet: dict[str, Any],
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        line_map = ff.LINES.get(form_code) or {}
        unmapped: list[str] = []
        for ln in worksheet.get("lines", []):
            code = ln["line_code"]
            field_path = line_map.get(code)
            if field_path is None:
                # Only flag lines that actually have non-zero amounts. A
                # zero line is harmless to skip.
                amt = Decimal(str(ln.get("amount", "0")))
                if amt != 0:
                    unmapped.append(code)
                continue
            out[field_path] = _fmt_amount(ln["amount"])
        if unmapped:
            raise IrsFormFieldMissingError(
                f"Worksheet for {form_code.value} has non-zero amounts on "
                f"unmapped lines: {sorted(set(unmapped))}",
            )
        return out


__all__ = [
    "IrsFormFiller",
    "TaxFillerContext",
    "IrsFormTemplateMissingError",
    "IrsFormFieldMissingError",
]
