"""Membership-backed authorization (`app_authz_source='membership'`).

These tests cover the path where the token establishes only *who* the caller
is and the firm/client/scope come from `firm_membership` rows.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.auth import AuthIdentity
from app.db.session import subject_session, tenant_session
from app.db.tenant import AccessScope
from app.domain.identity_resolution import (
    AmbiguousContextError,
    NoMembershipError,
    UnknownContextError,
    list_memberships,
    resolve_identity,
)
from app.main import create_app
from app.models.enums import MembershipStatus, StaffRole
from app.models.identity import FirmMembership, UserAccount
from app.security.auth import mint_test_token, reset_identity_provider
from tests.conftest import SeededWorld, ctx_firm


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _seed_member(
    firm_id: UUID,
    subject: str,
    role: StaffRole,
    *,
    client_id: UUID | None = None,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> UUID:
    """Create a user + membership. Writes need firm scope, so use tenant_session."""
    with tenant_session(ctx_firm(firm_id)) as sess:
        user = sess.query(UserAccount).filter_by(subject=subject).one_or_none()
        if user is None:
            user = UserAccount(id=uuid4(), subject=subject, email=f"{subject}@t.test")
            sess.add(user)
            sess.flush()
        sess.add(
            FirmMembership(
                id=uuid4(),
                firm_id=firm_id,
                user_id=user.id,
                client_id=client_id,
                role=role,
                status=status,
            )
        )
        sess.flush()
        return user.id


def _resolve(subject: str, **kw) -> AuthIdentity:
    with subject_session(subject) as sess:
        return resolve_identity(sess, subject=subject, **kw)


# --------------------------------------------------------------------------- #
# Resolution semantics
# --------------------------------------------------------------------------- #
def test_single_staff_membership_resolves_to_firm_scope(world: SeededWorld) -> None:
    _seed_member(world.firm_a, "staff-1", StaffRole.MANAGER)

    identity = _resolve("staff-1")

    assert identity.subject == "staff-1"
    assert identity.firm_id == world.firm_a
    assert identity.scope is AccessScope.FIRM
    assert identity.client_id is None


def test_portal_membership_resolves_to_that_client_only(world: SeededWorld) -> None:
    _seed_member(
        world.firm_a,
        "portal-1",
        StaffRole.CLIENT_PORTAL,
        client_id=world.a1.client_id,
    )

    identity = _resolve("portal-1")

    assert identity.scope is AccessScope.CLIENT
    assert identity.client_id == world.a1.client_id
    assert identity.firm_id == world.firm_a


def test_no_membership_is_rejected(world: SeededWorld) -> None:
    """A perfectly valid token for someone we've never heard of gets nothing."""
    with pytest.raises(NoMembershipError):
        _resolve("nobody")


def test_disabled_membership_is_ignored(world: SeededWorld) -> None:
    """Disabling a member must take effect immediately, not at token expiry."""
    _seed_member(
        world.firm_a, "ex-staff", StaffRole.STAFF, status=MembershipStatus.DISABLED
    )

    with pytest.raises(NoMembershipError):
        _resolve("ex-staff")


def test_multiple_memberships_require_explicit_choice(world: SeededWorld) -> None:
    _seed_member(world.firm_a, "multi", StaffRole.MANAGER)
    _seed_member(world.firm_b, "multi", StaffRole.STAFF)

    with pytest.raises(AmbiguousContextError) as exc:
        _resolve("multi")

    assert {o.firm_id for o in exc.value.options} == {world.firm_a, world.firm_b}


def test_explicit_choice_disambiguates(world: SeededWorld) -> None:
    _seed_member(world.firm_a, "multi", StaffRole.MANAGER)
    _seed_member(world.firm_b, "multi", StaffRole.STAFF)

    identity = _resolve("multi", requested_firm_id=world.firm_b)

    assert identity.firm_id == world.firm_b


def test_requested_firm_cannot_grant_unheld_access(world: SeededWorld) -> None:
    """The context hint is a filter, never a grant. This is the escalation test."""
    _seed_member(world.firm_a, "staff-a", StaffRole.MANAGER)

    with pytest.raises(UnknownContextError):
        _resolve("staff-a", requested_firm_id=world.firm_b)


def test_portal_user_cannot_request_a_different_client(world: SeededWorld) -> None:
    _seed_member(
        world.firm_a,
        "portal-1",
        StaffRole.CLIENT_PORTAL,
        client_id=world.a1.client_id,
    )

    with pytest.raises(UnknownContextError):
        _resolve(
            "portal-1",
            requested_firm_id=world.firm_a,
            requested_client_id=world.a2.client_id,
        )


# --------------------------------------------------------------------------- #
# Database-level guarantees
# --------------------------------------------------------------------------- #
def test_portal_membership_without_client_is_rejected_by_db(
    world: SeededWorld,
) -> None:
    """ck_firm_membership_client_scope stops the dangerous shape at the source."""
    with pytest.raises(IntegrityError):
        _seed_member(world.firm_a, "bad-portal", StaffRole.CLIENT_PORTAL)


