"""Run the synthetic Organize submission-completion corpus against the live model."""

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from lagniappe.core.tools.ai.core import ai_model
from lagniappe.core.tools.ai.organize import organize_submission_completion_prompt


CORPUS = Path(__file__).parents[1] / "files" / "organize_submission_eval.json"


def load_cases():
    """Load the synthetic Organize completion cases."""
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def rows_by_action(result):
    """Return completion rows indexed by their proposal action id."""
    rows = result.get("submissions") if isinstance(result, dict) else []
    return {
        row.get("action_id"): row.get("submission") or {}
        for row in rows
        if isinstance(row, dict) and row.get("action_id")
    }


def _case_field(case, action_id, field_id):
    records = {
        record.get("action_id"): record
        for record in case["context"].get("records", [])
    }
    forms = {
        form.get("form_ref"): form
        for form in case["context"].get("forms", [])
    }
    record = records.get(action_id) or {}
    form = forms.get(record.get("form_ref")) or {}
    return next(
        (
            field
            for field in form.get("schema", [])
            if field.get("id") == field_id
        ),
        None,
    )


def _values_equal(actual, expected, field=None):
    if field and field.get("input") == "number":
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError):
            return False
    if field and field.get("input") == "date":
        return str(actual or "").strip()[:10] == str(expected).strip()[:10]
    return str(actual or "").strip().casefold() == str(expected).strip().casefold()


def case_failures(case, result):
    """Return grounded-value and cross-role failures for one model result."""
    rows = rows_by_action(result)
    failures = []
    for action_id, expected in case["expected"].items():
        submission = rows.get(action_id, {})
        for field_id, value in expected.items():
            actual = submission.get(field_id)
            field = _case_field(case, action_id, field_id)
            if not _values_equal(actual, value, field):
                failures.append(
                    f"{action_id}.{field_id}: expected {value!r}, got "
                    f"{actual!r}"
                )
    for forbidden in case.get("forbidden", []):
        actual = rows.get(forbidden["action_id"], {}).get(forbidden["field_id"])
        field = _case_field(case, forbidden["action_id"], forbidden["field_id"])
        if _values_equal(actual, forbidden["value"], field):
            failures.append(
                f"{forbidden['action_id']}.{forbidden['field_id']}: "
                f"forbidden cross-role value appeared: {actual!r}"
            )
    return failures


def usability_failures(case, result):
    """Return failures that make a completion unusable by report execution."""
    failures = case_failures(case, result)
    rows = rows_by_action(result)
    records = {
        record.get("action_id"): record
        for record in case["context"].get("records", [])
    }
    forms = {
        form.get("form_ref"): form
        for form in case["context"].get("forms", [])
    }
    for action_id in case["expected"]:
        submission = rows.get(action_id)
        if not isinstance(submission, dict) or not submission:
            failures.append(f"{action_id}: submission is empty or missing")
            continue
        record = records.get(action_id) or {}
        form = forms.get(record.get("form_ref")) or {}
        allowed = {
            field.get("id")
            for field in form.get("schema", [])
            if isinstance(field, dict) and field.get("id")
        }
        unknown = sorted(set(submission) - allowed)
        if unknown:
            failures.append(
                f"{action_id}: submission contains fields outside its schema: {unknown}"
            )
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    cases = load_cases()
    ai_model.initialize()
    failures = []
    for run in range(1, args.runs + 1):
        for case in cases:
            prompt = organize_submission_completion_prompt(case["context"])
            result = ai_model.generate_content(prompt)
            case_failures = usability_failures(case, result)
            print(
                json.dumps(
                    {
                        "run": run,
                        "case": case["name"],
                        "passed": not case_failures,
                        "failures": case_failures,
                        "result": result,
                    },
                    indent=2,
                )
            )
            failures.extend(
                f"run {run} {case['name']}: {failure}"
                for failure in case_failures
            )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
