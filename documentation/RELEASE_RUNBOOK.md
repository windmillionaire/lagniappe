# Lagniappe Release Runbook

**Updated:** August 21, 2026

## Release model

| Ref | Purpose |
| --- | --- |
| `main` | Latest stable, installer-ready release |
| `next/X.Y.Z` | Active development for the next release |
| `hotfix/X.Y.Z` | Urgent patch based on `main` |
| `vX.Y.Z` | Immutable tag for a published release |

- Every change to `main` uses a pull request and squash merge.
- Commit the canonical production build with the release. Tracked static output
  may remain stale during development, but not on `main`.
- Never commit installation-local configuration, deployment descriptors,
  credentials, reports, or source maps.
- Use annotated, unsigned, immutable release tags.
- Delete each completed `next/*` or `hotfix/*` branch. Do not maintain a
  permanent development branch.

Increment `Z` for a compatible fix, `Y` for a normal feature release, and `X`
when the owner must perform documented post-upgrade data or cache maintenance.
For a major release, the release notes and `setup.sh upgrade` must clearly say
that the software upgrade finishes before the owner completes the required
Admin / Site Settings / Maintenance steps.

## Start the next release train

Run immediately after publishing `X.Y.Z`, using the next planned version as
`A.B.C`:

```bash
git switch main
git pull --ff-only origin main
git switch -c next/A.B.C
git push -u origin next/A.B.C
venv/bin/python run.py version set A.B.C
git add documentation/releases/A.B.C.md
git commit -am "Started version A.B.C"
git push
```

Pull `main` first because GitHub creates a new squash commit for the release.

## During development

- Commit directly to `next/X.Y.Z`.
- Run focused tests and commit current `testing/evidence/latest.json` evidence.
- Use `npm run dev` or `npm run watch` while changing frontend source.
- Keep `documentation/releases/X.Y.Z.md` current.

An ordinary `next/*` push without an open pull request is skipped by the release
workflow. Manual hosted runs are useful for diagnosis but do not replace the
release pull request's hosted gate.

### Promote a train when maintenance becomes required

A train may begin as a minor or patch release before its migration needs are
known. As soon as the release adds an Owner-run data migration or required
cache maintenance, promote it to the next major version before opening the
release pull request or creating hosted evidence. Rename the existing branch;
do not create parallel histories:

```bash
git branch -m next/X.0.0
git mv documentation/releases/A.B.C.md documentation/releases/X.0.0.md
venv/bin/python run.py version set X.0.0
```

Update the moved note's title and add a prominent **Required post-upgrade
maintenance** section. Set each new migration's `introduced_in` value to
`X.0`, commit the complete retargeting change, then publish the renamed branch:

```bash
git push -u origin next/X.0.0
git push origin --delete next/A.B.C
```

Verify the new remote branch before deleting the old one. `version set`
updates package metadata, generated application settings, the lockfile, and
the privacy-notice version; it does not rename an existing release note or Git
branch. `release-check` rejects new migration catalog entries without a major
increase, matching `introduced_in`, and the required release-note section.

## Release `next/X.Y.Z` to `main`

### 1. Finish release preparation

- Freeze source changes.
- Finalize release notes, migrations, dependency locks, privacy-notice
  applicability, and test evidence.
- For a major release, include the owner-run maintenance instructions and
  verify the upgrade command's major-version notice.
- Rehearse the installer against a non-personal test installation:

  ```bash
  ./setup.sh upgrade --branch next/X.Y.Z
  ```

If rehearsal changes source, finish those changes before continuing.

### 2. Verify the branch base

```bash
git fetch origin --prune
git status --short
git merge-base --is-ancestor origin/main HEAD
```

Stop for an unexpected dirty tree or failed ancestry check. If `main` advanced,
rebase onto `origin/main`, retain the `next/X.Y.Z` version metadata, and restart
release preparation.

### 3. Build and commit the exact candidate

```bash
npm ci
npm run build
git commit -am "Release Candidate X.Y.Z"
git status --short
```

Review the complete authored tree before committing. Add any intentional new
files explicitly. Skip the commit if the canonical build is already committed
and the tree is clean.

### 4. Run the offline gates

