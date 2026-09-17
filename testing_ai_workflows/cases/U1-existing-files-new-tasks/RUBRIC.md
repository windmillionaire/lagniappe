# U1 — Create Tasks and move existing files without uploads

Operator-only. This isolates the original fileless Organize permission gap.
Case 08 uploads a new batch; case 03 creates one reminder. Neither checks this
combination of existing files, new Tasks, renames and dependency references.

## Preconditions

- Use the editable **AI UNIFICATION** category with two Pages:
  **Unified AI — Home Insurance** and **Unified AI — Property Tax & Assessments**.
- Attach `setup-files/insurance-record-2026.md` to the first Page and
  `setup-files/property-tax-2026.md` to the second. These are synthetic fixtures.
- Neither Page has the requested 2026 record Tasks. If an earlier proposal was
  executed, restore the fixture state deliberately before measuring again.
- Finish setup separately and record Page/file references. Do not include setup
  activity in the measured run. **No files are uploaded during this case.**
- The September 16 setup and both measured proposals were reviewed; the test
  proposals were not executed, so setup still remained available at readback.

## Expected result

- One reviewable proposal contains both requested Page renames, two new open
  Tasks on the first renamed Page, and both existing-file moves to their exact
  corresponding Tasks. Six actions suffice; equivalent valid structure is fine.
- File moves depend on the new Task actions and preserve each file's identity.
  Do not duplicate the files, create replacement Pages, or leave the tax file
  on the Assessments Page.
- Neither source establishes payment: no paid/completed claim, closed Task,
  or invented completion date.
- The answer describes proposed changes and links to the same saved Plan.
  Stop before execution. External changes must not be applied directly.

Use `PROMPT.md` for MCP or `PROMPT_ON_SITE.md` for the panel. Keep this rubric
and setup files outside the model's neutral working directory. The current
baseline includes both unified entry points; older split-workflow failures
remain in the ignored comparison archive, not mixed into current metrics.
