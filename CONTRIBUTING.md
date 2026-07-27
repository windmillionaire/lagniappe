# Contributing to Lagniappe

Bug reports, feature suggestions, documentation fixes, and focused improvements
are welcome. Please read this page before opening a PR so review time can stay
focused on changes that fit the project.

Good first scopes include a focused bug fix with a regression test, an
accessibility improvement, a correction to technical documentation, or a
narrow maintainability change that follows the existing architecture. Provider
compatibility fixes are also welcome when they include an offline contract test
or clearly identified evidence from the contributor's own infrastructure.

## Architecture conformance

This project uses a custom entity/property backend, a custom frontend
view/widget system, and a YAML-driven style pipeline. They do not follow Django,
Rails, React, or other mainstream patterns.

PRs are expected to work with these local patterns. Changes whose main goal is to
introduce standard framework idioms, broad new abstraction layers, or
reorganize code to look more conventional are unlikely to fit and may be closed
without detailed review. If you use AI assistance, review the output carefully
and adapt it to the existing architecture before submitting.

When unsure whether an approach fits, open an issue first.

## AI-assisted work and traceability

AI assistance is fine, but must be carefully reviewed, and the repo has
some tools designed around making agents more useful and accountable. The
project has more explicit maps than many codebases: subsystem docs,
source/test annotations, review reports, browser-review harnesses, and runner
commands all help agents work inside a custom architecture that does not look
much like a standard React, Django, Rails, or Laravel app. The testing
and traceability harness was built specifically to give agents a feedback loop,
so AI-assisted changes can be reviewed against concrete expectations instead of
accepted on vibes.

Annotations such as `@testable`, `@tests`, `@features`, `@dimensions`,
`@template`, and `@reason` are primarily traceability scaffolding for tooling
and agent comprehension. They give agents direct pointers to relevant tests,
templates, features, and known manual boundaries so they do not have to infer
everything from broad grep passes. They are not meant to become a heavy manual
documentation burden for every human contributor.

If you use AI assistance, treat it as a powerful tool that still needs careful
setup, guards, and review:

- make the agent read the relevant `documentation/` page before changing a
  subsystem;
- prefer focused changes that follow the existing local architecture;
- ask the agent to run the relevant repo test command or explain why it could
  not;
- review any annotations it adds or changes, because traceability comments are
  useful only when they describe real coverage rather than decoration.

When moving or materially reshaping annotated source/tests, preserve or update
the nearby annotations where practical. For larger traceability changes, use
the tooling docs:

- [TESTING_TRACEABILITY_TOOL.md](documentation/TESTING_TRACEABILITY_TOOL.md)
- [TESTING_TEMPLATE_CONTRACTS.md](documentation/TESTING_TEMPLATE_CONTRACTS.md)
- [TESTING_SOURCE_REVIEW.md](documentation/TESTING_SOURCE_REVIEW.md)
- [TESTING_TEST_REVIEW.md](documentation/TESTING_TEST_REVIEW.md)

The goal is not annotation volume. The goal is that humans and agents can tell
what behavior a change is supposed to preserve, where to look for evidence, and
which risks are still manual or uncovered.

## Documentation

All technical documentation lives in `documentation/`. Start with
[OVERVIEW.md](documentation/OVERVIEW.md) for the full index.

Before changing a subsystem, read its doc:

- Backend entities and properties → [BACKEND_ENTITIES.md](documentation/BACKEND_ENTITIES.md)
- Frontend views and widgets → [FRONTEND_VIEWS.md](documentation/FRONTEND_VIEWS.md)
- Tests → [TESTING.md](documentation/TESTING.md) and [TESTING_WRITING_TESTS.md](documentation/TESTING_WRITING_TESTS.md)

Agent workflow docs: [AGENTS.md](AGENTS.md).

## Development setup

The README describes the ordinary guided installation flow. Use the steps below
when you are developing Lagniappe itself or running the application locally from
source.

Prerequisites:

- Python 3.12+
- Node.js/npm matching `package.json` (`^22.18.0 || >=24.11.0`);
  `.nvmrc` provides the recommended version for nvm users
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
- Redis access for local workflows that exercise search, filters, cache, or sync

Google Cloud and Redis are required for a working development installation;
there is no provider-free or local-only mode. Development and tests are
supported on Linux, macOS, and WSL2; native Windows is not currently supported
because the harness and npm scripts depend on POSIX behavior.

Development uses the same real installation configuration and cloud/Redis
resources as the application. First create the virtualenv and complete the
ordinary guided setup. You may decline its final deployment prompt if you only
need the local checkout:

```bash
python3 -m venv venv
./setup.sh
```

Then add the local development toolchain:

```bash
./setup.sh development
```

The development step is additive and safe to rerun. It installs
`requirements-dev.txt`, the locked npm dependencies, Playwright Chromium, and
the development frontend bundle. It does not create a substitute configuration
or provision a second infrastructure stack.

Normal setup leaves error reporting off unless the operator opts in. An
opted-in normal installation may send privacy-reduced reports to the Lagniappe
maintainer's Sentry project or use an operator-supplied DSN. The development
step will not proceed while the maintainer DSN is selected: a developer must
supply their own Sentry DSN or disable error reporting so development failures
do not pollute maintainer telemetry.

