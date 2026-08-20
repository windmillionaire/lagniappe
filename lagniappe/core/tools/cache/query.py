"""Cache query operations for entity search."""

import re

from markupsafe import Markup, escape
from redis.commands.search.query import Query

from lagniappe import CONFIG
from lagniappe.core.definitions import Restriction

from .core import cache
from .details import hydrate_search_results
from .keys import Search

HIGHLIGHT_OPEN = "\x02lagniappe-highlight-open\x03"
HIGHLIGHT_CLOSE = "\x02lagniappe-highlight-close\x03"
PIPE = re.compile(r"(?<!\\)\|")
SUBSTITUTE = re.compile(r"[^a-zA-Z0-9\s]")
PRIMARY_NAME_KINDS = ("category", "project", "page")
PRIMARY_NAME_BOOST = 4.0
SEARCH_QUERY_DIALECT = 2

STOPWORDS = frozenset(
    {
        "a",
        "is",
        "the",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
    }
)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_prunes_stale_rows_without_entity_details
# @pairs search:stale-row cache:self-repair
def _current_search_results(results):
    """Hydrate results and remove projections whose entity details are gone."""
    hydrated = hydrate_search_results(results)
    stale = [result for result in hydrated if not result.get("details")]
    keys = [
        Search[result.get("kind")].value.format(result.get("id"))
        for result in stale
        if Search[result.get("kind")].value and result.get("id")
    ]
    if keys:
        cache.delete(*keys)
    return [result for result in hydrated if result.get("details")], len(stale)


# @testable false
# @covered-by lagniappe/core/tools/cache/query.py::_add_snippet
# @reason pipe decoding is owned by highlighted form-value snippets
def _unescape_pipe(text):
    """Unescape pipe and backslash after splitting."""
    if not isinstance(text, str):
        return text
    # First unescape pipes, then backslashes
    return text.replace("\\|", "|").replace("\\\\", "\\")


# @testable false
# @covered-by lagniappe/core/tools/cache/query.py::_add_snippet
# @reason Redis highlight markers are normalized by snippet formatting
def _split_first_highlight(text):
    """Return text around the first generated highlight marker pair."""
    if not isinstance(text, str):
        return None

    start = text.find(HIGHLIGHT_OPEN)
    if start < 0:
        return None

    highlighted_start = start + len(HIGHLIGHT_OPEN)
    end = text.find(HIGHLIGHT_CLOSE, highlighted_start)
    if end < 0:
        return None

    return (
        text[:start],
        text[highlighted_start:end],
        text[end + len(HIGHLIGHT_CLOSE) :],
    )


# @testable false
# @covered-by lagniappe/core/tools/cache/query.py::_add_snippet
# @reason Redis highlight markers are normalized by snippet formatting
def _highlighted_html(text):
    """Escape snippet text and preserve only generated highlight tags."""
    if not isinstance(text, str):
        return Markup("")

    parts = []
    remaining = text
    while True:
        highlighted = _split_first_highlight(remaining)
        if not highlighted:
            parts.append(escape(remaining))
            break

        before, value, after = highlighted
        parts.append(escape(before))
        parts.append(Markup("<b>") + escape(value) + Markup("</b>"))
        remaining = after

    return Markup("").join(parts)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_term_list_normalizes_stopwords_and_special_characters
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_exact_match
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_partial_match
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_special_characters
# @tests tests_e2e/009_search/test_009a_search_page.py::test_primary_name_matches_rank_above_file_name_and_description_matches
# @features search
# @dimensions term-normalization stopwords exact-match partial-match special-characters primary-name-ranking
def _build_term_list(user_query, expanded=False):
    normalized = SUBSTITUTE.sub(" ", user_query)
    terms = [t for t in normalized.split() if len(t) > 1 and t.lower() not in STOPWORDS]
    if not expanded:
        return [f"(@name:{term}*)" for term in terms]

    expanded_terms = [
        f"((@name:{term}*) | (@desc:{term}*) | (@doc:{term}*) | (@values:{term}*))"
        for term in terms
    ]
    if not terms:
        return expanded_terms

    kinds = " | ".join(PRIMARY_NAME_KINDS)
    name_terms = " ".join(f"(@name:{term}*)" for term in terms)
    expanded_terms.append(
        f"~((@kind:{{ {kinds} }}) {name_terms}) "
        f"=> {{ $weight: {PRIMARY_NAME_BOOST}; }}"
    )
    return expanded_terms


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_permission_fragments_require_lists
# @features search
# @dimensions permissions validation
def _add_required(required):
    if not isinstance(required, list):
        raise TypeError("Required must be a list of hashes")
    if not required:
        return '(@requires:{""})'
    return f"(@requires:{{ {' | '.join(required)} }})"


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_permission_fragments_require_lists
# @features search
# @dimensions permissions validation
def _add_restricted_to(restricted_to):
    if not isinstance(restricted_to, list):
        raise TypeError("Restricted to must be a list of hashes")
    if not restricted_to:
        return "(ismissing(@restricted_to))"
    return f"(ismissing(@restricted_to) | @restricted_to:{{ {' | '.join(restricted_to)} }})"


