"""Render a pytest JUnit XML result into the GitHub Actions run summary.

Written in-tree rather than pulling a third-party reporting action: this
repo handles client financial data, and the test-evidence path is exactly
where an unreviewed supply-chain dependency would hurt most.

Usage:
    python scripts/ci_test_summary.py <junit.xml> [coverage.xml]

Writes markdown to $GITHUB_STEP_SUMMARY (stdout when unset, so it is
runnable locally).
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

# Maps a test module onto the thing a reader actually cares about. Keys match
# the dotted `classname` pytest writes into the JUnit report.
SUITES = {
    "tests.isolation": "Tenant isolation",
    "tests.security": "Security & access control",
    "tests.integration": "API integration",
    "tests.unit": "Domain logic",
}


def _suite_for(classname: str) -> str:
    for prefix, label in SUITES.items():
        if classname.startswith(prefix):
            return label
    return "Other"


def _coverage_pct(path: Path) -> float | None:
    if not path.is_file():
        return None
    root = ET.parse(path).getroot()
    rate = root.get("line-rate")
    return round(float(rate) * 100, 1) if rate is not None else None


def main(argv: list[str]) -> int:
    junit = Path(argv[1])
    if not junit.is_file():
        print(f"No JUnit report at {junit} — the test run likely crashed.")
        return 0

    root = ET.parse(junit).getroot()
    cases = root.iter("testcase")

    tally: dict[str, dict[str, int]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "skipped": 0}
    )
    failures: list[tuple[str, str]] = []

    for case in cases:
        suite = _suite_for(case.get("classname", ""))
        if case.find("failure") is not None or case.find("error") is not None:
            tally[suite]["failed"] += 1
            failures.append((case.get("classname", "?"), case.get("name", "?")))
        elif case.find("skipped") is not None:
            tally[suite]["skipped"] += 1
        else:
            tally[suite]["passed"] += 1

    total = {k: sum(v[k] for v in tally.values()) for k in ("passed", "failed", "skipped")}
    verdict = "PASSED" if total["failed"] == 0 else "FAILED"
    icon = "✅" if total["failed"] == 0 else "❌"

    lines = [
        f"## {icon} Test suite {verdict}",
        "",
        f"**{total['passed']} passed**, {total['failed']} failed, "
        f"{total['skipped']} skipped",
        "",
        "| Suite | Passed | Failed | Skipped |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label in list(SUITES.values()) + ["Other"]:
        if label not in tally:
            continue
        t = tally[label]
        lines.append(
            f"| {label} | {t['passed']} | {t['failed']} | {t['skipped']} |"
        )

    if len(argv) > 2:
        pct = _coverage_pct(Path(argv[2]))
        if pct is not None:
            lines += ["", f"**Line coverage:** {pct}%"]

    if failures:
        lines += ["", "### Failures", ""]
        lines += [f"- `{cls}::{name}`" for cls, name in failures[:50]]
        if len(failures) > 50:
            lines.append(f"- …and {len(failures) - 50} more")

    out = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
