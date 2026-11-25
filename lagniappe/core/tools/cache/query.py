"""Cache query operations for entity search."""

from collections.abc import Collection
from typing import Literal
from ...restrictions import QueryHashes
from .details import SearchRecord

import re

from markupsafe import Markup, escape
from redis.commands.search.query import Query

from lagniappe import CONFIG
from lagniappe.core.definitions import Restriction
from ..auth.restrictions import RESTRICTION_SOURCES

from .core import cache
from .details import hydrate_search_results
from .keys import Search
from .help import ensure_help, help_clause

HIGHLIGHT_OPEN = "\x02lagniappe-highlight-open\x03"
HIGHLIGHT_CLOSE = "\x02lagniappe-highlight-close\x03"
PIPE = re.compile(r"(?<!\\)\|")
SUBSTITUTE = re.compile(r"[^a-zA-Z0-9\s]")
PRIMARY_NAME_KINDS = ("category", "project", "page")
PRIMARY_NAME_BOOST = 4.0
SEARCH_QUERY_DIALECT = 2
EXACT_LOOKUP_CANDIDATE_LIMIT = 100
CANDIDATE_SEARCH_LIMIT = 100
CANDIDATE_RELAXATION_MAX_TERMS = 12
CANDIDATE_MIN_STRICT_RESULTS = 3

type GroupScope = list[str] | Literal[Restriction.BELONGS_TO_ALL, Restriction.BELONGS_TO_NONE]


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


def _current_search_results(results):
    """Hydrate results and remove projections whose entity details are gone."""
    entities = iter(hydrate_search_results([result for result in results if result.get("kind") != "help"]))
    hydrated = [result if result.get("kind") == "help" else next(entities) for result in results]
    stale = [result for result in hydrated if not result.get("details")]
    keys = [
        Search[result.get("kind") or ""].value.format(result.get("id"))
        for result in stale
        if Search[result.get("kind") or ""].value and result.get("id")
    ]
    if keys:
        cache.delete(*keys)
    return [result for result in hydrated if result.get("details")], len(stale)


def _unescape_pipe(text):
    """Unescape pipe and backslash after splitting."""
    if not isinstance(text, str):
        return text
    # First unescape pipes, then backslashes
    return text.replace("\\|", "|").replace("\\\\", "\\")


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


def _add_required(required):
    if not isinstance(required, list):
        raise TypeError("Required must be a list of hashes")
    if not required:
        raise ValueError("Required must contain at least one hash")
    return f"(@requires:{{ {' | '.join(required)} }})"


def _add_restricted_to(belongs_to):
    """Match any group within every present restriction source before paging."""
    if belongs_to is Restriction.BELONGS_TO_ALL:
        return ""
    if belongs_to is Restriction.BELONGS_TO_NONE:
        belongs_to = []
    if not isinstance(belongs_to, list):
        raise TypeError(
            "Group membership must be hashes, Restriction.BELONGS_TO_ALL, "
            "or Restriction.BELONGS_TO_NONE"
        )
    groups = " | ".join(sorted(set(belongs_to)))
    return " ".join(
        f"(ismissing(@restricted_to_{source}) | @restricted_to_{source}:{{ {groups} }})"
        if groups else f"(ismissing(@restricted_to_{source}))"
        for source in RESTRICTION_SOURCES
    )


def _format_result(doc, snippets=False):
    if doc.kind == "help":
        from lagniappe.reference import get_topic

        topic = get_topic(doc.topic_id)
        result = {
            "id": topic.id, "kind": "help", "name": topic.title,
            "details": {"id": topic.id, "kind": "help", "name": topic.title,
                        "icon": "help", "url": topic.url},
        }
        if snippets:
            _add_snippet(result, doc)
            result.setdefault("text", escape(topic.summary))
        return result
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


def _add_snippet(result, doc):
    if hasattr(doc, "desc") and _split_first_highlight(doc.desc):
        result["text"] = _highlighted_html(doc.desc)

    if hasattr(doc, "doc") and not result.get("text") and _split_first_highlight(doc.doc):
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


def _expand_result_kinds(kinds):
    """Return cache kinds represented by the requested search facets."""
    expanded = []
    for kind in kinds or []:
        expanded.append(kind)
        if kind == "task":
            expanded.append("model")
    return list(dict.fromkeys(expanded))


def entity_search(
    query_string: str, restrictions: QueryHashes, belongs_to: GroupScope
) -> list[SearchRecord]:
    """Search cached entities by query string with permission filtering."""
    if Restriction.is_denied(restrictions):
        return []

    term_list = _build_term_list(query_string)
    term_list.append("(-@kind:{ help })")

    if not Restriction.is_unrestricted(restrictions):
        term_list.append(_add_required(restrictions))

    term_list.append(_add_restricted_to(belongs_to))

    if term_list:
        redis_query = Query(" ".join(filter(None, term_list)) or "*").dialect(SEARCH_QUERY_DIALECT)
        results = cache.search(redis_query)
        formatted_results = [
            _format_result(doc, snippets=False) for doc in results.docs
        ]
        return _current_search_results(formatted_results)[0]
    else:
        return []


