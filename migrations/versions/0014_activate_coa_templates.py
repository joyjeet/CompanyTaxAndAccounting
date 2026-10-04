"""Activate the built-in chart-of-accounts templates.

Revision ID: 0014_activate_coa_templates
Revises: 0013_client_archive
Create Date: 2026-08-03

Migration 0008 seeded the shipped templates as `draft`, on the reasoning
that a CPA should explicitly activate a chart before it governs client
books. That is the right rule for a template a firm authors or uploads --
but it was also applied to the baseline templates that ship with the
product, and instantiation refuses to run without an ACTIVE `general`
template. The result was that a freshly provisioned environment could not
onboard a single client: creating one failed with "No ACTIVE general COA
template exists", and there was no way out.

This activates only the rows 0008 inserted, matched on their seed version,
and only while they are still untouched (`status = 'draft'`). A template a
firm has already reviewed, superseded, or replaced is left exactly as it
is, so this cannot overwrite a decision anyone made.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_activate_coa_templates"
down_revision = "0013_client_archive"
branch_labels = None
depends_on = None

# The keys and version seeded by 0008. Pinning the version means a later,
# firm-authored revision of the same key is never touched.
_SEEDED_VERSION = "0.1-draft"
_SEEDED_KEYS = (
    "general",
    "industry:generic",
    "industry:construction",
    "industry:professional_services",
    "industry:retail_ecommerce",
)

_SET_STATUS = sa.text(
    """
    UPDATE coa_template
       SET status = :new_status
     WHERE status = :old_status
       AND version = :version
       AND key IN :keys
    """
).bindparams(sa.bindparam("keys", expanding=True))


def _move(old_status: str, new_status: str) -> None:
    op.get_bind().execute(
        _SET_STATUS,
        {
            "old_status": old_status,
            "new_status": new_status,
            "version": _SEEDED_VERSION,
            "keys": list(_SEEDED_KEYS),
        },
    )


def upgrade() -> None:
    _move("draft", "active")


def downgrade() -> None:
    # Returns the shipped templates to their as-seeded state. Anything a
    # firm activated itself has a different version and is untouched.
    _move("active", "draft")
