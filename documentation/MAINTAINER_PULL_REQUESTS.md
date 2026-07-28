# Maintainer Pull Request Integration

Lagniappe pull requests are source-only. GitHub reviews and CI validate the
contributor's proposed source, but the GitHub merge buttons are not used.
Instead, the maintainer applies an accepted PR locally, runs the appropriate
tests, builds the production frontend, and creates one commit containing both
the reviewed source and the freshly generated delivery files.

This keeps `main` installable for people who never use the development
toolchain. It also prevents a window where newly merged source is paired with
stale tracked assets.

## What happens on GitHub

Opening a pull request does not add anything to `main`. It proposes the commits
from another branch and starts the required CI workflow.

An approval is also not a merge. It records that the reviewed PR revision is
acceptable. For an ordinary contributor PR:

1. Read the description, conversation, commit list, and complete **Files
   changed** diff.
2. Confirm the required **Source quality and traceability** check passed.
3. Pay particular attention to changes covered by `CODEOWNERS`, including CI,
   testing, the runner, and dependency files.
4. Submit an approving review only when the exact current PR revision is
   acceptable.

If the contributor pushes another commit, review the new diff and wait for CI
again. If the PR conflicts with current `main`, ask the contributor to update
the PR and let CI validate the result. Do not invent unreviewed conflict
resolutions during integration.

## Fetch the accepted PR

Replace `123` with the pull-request number:

```bash
git switch main
git fetch origin
git merge --ff-only origin/main
git fetch origin \
  '+refs/pull/123/head:refs/remotes/origin/pr/123'
git switch -c integration/pr-123 origin/main
git merge --squash origin/pr/123
```

`git merge --squash` applies the PR as staged changes without creating a commit
and without preserving the contributor branch's commit ancestry. At this point,
review exactly what was applied:

```bash
git status --short
git diff --cached --stat
git diff --cached
venv/bin/python run.py pr-check --base origin/main
```

The local diff must match the accepted source PR. If it does not, stop and find
the reason. Do not continue from a different PR revision merely because its
changes look similar.

## Test the combined source

Run the suites appropriate to the change. Use focused tests first and add
broader suites according to the risk:

```bash
venv/bin/python run.py test unit
venv/bin/python run.py test js
venv/bin/python run.py test tooling
venv/bin/python run.py test setup
venv/bin/python run.py test e2e
```

E2E and other managed-server sessions must run sequentially. Review any updated
`testing/evidence/latest.json` before staging it, especially when a failure
could have captured private diagnostic data.

If a test requires a source correction, do not quietly add the correction to
the integration commit. Put the correction on the PR branch, rerun CI, and
review that new revision.

## Build the delivery files

Install the locked frontend dependencies and make a fresh production build
from the accepted source:

```bash
npm ci
npm run build
git status --short
```

When the local installation has `SENTRY_AUTH_TOKEN` configured, `npm run build`
uploads hidden JavaScript source maps to its configured Sentry project and then
removes the maps from `lagniappe/web/static/`. Decide whether that upload is
intended before starting the build.

The build normally updates `config/constants.py`, generated Python style maps,
and `lagniappe/web/static/`. Stage those paths explicitly:

```bash
git add -- \
  config/constants.py \
  lagniappe/web/static \
  lagniappe/web/start/styles/icons.py \
  lagniappe/web/start/styles/styles.py
```

If the maintainer's test run updated the evidence manifest and it is safe to
publish, stage it too:

```bash
git add -- testing/evidence/latest.json
```

Do not stage installation-local configuration, reports, source maps, or other
unrelated working-tree files.

## Validate and commit the complete tree

Run the final source and repository checks:

```bash
npm run check
venv/bin/python -m ruff check .
venv/bin/python run.py traceability \
  --check --fail-on warning --no-report --no-manifest
venv/bin/python run.py traceability \
  --changed origin/main \
  --check --fail-on warning --no-report --no-manifest
git diff --cached --check
git status --short
git diff --cached --stat
```

Do not rerun `pr-check` after staging the production build. It is a contributor
boundary check and is expected to reject maintainer-generated delivery files.

Review the final staged diff, then make one commit:

```bash
git commit -m "Concise description of the accepted change"
git log -1 --format=fuller
```

This commit should have current `main` as its single parent and contain:

- the exact accepted source changes;
- reviewed evidence from the maintainer's tests, when updated; and
- the fresh production build.

## Fast-forward `main`

Check that nobody advanced `main` while integration was in progress:

```bash
git fetch origin
git log --oneline --decorate --max-count=3 HEAD origin/main
git push origin HEAD:main
```

The push uses the repository owner's ruleset bypass because normal contributor
changes must arrive through a PR. This bypass is intentional only for the
complete maintainer integration commit.

Never force this push. If it is rejected because `main` advanced, rebuild the
integration on the new `origin/main`, rerun the relevant checks, and try a
normal fast-forward push again.

Verify that local and remote `main` identify the same commit:

```bash
git switch main
git fetch origin
git merge --ff-only origin/main
git rev-parse HEAD origin/main
```

## Close the source PR

Comment on the accepted PR with the final integration commit, for example:

> Integrated manually as `abc1234` after the required CI check passed and the
> production assets were rebuilt.

Then click **Close pull request**, not a GitHub merge button. GitHub may display
**Closed with unmerged commits** because squash integration produced a
different commit ID. That message is expected; verify the source diff is
present in the integration commit before deleting the PR branch.

After remote `main` is verified, the same-repository PR branch is safe to
delete. A contributor who opened the PR from a fork controls their own branch.
The closed PR, discussion, review, and CI results remain available on GitHub.

The temporary local integration branch can also be removed after local `main`
has fast-forwarded to its commit:

```bash
git branch -d integration/pr-123
```

