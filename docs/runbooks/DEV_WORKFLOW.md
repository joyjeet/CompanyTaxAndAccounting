# Day-to-day development workflow

`dev` and `main` are protected branches. You cannot push to them directly —
`git push origin dev` will be rejected. Every change reaches them through a
pull request, because that is what forces the test suite to run before anything
is built or deployed.

This is deliberate. Before the protection existed, a `git push` went straight
to a deployment without a single test running.

## The whole workflow, one command

Edit files however you like, then:

```bash
make pr m="what you changed"
```

That single command:

1. creates a branch off the latest `dev`,
2. commits your work,
3. pushes it,
4. opens the pull request,
5. turns on auto-merge.

You do not have to wait around. The PR merges itself the moment the checks go
green, and the branch is deleted for you. If the checks fail, the PR just sits
there unmerged and nothing is deployed.

Watch progress if you want to:

```bash
gh pr checks --watch
```

## Fixing something after the checks fail

Stay on the same branch, make the fix, and run the same command again:

```bash
make pr m="fix the failing test"
```

It notices you already have an open PR and adds the commit to it rather than
opening a second one.

## First-time setup

```bash
brew install gh
gh auth login
```

## Doing it by hand

`make pr` is a convenience wrapper, not magic. The equivalent long form:

```bash
git checkout -b my-change origin/dev
git add -A && git commit -m "what you changed"
git push -u origin my-change
gh pr create --base dev --fill
gh pr merge --auto --squash
```

You can also do all of this by clicking, using the VS Code **Source Control**
panel plus the **GitHub Pull Requests** extension.

## What has to pass

Two checks are required before a PR can merge:

| Check | What it covers |
| --- | --- |
| `quality-gate / Lint, migrate, test` | ruff, the Alembic migration plus a rollback, and the full pytest suite with coverage |
| `quality-gate / Frontend typecheck, test, build` | `tsc --noEmit`, vitest, and a production build |

Run them locally first to get a faster answer:

```bash
make lint && make test
make frontend-test
```

## Releasing to production

`dev` deploys automatically once its checks pass. Production is a PR from `dev`
into `main`, which runs the same gate again.

```bash
gh pr create --base main --head dev --title "release: <summary>"
```

## A note on branch protection

The rules live in a GitHub ruleset named `protected-branches` and are mirrored
in [.github/branch-ruleset.json](../../.github/branch-ruleset.json) so the
configuration is reviewable in version control. If you change the ruleset in
the GitHub UI, update that file too. To reapply it from the file:

```bash
gh api --method PUT repos/<owner>/<repo>/rulesets/<id> --input .github/branch-ruleset.json
```