```bash
npm run check
venv/bin/python -m ruff check .
venv/bin/python run.py traceability --check --fail-on warning --no-report --no-manifest
venv/bin/python run.py traceability --changed origin/main --check --fail-on warning --no-report --no-manifest
venv/bin/python run.py release-check --base origin/main
git show --check --oneline HEAD -- . ':(exclude)lagniappe/web/static/**'
```

If a fix changes source or build input, rebuild, commit, and repeat all gates.

### 5. Create the hosted candidate and push it

```bash
venv/bin/python run.py hosted-e2e create
git push origin next/X.Y.Z
```

The hosted lifecycle is tied to the exact committed source/build pair. Do not
amend or replace that commit after creation.

### 6. Open the release pull request

```bash
gh pr create --base main --head next/X.Y.Z --title "Release X.Y.Z"
gh pr merge --auto --squash
gh pr checks --watch
```

The required **Source quality and traceability** workflow first reruns the
offline quality, traceability, and release checks in an unprivileged job. Only
a passing exact candidate can enter the protected environment and run hosted
`all`. A manual diagnostic dispatch may bypass that preflight, but cannot
publish release attestation. The automatic workflow may push one evidence-only
child commit and then validate that child without rerunning the suites. Do not
manually merge downloaded evidence into the release branch. Any later source
change requires a new exact hosted lifecycle.

### 7. Tear down hosted resources

After the current pull-request head is green and its result is secure:

```bash
venv/bin/python run.py hosted-e2e teardown
```

Keep a failed lifecycle available while diagnosing its logs. A failed result
cannot produce the required green status.

### 8. Publish the merged release

After GitHub squash-merges the pull request:

```bash
git switch main
git pull --ff-only origin main
```

Run the shortest critical release-specific smoke from `main`, then publish:

```bash
git tag -a vX.Y.Z -m "Lagniappe X.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "Lagniappe X.Y.Z" --notes-file documentation/releases/X.Y.Z.md
```

Confirm GitHub deleted `next/X.Y.Z`, then follow **Start the next release
train** from the tagged `main` commit.

## Recover or resume a release

- `hosted-e2e create` and `teardown` are resumable. Rerun the same command after
  a transient failure.
- If a fix changes the candidate commit, tear down the old lifecycle, rebuild,
  rerun the gates, and create a new lifecycle before pushing.
- If the pull-request branch moves unexpectedly, do not reuse its earlier
  hosted result.
- The hosted workflow records failed evidence for diagnosis, but only passing
  evidence can publish the required status.

## Hotfixes

Create the patch branch from current `main`:

```bash
git switch main
git pull --ff-only origin main
git switch -c hotfix/X.Y.Z
```

Implement the smallest safe fix, set the patch version, write focused release
notes, and rehearse with:

```bash
./setup.sh upgrade --branch hotfix/X.Y.Z
```

Then follow the normal build, offline gate, hosted candidate, pull request,
teardown, tag, and GitHub Release steps, substituting `hotfix/X.Y.Z` for the
branch name.

After publishing, rebase the active next train onto the hotfixed `main`:

```bash
git fetch origin
git switch next/A.B.C
git rebase origin/main
git push --force-with-lease
```

Resolve version conflicts in favor of `A.B.C` and rerun affected tests.

## Repository prerequisites

Verify these only when repository settings or release automation change:

- `main` is the default branch.
- Only squash merging is enabled; auto-merge and automatic head-branch deletion
  are enabled.
- `main` requires a pull request, the **Source quality and traceability** status,
  an up-to-date branch, and linear history; force pushes and deletion are
  blocked.
- `next/*` and `hotfix/*` have no rulesets.
- `v*` creation is restricted to the owner, and existing tags cannot be updated
  or deleted. Use separate creation and update/deletion rulesets so the owner's
  creation bypass cannot move an existing tag.
- The default `GITHUB_TOKEN` is read-only. The release workflow receives only
  its scoped evidence, continuation, status, pull-request validation, hosted
  invocation, and result-read permissions.

A direct push to `main` is reserved for a genuine GitHub outage or comparable
incident. Record the reason and recreate the release, validation, and tagging
evidence afterward.
