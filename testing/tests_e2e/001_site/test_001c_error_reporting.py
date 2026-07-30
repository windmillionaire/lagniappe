# @features error-reporting ai files
# @dimensions expected-provider-failure pdf-page-limit privacy
def test_sentry_filter_drops_only_expected_ai_document_page_limit():
    from lagniappe.web import _filter_expected_sentry_errors

    expected = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": (
                        "The document contains 1203 pages which exceeds the "
                        "supported page limit of 1000."
                    ),
                }
            ]
        }
    }
    unrelated = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": "A different provider request was invalid.",
                }
            ]
        },
        "user": {"email": "private@example.test"},
    }

    assert _filter_expected_sentry_errors(expected, {}) is None
    filtered = _filter_expected_sentry_errors(unrelated, {})
    assert filtered is not None
    assert "user" not in filtered