# @testable false
# @covered-by lagniappe/core/tools/cache/query.py::search
# @covered-by lagniappe/core/tools/cache/query.py::kind_search
# @covered-by lagniappe/core/tools/cache/query.py::entity_search
# @reason result formatting belongs to outward search workflows
def _format_result(doc, snippets=False):
    result = {
        "id": doc.id.replace(CONFIG.PREFIX, "").split(":")[1],
        "kind": doc.kind,
        "name": doc.name,
    }
    if hasattr(doc, "details_key"):
        result["details_key"] = doc.details_key
    elif hasattr(doc, "hash"):
        result["details_key"] = doc.hash
    if hasattr(doc, "parent_key"):
        result["parent_key"] = doc.parent_key
    if snippets:
        _add_snippet(result, doc)

    return result


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_snippet_extracts_highlighted_text_and_form_values
# @tests tests_unit/test_017_cache_query.py::test_search_snippet_skips_highlighted_value_without_matching_key
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_result_snippets
# @features search
# @dimensions snippets highlighted-text form-value pipe-escaping html-escaping malformed-cache
def _add_snippet(result, doc):
    if hasattr(doc, "desc"):
        if _split_first_highlight(doc.desc):
            result["text"] = _highlighted_html(doc.desc)

    if hasattr(doc, "doc") and not result.get("text"):
        if _split_first_highlight(doc.doc):
            result["text"] = _highlighted_html(doc.doc)

    if result.get("text") or not hasattr(doc, "values"):
        return

    if not _split_first_highlight(doc.values):
        return

    values = [_unescape_pipe(v) for v in PIPE.split(doc.values)]
    keys = [_unescape_pipe(k) for k in PIPE.split(doc.keys)]

    for i, value in enumerate(values):
        highlighted_match = _split_first_highlight(value)
        if not highlighted_match:
            continue
        if i >= len(keys):
            continue

        result["form_field"] = keys[i]
        before, highlighted, after = highlighted_match

        before_words = before.split()[-10:] if before else []
        after_words = after.split()[:10] if after else []

        snippet_parts = []
        if before and len(before.split()) > 10:
            snippet_parts.append("...")
        snippet_parts.extend(before_words)
        snippet_parts.append(f"{HIGHLIGHT_OPEN}{highlighted}{HIGHLIGHT_CLOSE}")
        snippet_parts.extend(after_words)
        if after and len(after.split()) > 10:
            snippet_parts.append("...")

        snippet = " ".join(snippet_parts)
        result["form_value"] = _highlighted_html(snippet)
        break


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_task_facet_includes_task_and_model_results_with_links
# @features search
# @dimensions facet-filter task-model
def _expand_result_kinds(kinds):
    """Return cache kinds represented by the requested search facets."""
    expanded = []
    for kind in kinds or []:
        expanded.append(kind)
        if kind == "task":
            expanded.append("model")
    return list(dict.fromkeys(expanded))


