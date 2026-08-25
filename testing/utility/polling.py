"""Observation-only helpers for the browser polling protocol."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .network import expect_successful_response


# @testable true
# @tests tests_tooling/test_004_network_waits.py::test_poll_wait_matches_subscription_and_validates_result
# @tests tests_tooling/test_004_network_waits.py::test_poll_wait_reports_missing_or_unexpected_result
# @matrix e2e polling : network-wait result-status subscription
@contextmanager
def expect_poll_result(
    page: Any,
    *,
    subscription_id: str,
    status: str | None = "changed",
    timeout: float | None = None,
) -> Iterator[Any]:
    """Observe one successful natural poll result for an exact subscription."""

    def check(response: Any) -> None:
        payload = response.json()
        assert payload.get("version") == 1, (
            f"POST /l/poll returned an invalid protocol version for "
            f"{subscription_id!r}: {payload!r}"
        )
        results = payload.get("results")
        assert isinstance(results, list), (
            f"POST /l/poll returned no result list for {subscription_id!r}: "
            f"{payload!r}"
        )
        result = next(
            (
                candidate
                for candidate in results
                if isinstance(candidate, dict)
                and candidate.get("id") == subscription_id
            ),
            None,
        )
        assert result is not None, (
            f"POST /l/poll did not return subscription {subscription_id!r}: "
            f"{results!r}"
        )
        if status is not None:
            assert result.get("status") == status, (
                f"POST /l/poll returned {result.get('status')!r} for "
                f"{subscription_id!r}; expected {status!r}. Result: {result!r}"
            )

    with expect_successful_response(
        page,
        method="POST",
        path="/l/poll",
        request_payload_contains=f'"id":"{subscription_id}"',
        response_check=check,
        timeout=timeout,
    ) as response_info:
        yield response_info
