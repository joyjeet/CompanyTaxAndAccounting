"""AcroForm field maps for official IRS PDFs.

For each form code we know the path to the bundled IRS template PDF
(`app/data/irs_forms/<code>.pdf`) and the mapping from our worksheet
line codes (e.g. "1a", "26") to the AcroForm field name inside that
PDF (e.g. `topmostSubform[0].Page1[0].f1_14[0]`).

The maps were derived once by running

    python scripts/inspect_irs_fields.py f1120 f1120s f1065 f1040sc

and reading off the (y,x) widget positions per page. Coordinates and
field IDs are stable across IRS revisions for at least the current
filing-year cycle.

Header fields are emitted via the HEADERS dict. Numeric line fields
are emitted via LINES. Anything else (checkboxes, signature blocks,
schedules on page 2+) is intentionally NOT mapped — we only fill the
income-statement portion of page 1 because that is the only thing the
worksheet engine actually computes.
"""

from __future__ import annotations

from pathlib import Path

from app.models.enums import TaxFormCode

# --------------------------------------------------------------------------- #
# Template location
# --------------------------------------------------------------------------- #
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "irs_forms"


def template_path(form_code: TaxFormCode) -> Path:
    """Return the absolute path to the bundled IRS PDF for `form_code`."""
    name = {
        TaxFormCode.F1120:   "f1120.pdf",
        TaxFormCode.F1120S:  "f1120s.pdf",
        TaxFormCode.F1065:   "f1065.pdf",
        TaxFormCode.F1040SC: "f1040sc.pdf",
    }[form_code]
    return _DATA_DIR / name


# --------------------------------------------------------------------------- #
# Header field keys (form-agnostic; each form maps as many as apply)
# --------------------------------------------------------------------------- #
HK_NAME            = "name"
HK_ADDRESS         = "address"
HK_CITY            = "city"
HK_STATE           = "state"
HK_ZIP             = "zip"
HK_EIN             = "ein"
HK_TAX_YEAR_BEGIN  = "tax_year_begin"
HK_TAX_YEAR_END    = "tax_year_end"
HK_TAX_YEAR_4DIGIT = "tax_year_4digit"
HK_DATE_INCORP     = "date_incorporated"
HK_TOTAL_ASSETS    = "total_assets"
HK_SSN             = "ssn"
HK_BUSINESS_NAME   = "business_name"


# --------------------------------------------------------------------------- #
# Per-form field maps
# --------------------------------------------------------------------------- #
# All AcroForm field names in IRS PDFs are nested under
# `topmostSubform[0].PageN[0].`. We store just the page+leaf suffix and
# pypdf will resolve via its full path. The filler uses substring match
# on the qualified name to be tolerant of minor IRS revisions.
# --------------------------------------------------------------------------- #

# Form 1120 — US C-Corporation
# Note: `get_fields()` flattens intermediate group nodes (PgHeader,
# NameFieldsReadOrder, etc.) so field suffixes are just Page1[0].fN_M[0].
_F1120_HEADERS: dict[str, str] = {
    HK_TAX_YEAR_BEGIN:  "Page1[0].f1_1[0]",
    HK_TAX_YEAR_END:    "Page1[0].f1_2[0]",
    HK_TAX_YEAR_4DIGIT: "Page1[0].f1_3[0]",
    HK_NAME:            "Page1[0].f1_4[0]",
    HK_ADDRESS:         "Page1[0].f1_5[0]",
    HK_CITY:            "Page1[0].f1_6[0]",
    HK_STATE:           "Page1[0].f1_7[0]",
    HK_ZIP:             "Page1[0].f1_8[0]",
    HK_EIN:             "Page1[0].f1_11[0]",
    HK_DATE_INCORP:     "Page1[0].f1_12[0]",
    HK_TOTAL_ASSETS:    "Page1[0].f1_13[0]",
}
_F1120_LINES: dict[str, str] = {
    "1a": "Page1[0].f1_14[0]",
    "1b": "Page1[0].f1_15[0]",
    # 1c (balance) is computed by IRS form; we don't fill explicitly but
    # could: "1c": "Page1[0].f1_16[0]",
    "2":  "Page1[0].f1_17[0]",
    # "3" (gross profit) is computed
    "4":  "Page1[0].f1_19[0]",
    "5":  "Page1[0].f1_20[0]",
    "6":  "Page1[0].f1_21[0]",
    "7":  "Page1[0].f1_22[0]",
    "8":  "Page1[0].f1_23[0]",
    "9":  "Page1[0].f1_24[0]",
    "10": "Page1[0].f1_25[0]",
    # "11" total income is computed
    "12": "Page1[0].f1_27[0]",
    "13": "Page1[0].f1_28[0]",
    "14": "Page1[0].f1_29[0]",
    "15": "Page1[0].f1_30[0]",
    "16": "Page1[0].f1_31[0]",
    "17": "Page1[0].f1_32[0]",
    "18": "Page1[0].f1_33[0]",
    "19": "Page1[0].f1_34[0]",
    "20": "Page1[0].f1_35[0]",
    "21": "Page1[0].f1_36[0]",
    "22": "Page1[0].f1_37[0]",
    "23": "Page1[0].f1_38[0]",
    "24": "Page1[0].f1_39[0]",
    "26": "Page1[0].f1_41[0]",
    # "27" total deductions is computed
}

