# Production authentication

How CTAA signs people in once you leave demo mode, and what to configure.

## The model in one paragraph

Entra ID answers **who you are**. Our own `firm_membership` table answers
**what you can reach**. The token is fully validated (signature, issuer,
audience, expiry) and then we throw away everything in it except `sub`. Nothing
about firm, client or role is trusted from the token.

## Why not put the firm/client in the token

Two reasons, both operational.

1. **Revocation.** A claim is frozen into the token until it expires. Remove
   someone from a firm and they keep working for the rest of the token's
   lifetime. A membership lookup takes effect on their next request.
2. **Churn.** A CPA firm's client roster changes constantly. Encoding it as
   directory extension attributes means a directory write — and directory-admin
   rights — for what is purely an application concern.

The claims path still exists (`APP_AUTHZ_SOURCE=claims`) and is the default so
local dev and CI are unaffected. Production sets `membership`.

## The two front doors

`/welcome` is the public landing page. It offers two entry points:

| Button | Authority | Typical users |
|---|---|---|
| Accounting firm | Workforce tenant (`login.microsoftonline.com/<tenant>`) | CPAs, bookkeepers, firm staff |
| Client portal | Entra External ID (`<tenant>.ciamlogin.com/...`) | Business owners |

**The button is a routing hint, not a grant.** It only decides which authority
to redirect to. If a client signs in through the firm door, they still get a
client portal, because the role comes from their membership row. Treating the
button as a permission would be straightforward privilege escalation.

Leave the `VITE_MSAL_CLIENT_*` variables blank to point both doors at the same
authority — the landing page still works, it just redirects to one place.

## Choosing a workspace

After sign-in the SPA calls `GET /auth/context`:

| Memberships | What happens |
|---|---|
| 0 | "Signed in, but not set up yet" page. **Not** a redirect to the IdP — signing in again cannot create a membership, so that would loop forever. |
| 1 | Selected silently. This is almost everyone. |
| 2+ | Workspace picker. Real case: staff at two practices, or a CPA who is also a client of another firm. |

The choice is stored in `sessionStorage` and sent as `X-CTAA-Firm` /
`X-CTAA-Client` headers. The backend checks those against the caller's own
memberships, so a tampered header can narrow access but never widen it.

## Configuration

Backend:

```
APP_AUTH_MODE=jwt
APP_AUTHZ_SOURCE=membership
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_AUDIENCE=api://<api-client-id>
OIDC_JWKS_URL=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys
```

Frontend (build-time — Vite inlines these):

```
VITE_AUTH_MODE=msal
VITE_AUTHZ_SOURCE=membership
VITE_MSAL_CLIENT_ID=<spa-client-id>
VITE_MSAL_AUTHORITY=https://login.microsoftonline.com/<tenant-id>
VITE_MSAL_API_SCOPE=api://<api-client-id>/access
VITE_MSAL_REDIRECT_URI=https://<your-host>
VITE_MSAL_CLIENT_AUTHORITY=https://<ciam-tenant>.ciamlogin.com/<ciam-tenant>.onmicrosoft.com
VITE_MSAL_CLIENT_CLIENT_ID=<portal-spa-client-id>
VITE_MSAL_CLIENT_API_SCOPE=api://<api-client-id>/access
```

`APP_AUTHZ_SOURCE` and `VITE_AUTHZ_SOURCE` **must match**. If the backend is on
`membership` and the SPA on `claims`, the SPA never sends a context header, and
any user with two memberships gets a 409 on every request with no picker to
resolve it.

### App registrations

Two registrations, plus one for the API:

* **API** — expose a scope (e.g. `access`). `OIDC_AUDIENCE` is its app-id-uri.
* **SPA (workforce)** — SPA platform, redirect URI = your host. Grant the API
  scope.
* **SPA (external ID)** — same, in the Entra External ID tenant.

Request the **API's** scope, never the SPA's own client id. Requesting your own
client id returns an id-token, not an access-token, and the RS256 validator
will reject it.

## Onboarding a real user

1. A firm admin invites them from **Team** (staff) or the client's portal
   access page (portal users).
2. They sign in through the matching door on `/welcome`.
3. They accept the invite, which creates the `firm_membership` row.
4. From then on, sign-in resolves straight through.

`client_portal` is rejected by the staff team API on purpose. A portal
membership must name the single client it is scoped to, which the staff
endpoints have no way to supply; allowing it there would either violate
`ck_firm_membership_client_scope` or hand an external client firm-wide scope.

## How the login lookup gets past RLS

`firm_membership` is `FORCE ROW LEVEL SECURITY` with a policy keyed on
`app.current_firm`. Resolving a login is a chicken-and-egg problem: we cannot
set `app.current_firm` until we know which firm the user belongs to. `FORCE`
means even the table owner is filtered, so there is no privileged-connection
escape hatch.

Migration `0015` adds a **permissive, SELECT-only** policy `p_self_read` keyed
on a new `app.current_subject` GUC. Permissive policies OR together, so this
widens read access by exactly one thing: you may see your own membership rows.
Writes still require firm scope, and tenant isolation is unchanged.

`subject_session()` (in `app/db/session.py`) sets only that GUC. It is for
identity resolution and nothing else — every tenant-scoped policy keys on
`app.current_firm`, which stays unset, so the session can see no client data at
all. `tests/integration/test_membership_authz.py` asserts both halves of this.

## Rollback

Set `APP_AUTHZ_SOURCE=claims` and `VITE_AUTHZ_SOURCE=claims`. The token-claims
path is untouched and still fully tested. The migration is independently
reversible (`alembic downgrade 0014_activate_coa_templates`).
