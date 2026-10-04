"""SQLAlchemy engine + session helpers.

Two engines:
    * `engine`             — runtime app role (NOSUPERUSER, NOBYPASSRLS).
    * owner engine (lazy)  — owner role; ONLY for migrations and test bootstrap.

`tenant_session` is the only sanctioned way to talk to the DB at runtime: it opens
a transaction, sets the three RLS GUCs with SET LOCAL (so they cannot leak to a
sibling pooled connection), then yields the session. On exit, the transaction is
committed or rolled back; SET LOCAL is dropped automatically.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.tenant import AccessScope, TenantContext

_settings = get_settings()

# Runtime engine. pool_pre_ping handles dropped connections gracefully.
engine: Engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@lru_cache(maxsize=1)
def get_owner_engine() -> Engine:
    """Owner-role engine. Used ONLY for migrations / test setup. Never for app traffic."""
    return create_engine(_settings.database_owner_url, pool_pre_ping=True, future=True)


@contextmanager
def owner_session() -> Iterator[Session]:
    """Open a session as the schema owner. Bypasses the runtime app role's RLS posture
    only because the owner is the table owner and policies still apply unless the
    owner is BYPASSRLS — which we deliberately did not grant. Reserved for trusted
    setup work (migrations, fixtures); never wired into the request path.
    """
    OwnerSession = sessionmaker(bind=get_owner_engine(), autoflush=False, expire_on_commit=False, future=True)
    sess = OwnerSession()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _set_local(sess: Session, key: str, value: str | None) -> None:
    """Set a transaction-local GUC.

    SET LOCAL only persists for the current transaction. When the connection is
    returned to the pool, the GUC is gone — preventing context leak across
    requests sharing pooled connections.

    We use parameter binding via set_config() rather than string interpolation to
    avoid SQL injection on the value side. set_config(name, value, is_local=true)
    is equivalent to SET LOCAL.
    """
    sess.execute(
        text("SELECT set_config(:k, :v, true)"),
        {"k": key, "v": value if value is not None else ""},
    )


@contextmanager
def tenant_session(ctx: TenantContext) -> Iterator[Session]:
    """Yield a session inside a transaction with the tenant GUCs set.

    The transaction is committed on clean exit and rolled back on exception.
    Use this for ALL request-scoped DB work.
    """
    sess = SessionLocal()
    try:
        sess.begin()  # explicit transaction so SET LOCAL has scope
        _set_local(sess, "app.current_firm", str(ctx.firm_id))
        _set_local(
            sess,
            "app.current_client",
            str(ctx.client_id) if ctx.client_id is not None else "",
        )
        _set_local(sess, "app.access_scope", ctx.scope.value)
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


@contextmanager
def subject_session(subject: str) -> Iterator[Session]:
    """Yield a session that can read ONLY the given subject's own memberships.

    Sets `app.current_subject` and nothing else. The `p_self_read` policy on
    `firm_membership` (migration 0015) keys off that GUC, so this session can
    see the caller's membership rows and no tenant data whatsoever — every
    tenant-scoped policy is keyed on `app.current_firm`, which stays unset and
    therefore evaluates to FALSE.

    This exists to break the chicken-and-egg in login: we cannot set the tenant
    GUCs until we know which firm the user belongs to. Use it ONLY for identity
    resolution; all real work goes through `tenant_session`.
    """
    sess = SessionLocal()
    try:
        sess.begin()
        _set_local(sess, "app.current_subject", subject)
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


@contextmanager
def unscoped_session() -> Iterator[Session]:
    """Open a session as the runtime app role with NO tenant context set.

    Used by isolation tests to assert the fail-closed behavior (zero rows when
    GUCs are unset). Do NOT use this in application code paths.
    """
    sess = SessionLocal()
    try:
        sess.begin()
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# Re-export for convenience.
__all__ = [
    "AccessScope",
    "SessionLocal",
    "engine",
    "get_owner_engine",
    "owner_session",
    "tenant_session",
    "unscoped_session",
]
