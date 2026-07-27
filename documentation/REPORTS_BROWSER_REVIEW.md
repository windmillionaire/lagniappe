# Reports Browser Review

Reference tag: `@REPORTS_BROWSER_REVIEW`

Use this workflow when an agent needs to inspect the application in a browser,
compare a focused site area with nearby E2E coverage, capture screenshots, and
write a curated browser review report. Good feedback can include product/UX
issues, UI/source suggestions, and important test coverage recommendations.

This is a scoped exploratory review, not an exhaustive audit or a quick visual
pass. The agent should sample the important user paths, states, and responsive
breakpoints for the requested area, then follow reasonable curiosity: click
through confusing controls, try representative form submissions, save and rerun
filters, resize the viewport, revisit previous panels, and generally look for
places where a real user would wonder what happens next.

## Workflow

1. Identify the review scope and nearby tests.

   Map the target route or section to the closest E2E folder before opening the
   browser. For example, `/` usually maps to `testing/tests_e2e/002_home/`, and
   project pages usually map to `testing/tests_e2e/004_projects/`.

   Useful starting commands:

   ```bash
   rg --files testing/tests_e2e -g 'test_*.py'
   rg -n "def test_|@features|@dimensions|@todo|unfinished" \
     testing/tests_e2e/002_home testing/tests_e2e/004_projects
   ```

   Skim the focused tests and the resources/elements they call. The goal is to
   understand which user stories are already covered, which states are intended
   but unfinished, and which important visible behavior appears unrepresented.

2. Start the managed testing server:

   ```bash
   venv/bin/python run.py test-server --start
   ```

   If the review needs realistic data immediately, load a seed pack at start:

   ```bash
   venv/bin/python run.py test-server --start --load project-review
   ```

   Available seed packs:

   - `project-review` is useful for project-page and task-filter reviews. It
     loads a project, model tasks, page tasks, completion/due-date/assignee
     examples, and attached-form submissions from the normal E2E definitions.
   - `category-review` is useful for category-index and page-filter reviews. It
     loads a category, its default page form, matching and nonmatching pages,
     an extra page category facet, and a public page with a document asset.
   - `form-index-review` is useful for the form index and form-builder entry
     points. It loads page and task forms with simple and complex schemas, plus
     related categories and projects so relationship columns have real values.
   - `page-review` is useful for the page view itself. It loads a page with a
     default form submission plus active, due, assigned, project-linked,
     form-submission, and completed tasks. Its document intentionally starts
     empty so the review can exercise the editor like a normal user would.
   - `search-review` is useful for the full search results page. It loads
     category, page, project, task, form, and user data with a shared `filter`
     query token so facets, snippets, result links, and pagination can be
     reviewed from `/search-page?q=filter`.
   - `task-index-review` is useful for the global active-task index. It loads
     personal and page-backed active tasks with due dates, assignment,
     project/model links, and attached-form data, plus one completed contrast
     task that should stay out of the active index.
   - `user-index-review` is useful for the user index and group-permissions
     tools. It loads plain users, permissioned users, user groups, and
     representative general/entity-specific permission profiles.

   Run browser reviews and E2E tests sequentially. The managed testing server
   owns shared test data and teardown, so a parallel pytest or browser-review
   session can clean up underneath another run.

3. Capture browser evidence into a review folder:

   ```bash
   venv/bin/python run.py browser-review capture \
     --name home-first-load \
     --title "Homepage Browser Review" \
     --focus "Dashboard usability and E2E coverage" \
     --path / \
     --wait-for "[lp-view][initialized]" \
     --login-admin
   ```

   The command prints a folder such as:

   ```text
   reports/browser_reviews/home-first-load_20260603_170000
   ```

4. Explore the focused stories in the live UI.

   Use the tests as a map, not a script. Recreate representative flows, check
   the most important empty/loading/error/permission states when they are easy
   to reach, and sample desktop and mobile captures. This pass should be
   curious and mildly adversarial, not optimized for speed: ask "what does this
   do?", try the controls that look awkward, save things, reopen them, reset
   them, navigate away and back, and mix a couple of filters or form inputs
   when the surface supports it. Notice:

   - broken or confusing behavior;
   - awkward visual hierarchy, copy, affordances, focus, spacing, alignment, or
     responsive layout;
   - console errors, failed requests, or suspicious server output;
   - important behavior that appears absent from nearby tests;
   - brittle or over-specified tests that seem likely to miss the real user
     risk.

   On the managed testing server, it is desirable to create throwaway records
   and complete representative form submissions. `test-server --teardown`
   clears test-prefixed datastore/cache data, so prefer real flows over stopping
   at open-form screenshots. For document surfaces, write, edit, format, and
   revisit the document like a normal collaborative editor rather than only
   checking whether the tab opens. It is also fine to use the app's AI text
   features during browser review. These flows are part of the product, and
   reviewing the generated output can expose prompt-tuning opportunities. Treat
   browser review as an intentionally time- and compute-expensive quality pass,
   not a quick cheapest-path smoke test.

   Be cautious with due-date findings from programmatic seed packs. Browser
   review seeds are created outside the normal browser form-submission path, so
   relative test dates can occasionally disagree with the browser/user timezone.
   Report obvious product date problems, but do not over-weight a one-day seed
   offset unless it reproduces through the normal UI flow or a focused date test.

