"""Verify the indexed owner query against real Datastore reference properties."""

from uuid import uuid4
from unittest.mock import patch

from google.cloud.datastore import Entity

from lagniappe.core.tools.database import get


# @matrix forms database : reference-query primary-secondary batching owner-deduplication
def test_form_reference_lookup_matches_primary_secondary_and_batched_owners():
    datastore = get.DATA.datastore
    kind = get.KINDS.models.value
    prefix = f"reference-query-{uuid4().hex}"
    forms = [Entity(datastore.key(kind, f"{prefix}-form-{i}")) for i in range(25)]
    rows = []

    def owner(name, entity_type="category", parent=None, **values):
        row = Entity(datastore.key(kind, f"{prefix}-{name}", parent=parent))
        row.update(type=entity_type, **values)
        rows.append(row)
        return row

    primary = owner("primary", form=forms[0].key)
    secondary = owner("secondary", forms=[forms[0].key])
    both = owner("both", form=forms[0].key, forms=[forms[-1].key], active=False, reserved=True)
    project = owner("project", entity_type="project")
    model = owner("model", entity_type="model", parent=project.key, form=forms[0].key)
    later = owner("later-model", entity_type="model", parent=project.key, form=forms[-1].key)
    owner("unrelated", form=datastore.key(kind, f"{prefix}-other-form"))
    owner("non-owner", entity_type="form", form=forms[0].key)

    # Minimal durable rows isolate this query boundary from form-save mutations.
    # All fixtures use this run's reserved kind and are deleted by exact key.
    try:
        datastore.put_multi(rows)
        api = datastore._datastore_api
        with patch.object(api, "run_query", wraps=api.run_query) as queries:
            result = get.form_users(forms[0])
            assert {row.key for row in result} == {
                primary.key, secondary.key, both.key, model.key, project.key,
            }
            assert len(result) == 5
            assert queries.call_count == 1

            queries.reset_mock()
            result = get.form_users(*forms, forms[0])
            assert {row.key for row in result} == {
                primary.key, secondary.key, both.key, model.key, later.key, project.key,
            }
            assert len(result) == 6
            assert queries.call_count == 2

        primary["form"] = forms[1].key
        datastore.put(primary)
        assert primary.key not in {row.key for row in get.form_users(forms[0])}
        assert {row.key for row in get.form_users(forms[1])} == {primary.key}
        assert get.form_users() == []
    finally:
        datastore.delete_multi([row.key for row in rows])