def test_staff_membership_with_client_is_rejected_by_db(world: SeededWorld) -> None:
    with pytest.raises(IntegrityError):
        _seed_member(
            world.firm_a, "bad-staff", StaffRole.STAFF, client_id=world.a1.client_id
        )


def test_self_read_policy_hides_other_users_memberships(world: SeededWorld) -> None:
    """p_self_read must widen access by exactly one thing: your own rows.

    If this leaks, the login lookup becomes a firm-wide roster disclosure.
    """
    _seed_member(world.firm_a, "alice", StaffRole.MANAGER)
    _seed_member(world.firm_b, "bob", StaffRole.STAFF)

    with subject_session("alice") as sess:
        rows = sess.query(FirmMembership).all()

    assert len(rows) == 1
    assert rows[0].firm_id == world.firm_a


def test_subject_session_exposes_no_tenant_data(world: SeededWorld) -> None:
    """The login session must not become a back door into client records."""
    from app.models.accounting import Client

    with subject_session("alice") as sess:
        assert sess.query(Client).all() == []


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def _membership_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip app_authz_source to 'membership' for the request path.

    `app.api.auth` imports get_settings lazily inside the function, so patching
    it on `app.core.config` is what takes effect.
    """
    from app.core.config import get_settings

    patched = get_settings().model_copy(update={"app_authz_source": "membership"})
    monkeypatch.setattr("app.core.config.get_settings", lambda: patched)


def test_endpoint_uses_membership_not_token_claims(
    client: TestClient, world: SeededWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token claiming firm B must still land in firm A if that's the membership.

    This is the whole point of the change: claims are no longer authoritative.
    """
    _seed_member(world.firm_a, "alice", StaffRole.MANAGER)
    _membership_mode(monkeypatch)

    token = mint_test_token(sub="alice", firm_id=world.firm_b, role="firm_staff")
    resp = client.get("/clients", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    returned = {c["id"] for c in resp.json()}
    assert returned == {str(world.a1.client_id), str(world.a2.client_id)}


def test_endpoint_without_membership_is_forbidden_not_unauthorized(
    client: TestClient, world: SeededWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """403, not 401 — a 401 would send the SPA into a sign-in redirect loop."""
    _membership_mode(monkeypatch)

    token = mint_test_token(sub="stranger", firm_id=world.firm_a, role="firm_staff")
    resp = client.get("/clients", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 403, resp.text


def test_endpoint_with_two_memberships_asks_for_a_choice(
    client: TestClient, world: SeededWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_member(world.firm_a, "multi", StaffRole.MANAGER)
    _seed_member(world.firm_b, "multi", StaffRole.STAFF)
    _membership_mode(monkeypatch)

    token = mint_test_token(sub="multi", firm_id=world.firm_a, role="firm_staff")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/clients", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "context_required"

    chosen = client.get(
        "/clients", headers={**headers, "X-CTAA-Firm": str(world.firm_b)}
    )
    assert chosen.status_code == 200, chosen.text


def test_auth_context_lists_available_contexts(
    client: TestClient, world: SeededWorld
) -> None:
    _seed_member(world.firm_a, "multi", StaffRole.MANAGER)
    _seed_member(
        world.firm_b,
        "multi",
        StaffRole.CLIENT_PORTAL,
        client_id=world.b1.client_id,
    )

    token = mint_test_token(sub="multi", firm_id=world.firm_a, role="firm_staff")
    resp = client.get("/auth/context", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subject"] == "multi"
    by_firm = {o["firm_id"]: o for o in body["options"]}
    assert by_firm[str(world.firm_a)]["scope"] == "firm"
    assert by_firm[str(world.firm_b)]["scope"] == "client"
    assert by_firm[str(world.firm_b)]["client_id"] == str(world.b1.client_id)


def test_auth_context_requires_a_token(client: TestClient) -> None:
    assert client.get("/auth/context").status_code == 401


def test_auth_context_is_empty_for_unknown_user(
    client: TestClient, world: SeededWorld
) -> None:
    token = mint_test_token(sub="stranger", firm_id=world.firm_a, role="firm_staff")
    resp = client.get("/auth/context", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["options"] == []


def test_list_memberships_returns_display_names(world: SeededWorld) -> None:
    _seed_member(world.firm_a, "alice", StaffRole.MANAGER)

    with subject_session("alice") as sess:
        options = list_memberships(sess, subject="alice")

    assert len(options) == 1
    assert options[0].role is StaffRole.MANAGER


# --------------------------------------------------------------------------- #
# Staff team API must not hand out portal access
# --------------------------------------------------------------------------- #
def test_team_invite_rejects_client_portal_role(
    client: TestClient, world: SeededWorld
) -> None:
    token = mint_test_token(sub="owner-a", firm_id=world.firm_a, role="firm_staff")
    resp = client.post(
        "/team/invites",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "x@y.test", "role": "client_portal", "expires_in_days": 7},
    )

    assert resp.status_code == 422, resp.text