def _add_models(results, project_hashes, restriction_clause):
    if not project_hashes:
        return [doc for doc in results.docs]

    get_models = " | ".join(project_hashes)
    result_ids = set([doc.id for doc in results.docs])
    expanded_results = []

    models = cache.search(Query(
        f"@kind:{{ model }} @requires:{{ {get_models} }} {restriction_clause}".strip()
    ).dialect(SEARCH_QUERY_DIALECT))
    to_append = {h: [m for m in models.docs if h in m.requires] for h in project_hashes}

    for result in results.docs:
        expanded_results.append(result)
        if hasattr(result, "hash") and to_append.get(result.hash):
            for m in to_append[result.hash]:
                if m.id not in result_ids:
                    expanded_results.append(m)

    return expanded_results


def kind_search(
    query_string: str,
    kind: str,
    restrictions: QueryHashes,
    belongs_to: GroupScope,
    **kwargs: str | bool | None,
) -> list[SearchRecord]:
    """Search cached entities filtered by kind and optional form type."""
    if kind == "help" or Restriction.is_denied(restrictions):
        return []

    term_list = _build_term_list(query_string) if query_string else []

    if kind == "file-owner":
        kinds = ["page", "task", "user"]
    elif kind == "project" and kwargs.get("models"):
        kinds = ["project", "model"]
    elif kind == "page" and kwargs.get("include_users"):
        kinds = ["page", "user"]
    elif kind == "page" and not kwargs.get("include_users"):
        kinds = ["page"]
    else:
        kinds = [kind]

    term_list.append(f"(@kind:{{ {' | '.join(kinds)} }})")

    restriction_clause = _add_restricted_to(belongs_to)
    term_list.append(restriction_clause)

    if kwargs.get("form_type"):
        term_list.append(f"(@type:{{ {kwargs.get('form_type')} }})")

    if not Restriction.is_unrestricted(restrictions):
        term_list.append(_add_required(restrictions))

    redis_query = Query(" ".join(filter(None, term_list))).dialect(SEARCH_QUERY_DIALECT)
    results = cache.search(redis_query)

    if kind == "project" and kwargs.get("models"):
        project_hashes = [doc.hash for doc in results.docs if doc.kind == "project"]
        expanded = _add_models(results, project_hashes, restriction_clause)
        formatted_results = [_format_result(doc, snippets=False) for doc in expanded]
    else:
        formatted_results = [
            _format_result(doc, snippets=False) for doc in results.docs
        ]
    return _current_search_results(formatted_results)[0]


