"""Shared, uncapped membership queries for Form preview and change execution."""

from ...definitions import Fetch
from ...entities import Entities
from ..database.core import KINDS
from ..database.filter import Filter, Query


BATCH_SIZE = 50


# @testable false
# @covered-by lagniappe/core/tools/forms/changes.py::apply_target
# @reason application and preflight use the same uncapped membership query, one bounded page at a time
def target_batch(form, cursor=None):
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("form", form.key))
        .order("__key__")
        .limit(BATCH_SIZE)
        .cursor(cursor)
        .fetch()
    )


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_form_authority_migrates_restricted_submissions
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_form_editor_migrates_restricted_submissions
# @matrix form-migration : form-authority restricted-submissions
def load_target(raw):
    if raw.get("type") not in {"page", "task"}:
        return None
    # The owning form authorizes schema migration across all attached submissions.
    # Page/Task permissions still govern viewing and directly editing their values.
    return Entities.fetch_one(raw, request=Fetch.direct())
