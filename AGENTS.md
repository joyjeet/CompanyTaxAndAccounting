# CompanyTaxAndAccounting — agent operating notes

These are persistent rules for any AI coding agent (or human) operating on
this repo. They override defaults.

## Azure subscription pin — DO NOT GUESS

**Every deploy or `az` call against this project MUST target the subscription
recorded in `.azure.env` at the repo root.** That file is gitignored; this
repository is public, so the ID is not committed. Create it once from
`.azure.env.example`.

The owner has **multiple** Azure subscriptions. `az account show` is not a
source of truth — the active one drifts between them. Before any deploy /
teardown / resource inspection:

```bash
set -a && source .azure.env && set +a
az account set --subscription "$SUBSCRIPTION_ID"
```

`scripts/deploy_azure_customer.sh`, `scripts/redeploy_ui.sh` and
`scripts/teardown_azure_customer.sh` all resolve this via
`scripts/_azure_env.sh`. They **fail loudly** rather than falling back to the
currently-active subscription — guessing risks deploying into the wrong one.
Do not reintroduce a hardcoded default. For a one-off, pass
`SUBSCRIPTION_ID=… ./scripts/…`.

### Region

`centralus`. Postgres Flexible Server is offer-restricted on this
subscription in `eastus`, `eastus2`, and `westus2`. The two unrestricted
US regions today are `centralus` and `westus3`.

### Existing long-lived resource groups in this sub

| RG | Purpose |
|---|---|
| `rg-ctax-shared-cus` | Shared ACR `ctaxdemocusreg` (reused across demos) |
| `rg-ctax-shared-eus` | Shared Azure OpenAI `ctaxdemoeusoai` |
| `rg-ctax-demo-cus`   | Ephemeral per-deploy demo stack (24 h TTL — recreated on every `deploy_azure_customer.sh` run) |

## Branches are protected — you cannot push to `dev` or `main`

Both branches are covered by the `protected-branches` ruleset (mirrored in
`.github/branch-ruleset.json`). `git push origin dev` is rejected. Ship work
with:

```bash
make pr m="what you changed"
```

That branches off `origin/dev`, commits, pushes, opens the PR and enables
auto-merge, so it merges itself once the gate is green. See
`docs/runbooks/DEV_WORKFLOW.md`.

**Never cut a branch from an already-merged local branch.** PRs are
squash-merged, so the pre-squash commits conflict with the squashed commit on
`dev` — and GitHub runs *no checks at all* on a conflicting PR, so it silently
hangs forever waiting for auto-merge.

## Deploy path

Pushes to `dev` deploy automatically through `.github/workflows/cd.yml`:
`quality-gate` -> `build-and-push` -> `deploy-dev` (which runs migrations).
Production is a PR from `dev` into `main`. Nothing deploys unless the full
test suite passes first.

For an ephemeral customer-demo stack, the canonical command is:

```bash
./scripts/deploy_azure_customer.sh
```

It builds the API & UI images via `az acr build`, deploys
`infra/main-demo.bicep`, runs `alembic upgrade head` + `scripts/seed_demo.py`
inside the API container at boot, prints the customer-facing URLs, and
schedules auto-teardown after 24 h. Output receipt lands in
`results/azure-demo-<timestamp>/deploy.json`.

The GitHub Actions `cd.yml` workflow deploys the `ctaa-dev` / `ctaa-prod`
stacks and is separate from the demo stack above.

## Test baseline

Before any deploy (CI enforces all of these, so running them first is faster
than waiting for a red gate):

```bash
.venv/bin/python -m pytest --tb=no -p no:warnings   # expect: 489 passed
.venv/bin/ruff check app tests                      # expect: clean
cd frontend && npx tsc --noEmit && npm run build    # expect: clean
```