# Form 1120-S — US S-Corporation
_F1120S_HEADERS: dict[str, str] = {
    HK_TAX_YEAR_BEGIN:  "Page1[0].f1_1[0]",
    HK_TAX_YEAR_END:    "Page1[0].f1_2[0]",
    HK_TAX_YEAR_4DIGIT: "Page1[0].f1_3[0]",
    HK_NAME:            "Page1[0].f1_4[0]",
    HK_ADDRESS:         "Page1[0].f1_5[0]",
    HK_CITY:            "Page1[0].f1_6[0]",
    HK_STATE:           "Page1[0].f1_7[0]",
    HK_ZIP:             "Page1[0].f1_8[0]",
    HK_EIN:             "Page1[0].f1_13[0]",
    HK_DATE_INCORP:     "Page1[0].f1_14[0]",
    HK_TOTAL_ASSETS:    "Page1[0].f1_15[0]",
}
_F1120S_LINES: dict[str, str] = {
    "1a": "Page1[0].f1_17[0]",
    "1b": "Page1[0].f1_18[0]",
    # 1c is computed
    "2":  "Page1[0].f1_20[0]",
    # 3 gross profit is computed
    "4":  "Page1[0].f1_22[0]",
    "5":  "Page1[0].f1_23[0]",
    # 6 total income is computed
    "7":  "Page1[0].f1_25[0]",
    "8":  "Page1[0].f1_26[0]",
    "9":  "Page1[0].f1_27[0]",
    "10": "Page1[0].f1_28[0]",
    "11": "Page1[0].f1_29[0]",
    "12": "Page1[0].f1_30[0]",
    "13": "Page1[0].f1_31[0]",
    "14": "Page1[0].f1_32[0]",
    "15": "Page1[0].f1_33[0]",
    "16": "Page1[0].f1_34[0]",
    "17": "Page1[0].f1_35[0]",
    "18": "Page1[0].f1_36[0]",
    "19": "Page1[0].f1_37[0]",
    # 20 total deductions is computed
}

# Form 1065 — US Partnership
_F1065_HEADERS: dict[str, str] = {
    HK_TAX_YEAR_BEGIN:  "Page1[0].f1_01[0]",
    HK_TAX_YEAR_END:    "Page1[0].f1_02[0]",
    HK_TAX_YEAR_4DIGIT: "Page1[0].f1_03[0]",
    HK_NAME:            "Page1[0].f1_04[0]",
    HK_ADDRESS:         "Page1[0].f1_05[0]",
    HK_CITY:            "Page1[0].f1_06[0]",
    HK_STATE:           "Page1[0].f1_08[0]",
    HK_ZIP:             "Page1[0].f1_09[0]",
    HK_EIN:             "Page1[0].f1_14[0]",
    HK_TOTAL_ASSETS:    "Page1[0].f1_16[0]",
}
_F1065_LINES: dict[str, str] = {
    "1a": "Page1[0].f1_19[0]",
    "1b": "Page1[0].f1_20[0]",
    # 1c is computed
    "2":  "Page1[0].f1_22[0]",
    # 3 gross profit is computed
    "4":  "Page1[0].f1_24[0]",
    "5":  "Page1[0].f1_25[0]",
    "6":  "Page1[0].f1_26[0]",
    "7":  "Page1[0].f1_27[0]",
    # 8 total income is computed
    "9":  "Page1[0].f1_29[0]",
    "10": "Page1[0].f1_30[0]",
    "11": "Page1[0].f1_31[0]",
    "12": "Page1[0].f1_32[0]",
    "13": "Page1[0].f1_33[0]",
    "14": "Page1[0].f1_34[0]",
    "15": "Page1[0].f1_35[0]",
    "16": "Page1[0].f1_36[0]",  # Depreciation (a)
    "17": "Page1[0].f1_39[0]",
    "18": "Page1[0].f1_40[0]",
    "19": "Page1[0].f1_41[0]",
    "20": "Page1[0].f1_42[0]",
    # 21 total deductions, 22 ordinary income are computed
}

