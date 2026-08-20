"""Redis-backed workspace retrieval from saved file-summary terms."""

from .debug import ai_debug
from .function_definitions.search import execute_search
from .references import hash_reference


ORGANIZE_RETRIEVAL_RESULTS_PER_TERM = 5
ORGANIZE_RETRIEVAL_KINDS = ("category", "page", "form")


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_prepare_organize_retrieval_context_searches_bounded_structure_candidates
# @features ai-report search
# @dimensions summary-terms redis-search kinds limits fallback
def prepare_organize_retrieval_context(report, user):
    """Fetch bounded category/page/form candidates for saved summary terms."""
    files = list(getattr(report, "input_files", None) or [])
    if not files:
        return {}

    context = {}
    for file in files:
        file_ref = hash_reference(file)
        searches = []
        for term in _file_retrieval_terms(file):
            try:
                candidates = execute_search(
                    {
                        "query": term,
                        "kinds": list(ORGANIZE_RETRIEVAL_KINDS),
                        "limit": ORGANIZE_RETRIEVAL_RESULTS_PER_TERM,
                    },
                    user,
                )
            except Exception as error:  # Redis retrieval is optional prompt context.
                ai_debug(
                    "organize.retrieval.search_unavailable",
                    file_ref=file_ref,
                    term=term,
                    error_type=type(error).__name__,
                    error=str(error),
                )
                candidates = []
            searches.append({"term": term, "candidates": candidates})
        if searches:
            context[file_ref] = searches
    return context


# @testable false
# @covered-by lagniappe/core/tools/ai/organize_retrieval.py::prepare_organize_retrieval_context
# @reason persisted term cleanup is exercised through the public prepass
def _file_retrieval_terms(file):
    summarize = getattr(getattr(file, "properties", None), "summarize", None)
    values = getattr(summarize, "retrieval_terms", None) if summarize else None
    if not isinstance(values, list):
        return ()
    terms = []
    seen = set()
    for value in values:
        term = str(value or "").strip()
        normalized = term.casefold()
        if not term or len(term) > 80 or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) == 2:
            break
    return tuple(terms)