5. Edit that folder's `review.json`.

   Keep the report curated. Screenshots should appear only when they illustrate
   a finding. Logs, console messages, and server output should be included only
   when they explain an issue.

   Coverage findings belong in the report when they are important to the
   reviewed area and are grounded in the focused tests you inspected. If the
   review also changes tests, put durable backlog close to the tests as
   `@todo`, an ordinary review comment, or an `@pytest.mark.unfinished` stub, then
   mention that in the report.

6. Render the HTML report:

   ```bash
   venv/bin/python run.py browser-review render \
     reports/browser_reviews/home-first-load_20260603_170000/review.json
   ```

   The final report is:

   ```text
   reports/browser_reviews/home-first-load_20260603_170000/index.html
   ```

7. Teardown the server:

   ```bash
   venv/bin/python run.py test-server --teardown
   ```

## Report Folder

Each browser review lives in its own generated folder:

```text
reports/browser_reviews/<slug>_<timestamp>/
  capture.json
  review.json
  index.html
  screenshots/
  logs/              # optional, only when useful
```

`capture.json` records available screenshots and browser diagnostics. It is raw
evidence, not the final review. `review.json` is the curated report spec that an
agent edits before rendering.

If `browser-review capture` fails, the generated folder is removed by default so
failed retries do not clutter `reports/browser_reviews/`. Add `--keep-failed`
when the partial screenshots or raw files are useful for debugging.

## Design Exploration Reports

The same report folder can also be used for UI design exploration when the
baseline behavior is known but the next step is a product choice instead of a
bug triage pass.

Use the normal `test-server` and `browser-review capture` commands to preserve
the real page evidence. Then create deterministic local mockups, usually as a
small HTML/CSS board under `/tmp`, and screenshot each concept into that
report's `screenshots/` folder. Edit `review.json` with concept-oriented
findings, using `good` for the recommended direction and `note` for viable
alternatives. Render with the normal `browser-review render` command.

Keep these reports focused on decisions: the current state, the recommended
direction, tradeoffs for each alternative, and enough implementation notes to
make the follow-up change obvious.

## Review Spec

Use this shape in `review.json`:

```json
{
  "title": "Homepage Browser Review",
  "subtitle": "Dashboard usability and E2E coverage",
  "summary": "Short overall judgment.",
  "findings": [
    {
      "severity": "medium",
      "title": "Detached plus buttons make create actions ambiguous.",
      "body": "Explain the observed issue and user impact.",
      "suggestions": [
        "Add explicit tooltips or accessible labels to icon-only create buttons.",
        "Consider integrating create actions into the same row surface."
      ],
      "screenshots": [
        {
          "path": "screenshots/home-first-load_desktop.png",
          "caption": "The plus controls sit in a separate column from their labels."
        }
      ]
    },
    {
      "severity": "note",
      "title": "Coverage: task empty-state recovery is not represented nearby.",
      "body": "testing/tests_e2e/002_home/ covers task list rendering and creation, but the reviewed empty-state recovery path does not appear to have a focused assertion.",
      "suggestions": [
        "Add an E2E assertion for the empty-state create path if this remains a primary homepage action.",
        "Prefer a helper-level selector for the empty-state action instead of asserting the full card copy."
      ],
      "screenshots": []
    }
  ],
  "diagnostics": []
}
```

Supported severities are `high`, `medium`, `low`, `good`, and `note`.
Until the renderer has separate categories, prefix test recommendations with
`Coverage:` so they are easy to scan in the findings list.

Add `diagnostics` only when logs, console errors, failed requests, or server
output are relevant to a finding:

```json
{
  "title": "Console error after opening project create form",
  "content": "error: ...stack trace or server excerpt..."
}
```

## Login

For manual login, use the same test-user bypass as the E2E login flow:

```text
http://127.0.0.1:5000/users/login?test_user=admin@test.com
```

In `FLASK_ENV=testing`, the `test_user` query logs in the requested test user.
If the requested email is the configured admin email and it does not exist yet,
the route creates it first. Other test-user emails must already exist or the
route returns `403`.

## Notes For Agents

- Prefer `browser-review capture` for screenshots and diagnostics; write the
  critique yourself in `review.json`.
- Treat nearby tests as review context. Read enough test, resource, and element
  code to tell whether a finding is already covered, intentionally unfinished,
  or plausibly missing.
- For JavaScript-heavy or prefetched pages, use a page-specific readiness
  selector such as `[lp-view][initialized]` and increase `--settle-ms` when
  needed. If the useful ready marker is hidden, run a small interaction pass
  instead of forcing `browser-review capture`; Playwright's default selector
  wait expects visible elements.
- Treat `net::ERR_ABORTED` entries from background polling, prefetches, or page
  close as raw evidence only. Verify them in a live interaction pass before
  reporting them as product failures.
- Do not include every screenshot in `index.html`. Attach only evidence that
  supports a finding.
- Do not include URLs, raw logs, or console output in the report unless they
  matter to an issue.
- Coverage findings should be phrased as recommendations unless you have
  checked the relevant tests closely. Name the focused folder or test file that
  informed the recommendation.
- Do not create a coverage checklist for every untested click. Call out missing
  coverage only when the behavior is important, user-visible, risky, or already
  implied by nearby tests.
- If you modify tests during the review, follow `documentation/TESTING_WRITING_TESTS.md`
  and use `@todo` or `@pytest.mark.unfinished` for durable
  backlog.
- In sandboxed Codex environments, localhost/browser access may require command
  approval. Outside the sandbox, a first-class browser tool may work directly.
