"""AI-facing short reference helpers."""

import re

from lagniappe.core.tools import cache
from lagniappe.core.tools.files.html import render_markdown


HASH_REFERENCE_REGEX = re.compile(r"\bhash:([0-9a-z]{12})\b")
HASH_PREFIXED_ID_REGEX = re.compile(r"\bhash:(ah[A-Za-z0-9_-]{30,})\b")
HASH_TOKEN_REGEX = re.compile(r"\bhash:([A-Za-z0-9_-]+)\b")


# @testable true
# @tests tests_unit/test_020b_ai_ask.py::test_validate_ask_response_renders_answer_markdown
# @tests tests_unit/test_032_agent_api.py::test_external_ask_submission_allows_hash_token_in_named_link_destination
# @pairs ai-report:answer-only markdown:html-sanitization
def render_ai_markdown(text):
    """Render model Markdown after resolving known AI references for browser use."""
    return render_markdown(normalize_hash_references(text))


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_hash_reference_normalizer_batches_lookup
# @matrix ai : batched-cache hash-reference normalization
def hash_reference(entity):
    """Return the explicit AI reference token for an entity hash."""
    entity_hash = getattr(entity, "hash", None)
    return f"hash:{entity_hash}" if entity_hash else None


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_hash_reference_normalizer_batches_lookup
# @matrix ai : batched-cache hash-reference normalization
def normalize_hash_references(value, *, resolved_details=None):
    """Replace known ``hash:...`` tokens with executable entity ids.

    The payload is scanned first so all hashes are resolved in one cache lookup.
    Unknown hashes remain unchanged.
    """
    hashes = _collect_hash_references(value)
    executable_ids = _collect_hash_prefixed_ids(value)
    replacements = {
        f"hash:{entity_id}": entity_id for entity_id in executable_ids
    }

    if hashes:
        details = cache.get_details_by_hash(hashes)
        if resolved_details is not None:
            resolved_details.update(details)
        replacements.update(
            {
                f"hash:{entity_hash}": item["id"]
                for entity_hash, item in details.items()
                if isinstance(item, dict) and item.get("id")
            }
        )
    if not replacements:
        return value

    return _replace_hash_references(value, replacements)


# @testable false
# @covered-by lagniappe/core/tools/ai/references.py::normalize_hash_references
# @reason recursive collection is covered through normalizer behavior
def _collect_hash_references(value):
    hashes = []
    if isinstance(value, dict):
        for key, child in value.items():
            hashes.extend(_collect_hash_references(key))
            hashes.extend(_collect_hash_references(child))
    elif isinstance(value, list):
        for child in value:
            hashes.extend(_collect_hash_references(child))
    elif isinstance(value, str):
        hashes.extend(HASH_REFERENCE_REGEX.findall(value))
    return list(dict.fromkeys(hashes))


# @testable false
# @covered-by lagniappe/core/tools/ai/references.py::normalize_hash_references
# @reason recursive collection is covered through normalizer behavior
def _collect_hash_prefixed_ids(value):
    ids = []
    if isinstance(value, dict):
        for key, child in value.items():
            ids.extend(_collect_hash_prefixed_ids(key))
            ids.extend(_collect_hash_prefixed_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_collect_hash_prefixed_ids(child))
    elif isinstance(value, str):
        ids.extend(HASH_PREFIXED_ID_REGEX.findall(value))
    return list(dict.fromkeys(ids))


# @testable false
# @covered-by lagniappe/core/tools/ai/references.py::normalize_hash_references
# @reason recursive replacement is covered through normalizer behavior
def _replace_hash_references(value, replacements):
    if isinstance(value, dict):
        return {
            _replace_hash_references(key, replacements): _replace_hash_references(
                child,
                replacements,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_hash_references(child, replacements) for child in value]
    if not isinstance(value, str):
        return value

    return HASH_TOKEN_REGEX.sub(
        lambda match: replacements.get(match.group(0), match.group(0)),
        value,
    )