Use `npm run watch` while editing frontend/style sources. `npm run build`
creates the production bundle; Sentry source maps are generated and uploaded
only when `SENTRY_AUTH_TOKEN` is configured.

## Pull request build policy

Generated delivery files are committed on `main` so ordinary installations do
not need Node or the development toolchain. They are maintainer-built
artifacts, not contributor-authored PR content. Contributor PRs must therefore
exclude:

- `lagniappe/web/static/`;
- generated server style maps in `lagniappe/web/start/styles/`;
- every installation-local file under `config/files/`;
- the generated root `lagniappe.yaml` and `index.yaml`; and
- build-only `BUILD_ID` changes in `config/constants.py`.

Contributors may build locally to test their work. They may exclude generated
changes from the commit themselves or use the optional index-cleaning helper,
then run the authoritative check:

```bash
venv/bin/python run.py pr-clean  # optional
venv/bin/python run.py pr-check
```

`pr-clean` resets only the generated paths in Git's prospective commit/index to
the PR merge base and restores only the `BUILD_ID` line. Local static output,
style maps, and installation config remain in the working tree for continued
testing; authored source and other constants are preserved. If generated
output was already committed, the helper stages its reversal, which must be
committed before pushing.

`pr-check` compares the prospective commit/index with the merge base. It ignores
unstaged and untracked local build output because those files are not PR
content. Both commands default to `origin/main`, then `main`; use `--base REF`
for a different target. `pr-check` is validation-only and never changes Git
state.

The maintainer integrates a PR locally without committing immediately, runs a
fresh production build from the combined source, reviews the result, and
commits the source plus maintainer-generated delivery files together:

```bash
git switch main
git merge --squash CONTRIBUTOR_BRANCH
npm ci
npm run build
git status
git commit
```

This applies even when the PR did not directly change frontend source. The
public `main` branch therefore never has newly integrated source paired with
stale generated files, while the contributor PR remains source-only and
reviewable. The hosted PR workflow invokes the same `pr-check` command as a
hard gate; in a hosted checkout, the index represents the committed PR branch.

```bash
venv/bin/python run.py dev          # development server (port 5050)
venv/bin/python run.py test         # all pytest suites
venv/bin/python run.py test unit    # backend unit tests
venv/bin/python run.py test js      # server-free frontend behavior tests
venv/bin/python run.py test e2e     # Playwright + pytest browser tests
venv/bin/python run.py test tooling # setup, config, and repository-health tests
```

Unit, JavaScript, and tooling tests are server-free. E2E tests use the managed
test server on port 5000 and require the configured GCP/Redis test
infrastructure. See [TESTING.md](documentation/TESTING.md) for aliases,
filters, traceability tools, and the definitions/resources/elements test
layout.

Run the source-quality checks before submitting a change:

```bash
npm run check
venv/bin/python -m ruff check .
venv/bin/python run.py traceability --check --fail-on warning
venv/bin/python run.py traceability --changed origin/main --check --fail-on warning
venv/bin/python run.py pr-check
```

Biome checks authored JavaScript, CSS, and JSON; Ruff performs the narrow
Python correctness lint. Use `npm run format` to apply Biome formatting. Ruff
does not format Python in this repository.

Tests run through the repo runner update the tracked
`testing/evidence/latest.json` manifest. Run the tests required by your change
on your own configured GCP/Redis infrastructure and include that manifest in
the PR. Review it first: failed results can contain diagnostic tracebacks, so
never commit credentials, private data, or other sensitive output. The hosted
workflow deliberately has no infrastructure credentials and runs no
application tests; it validates Biome, Ruff, repository-wide and changed-source
traceability, the committed test evidence, and the contributor artifact
boundary. This is a trust-based contribution record, and the maintainer reruns
the appropriate tests before merging.

## Icons

Semantic icon mappings live in `src/style/icons.yaml`. Reusing an existing
mapping requires no asset step. Each leaf records a Material Symbols Rounded
glyph, fill state, and optional weight or animation. Templates use
`render_icon()` and JavaScript uses the shared icon helpers; do not hardcode
ligature names or font presentation in application code. Optical size
exceptions belong in `src/style/icons.css` as semantic `data-icon` selectors
that set `--icon-size`; this resizes the inner glyph while preserving the
shared outer icon box.

Adding a new glyph changes the self-hosted subset. After editing the registry,
run `venv/bin/python run.py icons` to request the official subset from Google,
update its metadata, and rebuild the frontend. The Apache 2.0 license is
preserved under `THIRD_PARTY_LICENSES/`.

## Setup and local config files

The installer update/upgrade flow assumes installation-specific files stay untracked.
Keep `.gitignore` entries for generated config and deployment artifacts such as
`config/files/`, `lagniappe.yaml`, and `index.yaml`. Ordinary installations can
use `./setup.sh upgrade` to replace tracked source from `origin/main`, refresh
the generated installation configuration, and optionally deploy. Maintainers
of modified checkouts should merge source themselves and run
`./setup.sh update` without replacing their worktree.

## Pull requests

1. Fork the repository and branch from `main`.
2. Read the relevant `documentation/` page before changing code.
3. Follow existing patterns in the area you are editing.
4. Add or update tests when behavior changes.
5. Run the relevant tests and commit `testing/evidence/latest.json`.
6. Submit a PR with a clear description of what changed and why.

## License

By contributing, you agree that your contributions are licensed under the
[GNU Affero General Public License v3.0](LICENSE).