# Form 1040 Schedule C — Sole Proprietor
_F1040SC_HEADERS: dict[str, str] = {
    HK_NAME:          "Page1[0].f1_1[0]",
    HK_SSN:           "Page1[0].f1_2[0]",
    HK_BUSINESS_NAME: "Page1[0].f1_5[0]",
    HK_EIN:           "Page1[0].f1_6[0]",
    HK_ADDRESS:       "Page1[0].f1_7[0]",
    HK_CITY:          "Page1[0].f1_8[0]",
}
_F1040SC_LINES: dict[str, str] = {
    # Part I — Income
    "1":   "Page1[0].f1_10[0]",
    "2":   "Page1[0].f1_11[0]",
    # 3 (line 1 - line 2) is computed
    "4":   "Page1[0].f1_13[0]",
    # 5 gross profit computed
    "6":   "Page1[0].f1_15[0]",
    # 7 gross income computed
    # Part II — Expenses (interleaved left/right columns)
    "8":   "Page1[0].f1_17[0]",
    "9":   "Page1[0].f1_18[0]",
    "10":  "Page1[0].f1_19[0]",
    "11":  "Page1[0].f1_20[0]",
    "12":  "Page1[0].f1_21[0]",
    "13":  "Page1[0].f1_22[0]",
    "14":  "Page1[0].f1_23[0]",
    "15":  "Page1[0].f1_24[0]",
    "16a": "Page1[0].f1_25[0]",
    "16b": "Page1[0].f1_26[0]",
    "17":  "Page1[0].f1_27[0]",
    "18":  "Page1[0].f1_28[0]",
    "19":  "Page1[0].f1_29[0]",
    "20a": "Page1[0].f1_30[0]",
    "20b": "Page1[0].f1_31[0]",
    "21":  "Page1[0].f1_32[0]",
    "22":  "Page1[0].f1_33[0]",
    "23":  "Page1[0].f1_34[0]",
    "24a": "Page1[0].f1_35[0]",
    "24b": "Page1[0].f1_36[0]",
    "25":  "Page1[0].f1_37[0]",
    "26":  "Page1[0].f1_38[0]",
    "27a": "Page1[0].f1_39[0]",
    # 28 total, 29 tentative profit, 31 net profit are computed
}


# --------------------------------------------------------------------------- #
# Public lookup tables
# --------------------------------------------------------------------------- #
HEADERS: dict[TaxFormCode, dict[str, str]] = {
    TaxFormCode.F1120:   _F1120_HEADERS,
    TaxFormCode.F1120S:  _F1120S_HEADERS,
    TaxFormCode.F1065:   _F1065_HEADERS,
    TaxFormCode.F1040SC: _F1040SC_HEADERS,
}

LINES: dict[TaxFormCode, dict[str, str]] = {
    TaxFormCode.F1120:   _F1120_LINES,
    TaxFormCode.F1120S:  _F1120S_LINES,
    TaxFormCode.F1065:   _F1065_LINES,
    TaxFormCode.F1040SC: _F1040SC_LINES,
}

# Computed lines are totals/subtotals that IRS forms often auto-calculate in
# interactive viewers. We still write them explicitly so downloaded PDFs have
# stable values in all viewers.
COMPUTED_LINE_FIELDS: dict[TaxFormCode, dict[str, str]] = {
    TaxFormCode.F1120S: {
        "1c": "Page1[0].f1_19[0]",
        "3": "Page1[0].f1_21[0]",
        "6": "Page1[0].f1_24[0]",
        "21": "Page1[0].f1_38[0]",
        "22": "Page1[0].f1_39[0]",
    },
}


def line_field(form_code: TaxFormCode, line_code: str) -> str | None:
    """Return the AcroForm field path for a worksheet line, or None."""
    return LINES.get(form_code, {}).get(line_code)


def header_field(form_code: TaxFormCode, key: str) -> str | None:
    """Return the AcroForm field path for a header key, or None."""
    return HEADERS.get(form_code, {}).get(key)


__all__ = [
    "template_path",
    "header_field",
    "line_field",
    "HEADERS",
    "LINES",
    "COMPUTED_LINE_FIELDS",
    "HK_NAME",
    "HK_ADDRESS",
    "HK_CITY",
    "HK_STATE",
    "HK_ZIP",
    "HK_EIN",
    "HK_TAX_YEAR_BEGIN",
    "HK_TAX_YEAR_END",
    "HK_TAX_YEAR_4DIGIT",
    "HK_DATE_INCORP",
    "HK_TOTAL_ASSETS",
    "HK_SSN",
    "HK_BUSINESS_NAME",
]