# @testable infrastructure
def entity_search(query_string, restrictions, belongs_to):
    """Search cached entities by query string with permission filtering."""
    term_list = _build_term_list(query_string)

    if not Restriction.is_unrestricted(restrictions):
        term_list.append(_add_required(restrictions))

    term_list.append(_add_restricted_to(belongs_to))

    if term_list:
        redis_query = Query(" ".join(term_list))
        results = cache.search(redis_query)
        formatted_results = [
            _format_result(doc, snippets=False) for doc in results.docs
        ]
        return _current_search_results(formatted_results)[0]
    else:
        return []


# @testable infrastructure
def _add_models(results, project_hashes):
    if not project_hashes:
        return [doc for doc in results.docs]

    get_models = " | ".join(project_hashes)
    result_ids = set([doc.id for doc in results.docs])
    expanded_results = []

    models = cache.search(Query(f"@kind:{{ model }} @requires:{{ {get_models} }}"))
    to_append = {h: [m for m in models.docs if h in m.requires] for h in project_hashes}

    for result in results.docs:
        expanded_results.append(result)
        if hasattr(result, "hash") and to_append.get(result.hash):
            for m in to_append.get(result.hash):
                if m.id not in result_ids:
                    expanded_results.append(m)

    return expanded_results


# @testable infrastructure
# @tests tests_unit/test_017_cache_query.py::test_search_queries_use_redis_cloud_compatible_tag_syntax
# @features search
# @dimensions redis-cloud tag-syntax permissions empty-access
def kind_search(query_string, kind, restrictions, belongs_to, **kwargs):
    """Search cached entities filtered by kind and optional form type."""
    term_list = _build_term_list(query_string) if query_string else []

    if kind == "project" and kwargs.get("models"):
        kinds = ["project", "model"]
    elif kind == "page" and kwargs.get("include_users"):
        kinds = ["page", "user"]
    elif kind == "page" and not kwargs.get("include_users"):
        kinds = ["page"]
    else:
        kinds = [kind]

    term_list.append(f"(@kind:{{ {' | '.join(kinds)} }})")

    term_list.append(_add_restricted_to(belongs_to))

    if kwargs.get("form_type"):
        term_list.append(f"(@type:{{ {kwargs.get('form_type')} }})")

    if not Restriction.is_unrestricted(restrictions):
        term_list.append(_add_required(restrictions))

    redis_query = Query(" ".join(term_list))
    results = cache.search(redis_query)

    if kind == "project" and kwargs.get("models"):
        project_hashes = [doc.hash for doc in results.docs if doc.kind == "project"]
        expanded = _add_models(results, project_hashes)
        formatted_results = [_format_result(doc, snippets=False) for doc in expanded]
    else:
        formatted_results = [
            _format_result(doc, snippets=False) for doc in results.docs
        ]
    return _current_search_results(formatted_results)[0]


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_search_queries_use_redis_cloud_compatible_tag_syntax
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_returns_results
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_no_results
# @tests tests_e2e/009_search/test_009a_search_page.py::test_primary_name_matches_rank_above_file_name_and_description_matches
# @features search
# @dimensions results no-results redis-cloud tag-syntax permissions empty-access primary-name-ranking
def search(user_query, required, belongs_to, kinds=None, page=1, limit=10):
    """Run a full-text search with highlighting, snippets, and pagination."""
    term_list = _build_term_list(user_query, expanded=True)

    expanded_kinds = _expand_result_kinds(kinds)
    if expanded_kinds:
        term_list.append(f"(@kind:{{ {' | '.join(expanded_kinds)} }})")

    if not Restriction.is_unrestricted(required):
        term_list.append(_add_required(required))

    term_list.append(_add_restricted_to(belongs_to))

    if term_list:
        redis_query = (
            Query(" ".join(term_list))
            .dialect(SEARCH_QUERY_DIALECT)
            .highlight(
                fields=["desc", "doc", "values"],
                tags=[HIGHLIGHT_OPEN, HIGHLIGHT_CLOSE],
            )
            .summarize(fields=["desc", "doc"], num_frags=1, context_len=25)
            .paging(offset=(page - 1) * limit, num=limit)
        )
        results = cache.search(redis_query)
        formatted_results = [
            _format_result(doc, snippets=True) for doc in results.docs
        ]
        formatted_results, stale_count = _current_search_results(formatted_results)
        return formatted_results, max(0, results.total - stale_count)
    else:
        return [], 0