def search(
    user_query: str,
    required: QueryHashes,
    belongs_to: GroupScope,
    kinds: Collection[str] | None = None,
    page: int = 1,
    limit: int = 10,
    *,
    include_help: bool = False,
) -> tuple[list[SearchRecord], int]:
    """Run a full-text search with highlighting, snippets, and pagination."""
    allow_help = include_help and (not kinds or "help" in kinds)
    if Restriction.is_denied(required) and not allow_help:
        return [], 0

    term_list = _build_term_list(user_query, expanded=True)

    expanded_kinds = [kind for kind in _expand_result_kinds(kinds) if kind != "help"]
    scopes = []
    if not Restriction.is_denied(required) and (not kinds or expanded_kinds):
        entity_scope = ["(-@kind:{ help })"]
        if expanded_kinds:
            entity_scope.append(f"(@kind:{{ {' | '.join(expanded_kinds)} }})")
        if not Restriction.is_unrestricted(required):
            entity_scope.append(_add_required(required))
        entity_scope.append(_add_restricted_to(belongs_to))
        scopes.append("(" + " ".join(filter(None, entity_scope)) + ")")
    if allow_help:
        scopes.append(help_clause(ensure_help()))
    if not scopes:
        return [], 0
    # Visibility clauses select records; their differing shapes must not boost
    # entities over help with the same text and a higher document weight.
    term_list.append("(" + " | ".join(scopes) + ") => { $weight: 0; }")

    if term_list:
        redis_query = (
            Query(" ".join(filter(None, term_list)) or "*")
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


def exact_name_search(
    name: str,
    required: QueryHashes,
    belongs_to: GroupScope,
    *,
    kinds: Collection[str] | None = None,
    parent_hash: str | None = None,
    limit: int = 10,
) -> list[SearchRecord]:
    """Run a bounded exact-name lookup without changing full-text ``search``."""
    if Restriction.is_denied(required):
        return []

    normalized_name = " ".join(str(name or "").split())
    if not normalized_name:
        return []

    term_list = _build_term_list(normalized_name)
    term_list.append("(-@kind:{ help })")
    expanded_kinds = _expand_result_kinds(kinds)
    if expanded_kinds:
        term_list.append(f"(@kind:{{ {' | '.join(expanded_kinds)} }})")
    if parent_hash:
        term_list.append(_add_required([parent_hash]))
    if not Restriction.is_unrestricted(required):
        term_list.append(_add_required(required))
    term_list.append(_add_restricted_to(belongs_to))

    candidate_limit = min(
        EXACT_LOOKUP_CANDIDATE_LIMIT,
        max(int(limit or 1) * 4, 25),
    )
    redis_query = (
        Query(" ".join(filter(None, term_list)) or "*")
        .dialect(SEARCH_QUERY_DIALECT)
        .paging(offset=0, num=candidate_limit)
    )
    results = cache.search(redis_query)
    formatted = [_format_result(doc, snippets=False) for doc in results.docs]
    current, _stale_count = _current_search_results(formatted)
    exact = [
        result
        for result in current
        if " ".join(str(result.get("name") or "").split()).casefold()
        == normalized_name.casefold()
    ]
    return exact[: max(1, int(limit or 1))]


def candidate_search(
    user_query: str,
    required: QueryHashes,
    belongs_to: GroupScope,
    *,
    kinds: Collection[str] | None = None,
    parent_hash: str | None = None,
    limit: int = 10,
) -> list[SearchRecord]:
    """Return bounded AI candidates, relaxing sparse multiword searches once."""
    if Restriction.is_denied(required):
        return []

    terms = list(dict.fromkeys(
        term.casefold()
        for term in SUBSTITUTE.sub(" ", str(user_query or "")).split()
        if len(term) > 1 and term.casefold() not in STOPWORDS
    ))
    if not terms:
        return []

    limit = max(1, min(int(limit or 1), CANDIDATE_SEARCH_LIMIT))
    pool_limit = min(CANDIDATE_SEARCH_LIMIT, max(limit * 4, 25))
    term_list = _build_term_list(" ".join(terms), expanded=True)
    scope = ["(-@kind:{ help })"]
    expanded_kinds = _expand_result_kinds(kinds)
    if expanded_kinds:
        scope.append(f"(@kind:{{ {' | '.join(expanded_kinds)} }})")
    if parent_hash:
        scope.append(_add_required([parent_hash]))
    if not Restriction.is_unrestricted(required):
        scope.append(_add_required(required))
    scope.append(_add_restricted_to(belongs_to))

    strict = _candidate_query(term_list + scope, pool_limit)
    strict_ids = {result["id"] for result in strict}
    normalized_name = " ".join(str(user_query or "").split()).casefold()
    candidates = {result["id"]: result for result in strict}
    if (
        1 < len(terms) <= CANDIDATE_RELAXATION_MAX_TERMS
        and len(strict) < min(limit, CANDIDATE_MIN_STRICT_RESULTS)
        and not any(
            " ".join(str(result.get("name") or "").split()).casefold()
            == normalized_name
            for result in strict
        )
    ):
        # Keep the optional name boost and all access clauses outside the OR.
        relaxed = ["(" + " | ".join(term_list[:len(terms)]) + ")"]
        relaxed.extend(term_list[len(terms):])
        for result in _candidate_query(relaxed + scope, pool_limit):
            candidates.setdefault(result["id"], result)

    ordered = sorted(
        candidates.values(),
        key=lambda result: _candidate_rank(result, normalized_name, terms, strict_ids),
    )
    for result in ordered:
        result.pop("_candidate_score", None)
    return ordered[:limit]


def _candidate_query(clauses, limit):
    redis_query = (
        Query(" ".join(filter(None, clauses)))
        .dialect(SEARCH_QUERY_DIALECT)
        .with_scores()
        .highlight(
            fields=["desc", "doc", "values"],
            tags=[HIGHLIGHT_OPEN, HIGHLIGHT_CLOSE],
        )
        .summarize(fields=["desc", "doc"], num_frags=1, context_len=25)
        .paging(offset=0, num=limit)
    )
    results = cache.search(redis_query)
    formatted = [
        {
            **_format_result(doc, snippets=True),
            "_candidate_score": float(getattr(doc, "score", 0) or 0),
        }
        for doc in results.docs
    ]
    return _current_search_results(formatted)[0]


def _candidate_rank(result, normalized_name, terms, strict_ids):
    name = " ".join(str(result.get("name") or "").split()).casefold()
    name_words = SUBSTITUTE.sub(" ", name).split()
    name_coverage = sum(
        any(word.startswith(term) for word in name_words) for term in terms
    )
    return (
        name != normalized_name,
        result["id"] not in strict_ids,
        -name_coverage,
        -result["_candidate_score"],
        name,
        result["id"],
    )
