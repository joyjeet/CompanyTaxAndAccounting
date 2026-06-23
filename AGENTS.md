# CompanyTaxAndAccounting — agent operating notes

These are persistent rules for any AI coding agent (or human) operating on
this repo. They override defaults.

## Azure subscription pin — DO NOT GUESS

**Every deploy or `az` call against this project MUST target subscription:**

```
0270f50b-f296-40a3-9f05-3f8ff04ba8bc
```

(Display name: *Visual Studio Premium with MSDN*, owner `joyjeet@msn.com`.)

The owner has **multiple** Azure subscriptions. `az account show` is not a
source of truth — it may report `15d0fb58-…` ("Visual Studio Enterprise
Subscription") or another one. Before any deploy / teardown / resource
inspection, run:

```bash
az account set --subscription 0270f50b-f296-40a3-9f05-3f8ff04ba8bc
```

`scripts/deploy_azure_customer.sh` and `scripts/teardown_azure_customer.sh`
already pin this via the `SUBSCRIPTION_ID` env default — do not change that
default without an explicit user instruction. If a different subscription is
ever required, it must be passed in as `SUBSCRIPTION_ID=… ./scripts/…`, not
by editing the default.

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

## Deploy path

The canonical deploy command is:

```bash
./scripts/deploy_azure_customer.sh
```

It builds the API & UI images via `az acr build`, deploys
`infra/main-demo.bicep`, runs `alembic upgrade head` + `scripts/seed_demo.py`
inside the API container at boot, prints the customer-facing URLs, and
schedules auto-teardown after 24 h. Output receipt lands in
`results/azure-demo-<timestamp>/deploy.json`.

The GitHub Actions `cd.yml` workflow targets a different (`eastus2` /
`ctaa-staging`) stack and has never been wired up — do not rely on it.

## Test baseline

Before any deploy:

```bash
.venv/bin/python -m pytest --tb=no -p no:warnings   # expect: 373 passed
cd frontend && npx tsc --noEmit && npm run build    # expect: clean
```
