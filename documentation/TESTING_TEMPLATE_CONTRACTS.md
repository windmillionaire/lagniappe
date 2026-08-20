# Template contract tracking

`testing/utility/template_contracts.py` follows `@template` tags from E2E tests
into Jinja macros, imported macros, frontend handlers, and test selectors. It
helps distinguish contracts that are exercised directly from attributes that
still need review.

Run it through the repository runner:

```bash
venv/bin/python run.py template-contracts
venv/bin/python run.py template-contracts test_file.py::test_name
venv/bin/python run.py template-contracts template/path.html::macro
venv/bin/python run.py template-contracts --changed --check
```

The default output is a concise summary and stable findings. `--verbose` adds
every expanded macro, contract attribute, automated check, and selector-evidence
mapping.

Jinja imports resolve from `lagniappe/web/templates`, matching the application
loader. Macro traversal uses the Jinja AST, so ordinary calls, call blocks,
positional arguments, and keyword arguments are followed. Loops, conditionals,
and dynamic values remain explicit review notes instead of being presented as
certain coverage.

## Test annotation

Tag the test with the template macro that owns its stable DOM contract:

```python
# @template projects/info.html::info_form
# @features projects
# @dimensions update
def test_project_info_update(...):
    ...
```

Prefer the smallest macro that owns the behavior. A tag is not evidence by
itself: the report separately shows selector/helper evidence found in the test
and attributes covered through included tagged templates.

## Findings and exit status

Errors include missing templates/macros, unsupported `lp-*` vocabulary, and
controls whose routed target cannot be resolved. Frontend targets that need
human interpretation and branch/loop-dependent markup are review findings.

`--check` fails on errors by default. `--fail-on warning` also fails on warning
findings. Baselines use stable IDs:

```bash
venv/bin/python run.py template-contracts --write-baseline reports/template-contract-baseline.json
venv/bin/python run.py template-contracts --baseline reports/template-contract-baseline.json --check
```

`--changed [BASE]` includes contracts reached from changed tests or templates.
Any changed frontend module causes the full contract set to be checked because
handler and widget changes can affect every template. `BASE` defaults to
`HEAD`.

JSON uses the same versioned envelope and provenance fields as traceability.
Markdown defaults to `reports/template-contracts*.md`; use `--no-report` for a
terminal-only check.
