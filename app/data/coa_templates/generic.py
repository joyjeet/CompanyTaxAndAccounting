"""Generic industry overlay — DRAFT v0.1.

The "I don't know which industry yet" fallback. Adds nothing beyond the
general base; clients picking `Industry.GENERIC` get a clean tree they
extend manually. Still emitted as a row so onboarding code can
unconditionally attach an overlay.
"""
from __future__ import annotations

from app.models.enums import CoaTemplateKind, Industry

TEMPLATE = {
    "key": "industry:generic",
    "display_name": "Generic Industry (No Overlay)",
    "kind": CoaTemplateKind.INDUSTRY_OVERLAY,
    "industry": Industry.GENERIC,
    "version": "0.1-draft",
    "nodes": [],
}
