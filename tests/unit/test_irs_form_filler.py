"""Tests for IrsFormFiller — official IRS PDF template fill."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.domain.irs_form_fields import LINES, template_path
from app.domain.irs_form_filler import (
    IrsFormFieldMissingError,
    IrsFormFiller,
    TaxFillerContext,
    _fmt_amount,
)
from app.models.enums import TaxFormCode


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read_filled_values(pdf_bytes: bytes) -> dict[str, str]:
    """Read back all non-empty AcroForm /V values keyed by leaf field name."""
    import io
    r = PdfReader(io.BytesIO(pdf_bytes))
    out: dict[str, str] = {}
    for k, v in (r.get_fields() or {}).items():
        val = v.get("/V")
        if val is None or val == "" or val == "/Off":
            continue
        out[k.rsplit(".", 1)[-1]] = str(val)
    return out


def _ctx() -> TaxFillerContext:
    return TaxFillerContext(
        client_name="Acme Demo Corp",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        ein="12-3456789",
        address_line="123 Main Street",
        city="Anytown",
        state="CA",
        zip_code="94000",
    )


# --------------------------------------------------------------------------- #
# Bundled templates
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", list(TaxFormCode))
def test_template_pdf_exists_on_disk(code: TaxFormCode) -> None:
    assert template_path(code).exists(), (
        f"missing IRS PDF template for {code.value} at {template_path(code)}"
    )


@pytest.mark.parametrize("code", list(TaxFormCode))
def test_every_line_in_map_resolves_against_real_pdf(code: TaxFormCode) -> None:
    """Each `Page1[0].fN_M[0]` suffix must match a real field in the PDF.

    This is the regression guard for stale field maps: if the IRS publishes
    a new revision that renames `f1_14` to `f1_15`, this test fires.
    """
    pdf = PdfReader(str(template_path(code)))
    all_paths = list((pdf.get_fields() or {}).keys())
    line_map = LINES.get(code) or {}
    assert line_map, f"no line map registered for {code.value}"
    for line_code, suffix in line_map.items():
        resolved = IrsFormFiller._resolve_field(suffix, all_paths)
        assert resolved is not None, (
            f"{code.value} line {line_code!r} suffix {suffix!r} is unresolved"
        )


# --------------------------------------------------------------------------- #
# Amount formatting
# --------------------------------------------------------------------------- #
def test_fmt_amount_blanks_zero() -> None:
    assert _fmt_amount(Decimal("0")) == ""
    assert _fmt_amount("0.00") == ""
    assert _fmt_amount(0) == ""


def test_fmt_amount_rounds_half_up_to_whole_dollars() -> None:
    assert _fmt_amount("100.49") == "100"
    assert _fmt_amount("100.50") == "101"
    assert _fmt_amount("100.51") == "101"


def test_fmt_amount_uses_thousands_separator() -> None:
    assert _fmt_amount("1234567") == "1,234,567"
    assert _fmt_amount(Decimal("43010.35")) == "43,010"


def test_fmt_amount_handles_negative() -> None:
    # IRS forms don't use parens here; -100 stays as "-100".
    assert _fmt_amount(Decimal("-100")) == "-100"


# --------------------------------------------------------------------------- #
# End-to-end fill
# --------------------------------------------------------------------------- #
def test_render_fills_header_and_amounts_for_f1120() -> None:
    worksheet = {
        "form_code": "F1120",
        "lines": [
            {"line_code": "1a", "amount": "43010.35", "line_label": "x", "section": "income"},
            {"line_code": "2",  "amount": "854.47",   "line_label": "x", "section": "cogs"},
            {"line_code": "12", "amount": "5000",     "line_label": "x", "section": "deductions"},
            {"line_code": "26", "amount": "850",      "line_label": "x", "section": "deductions"},
        ],
    }
    pdf = IrsFormFiller().render(
        form_code=TaxFormCode.F1120, worksheet=worksheet, ctx=_ctx(),
    )
    assert pdf.startswith(b"%PDF")
    values = _read_filled_values(pdf)
    # Header
    assert values.get("f1_4[0]") == "Acme Demo Corp"
    assert values.get("f1_11[0]") == "12-3456789"
    assert values.get("f1_1[0]") == "01/01"
    assert values.get("f1_2[0]") == "12/31"
    assert values.get("f1_3[0]") == "24"
    # Line 1a → f1_14, Line 2 → f1_17, Line 12 → f1_27, Line 26 → f1_41
    assert values.get("f1_14[0]") == "43,010"
    assert values.get("f1_17[0]") == "854"
    assert values.get("f1_27[0]") == "5,000"
    assert values.get("f1_41[0]") == "850"


def test_zero_line_is_blank_not_zero() -> None:
    worksheet = {
        "form_code": "F1120",
        "lines": [
            {"line_code": "1a", "amount": "1000", "line_label": "x", "section": "income"},
            {"line_code": "1b", "amount": "0",    "line_label": "x", "section": "income"},
        ],
    }
    pdf = IrsFormFiller().render(
        form_code=TaxFormCode.F1120, worksheet=worksheet, ctx=_ctx(),
    )
    values = _read_filled_values(pdf)
    assert values.get("f1_14[0]") == "1,000"  # 1a filled
    assert "f1_15[0]" not in values            # 1b blank, not "0"


def test_unmapped_nonzero_line_raises() -> None:
    # F1120 has no mapping for line "99" (it doesn't exist on the form).
    worksheet = {
        "form_code": "F1120",
        "lines": [
            {"line_code": "99", "amount": "100", "line_label": "x", "section": "income"},
        ],
    }
    with pytest.raises(IrsFormFieldMissingError):
        IrsFormFiller().render(
            form_code=TaxFormCode.F1120, worksheet=worksheet, ctx=_ctx(),
        )


def test_unmapped_zero_line_is_silently_skipped() -> None:
    worksheet = {
        "form_code": "F1120",
        "lines": [
            {"line_code": "99", "amount": "0", "line_label": "x", "section": "income"},
            {"line_code": "1a", "amount": "500", "line_label": "x", "section": "income"},
        ],
    }
    pdf = IrsFormFiller().render(
        form_code=TaxFormCode.F1120, worksheet=worksheet, ctx=_ctx(),
    )
    values = _read_filled_values(pdf)
    assert values.get("f1_14[0]") == "500"


def test_render_all_four_forms_smoke() -> None:
    """Each registered form must render without raising, given a minimal
    revenue + COGS worksheet."""
    for code in TaxFormCode:
        worksheet = {
            "form_code": code.value,
            "lines": [
                {"line_code": "1a" if code is not TaxFormCode.F1040SC else "1",
                 "amount": "10000", "line_label": "x", "section": "income"},
                {"line_code": "2" if code is not TaxFormCode.F1040SC else "4",
                 "amount": "3000", "line_label": "x", "section": "cogs"},
            ],
        }
        pdf = IrsFormFiller().render(
            form_code=code, worksheet=worksheet, ctx=_ctx(),
        )
        assert pdf.startswith(b"%PDF"), f"{code.value} did not render valid PDF"


def test_readonly_flag_is_set_on_filled_fields() -> None:
    worksheet = {
        "form_code": "F1120",
        "lines": [
            {"line_code": "1a", "amount": "1000", "line_label": "x", "section": "income"},
        ],
    }
    pdf = IrsFormFiller().render(
        form_code=TaxFormCode.F1120, worksheet=worksheet, ctx=_ctx(),
    )
    import io
    r = PdfReader(io.BytesIO(pdf))
    fields = r.get_fields() or {}
    # f1_14[0] is line 1a — must have the read-only flag bit set.
    for k, v in fields.items():
        if k.endswith(".f1_14[0]"):
            ff = int(v.get("/Ff") or 0)
            assert ff & 1, "ReadOnly bit not set on filled field"
            return
    pytest.fail("f1_14[0] not present in filled PDF fields")
