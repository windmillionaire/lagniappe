"""Reference normalization helpers for AI report proposals."""

from typing import TypeGuard


def _proposal_file_refs(data):
    refs = []
    for key in ("file", "file_id", "file_ref"):
        if data.get(key):
            refs.append(data[key])
    files = data.get("files") or data.get("file_ids") or data.get("file_refs") or []
    if isinstance(files, str):
        refs.append(files)
    elif isinstance(files, list):
        refs.extend(value for value in files if value)
    return refs


def _referenced_action_ids(action):
    yield from _explicit_dependency_ids(action)
    data = action.get("data") or {}
    yield from _data_action_references(data)


def _explicit_dependency_ids(action):
    dependencies = action.get("depends_on") or []
    if isinstance(dependencies, str) or not isinstance(dependencies, list):
        dependencies = [dependencies]

    for dependency in dependencies:
        if isinstance(dependency, str):
            yield _strip_action_reference(dependency)


def _strip_action_reference(value):
    if value.startswith("$"):
        return value[1:]
    if value.startswith("action:"):
        return value.split(":", 1)[1]
    return value


def _data_action_reference(data, root):
    value = data.get(f"{root}_action")
    if isinstance(value, str) and value:
        return _strip_action_reference(value)

    value = data.get(root)
    if isinstance(value, dict) and isinstance(value.get("action"), str):
        return _strip_action_reference(value["action"])
    if isinstance(value, str) and value.startswith(("$", "action:")):
        return _strip_action_reference(value)
    return None


def _first_data_reference(data, *keys):
    for key in keys:
        for candidate in (key, f"{key}_id", f"{key}_ref", f"{key}_action"):
            value = data.get(candidate)
            if value:
                return value
    return None


def _has_form_reference_or_label(data):
    if _first_data_reference(data, "form"):
        return True
    return any(
        bool(data.get(key)) for key in ("form_name", "form_display", "form_label")
    )


def _proposal_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _data_action_references(value, key=None):
    # Form field ids are user-defined and may legitimately be ``action`` or end
    # in ``_action``. Submission values are content, never proposal references,
    # so keep that namespace and the authored artifact HTML opaque to the walk.
    if key in {"submission", "description", "name", "artifact_html"}:
        return

    if isinstance(value, dict):
        action = value.get("action")
        if isinstance(action, str):
            yield _strip_action_reference(action)
        for child_key, child in value.items():
            yield from _data_action_references(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _data_action_references(child, key)
    elif isinstance(value, str) and (
        value.startswith("$")
        or value.startswith("action:")
        or key
        and key.endswith("_action")
    ):
        yield _strip_action_reference(value)
