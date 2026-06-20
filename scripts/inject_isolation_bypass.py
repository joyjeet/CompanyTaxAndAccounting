"""Deliberately introduce a tenant-isolation bypass into the codebase.

This script is used ONLY by the `isolation-gate-proof` CI workflow. It edits
the live `app/db/session.py` file to comment out the per-request `SET LOCAL
app.current_firm` call. Test suite must then fail. If it does, the gate is
real and provable.

Do NOT run this locally outside the CI workflow.
"""
from __future__ import annotations

import pathlib
import sys


def main() -> int:
    target = pathlib.Path("app/db/session.py")
    if not target.exists():
        print(f"ERROR: {target} not found", file=sys.stderr)
        return 2

    src = target.read_text()
    needle = '_set_local(sess, "app.current_firm", str(ctx.firm_id))'
    if needle not in src:
        print(
            "ERROR: expected line not found — bypass injection cannot proceed. "
            "Did the code shape change? Update inject_isolation_bypass.py to match.",
            file=sys.stderr,
        )
        return 2

    patched = src.replace(
        needle,
        '# INJECTED-BYPASS: ' + needle,
        1,
    )
    target.write_text(patched)
    print(f"Bypass injected into {target}. Tests must now fail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
