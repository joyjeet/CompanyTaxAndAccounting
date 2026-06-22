"""One-off helper: dump AcroForm widget positions for each bundled IRS form.

Run with `python scripts/inspect_irs_fields.py f1120 f1120s f1065 f1040sc`.
Prints a sorted (top-down, left-right) listing of every widget on every
page along with its short field name, type, and rect.

Used to derive the field maps in app/domain/irs_form_fields.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "app" / "data" / "irs_forms"


def _widgets_for_page(page) -> list[tuple[float, float, str, str]]:
    annots = page.get("/Annots") or []
    out: list[tuple[float, float, str, str]] = []
    for a in annots:
        obj = a.get_object()
        if obj.get("/Subtype") != "/Widget":
            continue
        # Walk parents to assemble the full qualified name.
        parts: list[str] = []
        cur = obj
        while cur is not None:
            t = cur.get("/T")
            if t:
                parts.append(str(t))
            cur = cur.get("/Parent")
        full = ".".join(reversed(parts))
        rect = obj.get("/Rect")
        if rect is None:
            continue
        x1, y1, x2, y2 = (float(v) for v in rect)
        ft = str(obj.get("/FT") or "?")
        out.append((round(y2, 1), round(x1, 1), full, ft))
    out.sort(key=lambda r: (-r[0], r[1]))
    return out


def main(forms: list[str]) -> int:
    for code in forms:
        path = TEMPLATES / f"{code}.pdf"
        if not path.exists():
            print(f"!! {code}: {path} not found", file=sys.stderr)
            continue
        r = PdfReader(str(path))
        print(f"\n========== {code} ({len(r.pages)} pages) ==========")
        for i, page in enumerate(r.pages, 1):
            widgets = _widgets_for_page(page)
            print(f"\n--- {code} page {i} ({len(widgets)} widgets) ---")
            for y, x, name, ft in widgets:
                short = name.split(".")[-1]
                print(f"  y={y:7.1f} x={x:6.1f} {ft:4s}  {short}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["f1120", "f1120s", "f1065", "f1040sc"]))
