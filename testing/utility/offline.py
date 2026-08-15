from contextlib import contextmanager
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


OFFLINE_RECORDS = """
async (storeName) => await new Promise((resolve) => {
        const request = indexedDB.open("offline-db", 5);
        request.onerror = () => resolve(null);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("sync")) {
                db.createObjectStore("sync", { keyPath: "sync_id" });
            }
            if (!db.objectStoreNames.contains("mutations")) {
                db.createObjectStore("mutations", { keyPath: "id" });
            }
        };
        request.onsuccess = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(storeName)) {
                db.close();
                resolve([]);
                return;
            }
            const transaction = db.transaction(storeName, "readonly");
            const recordsRequest = transaction.objectStore(storeName).getAll();
            recordsRequest.onsuccess = () => resolve(recordsRequest.result || []);
            recordsRequest.onerror = () => resolve(null);
            transaction.oncomplete = () => db.close();
            transaction.onerror = () => {
                db.close();
                resolve(null);
            };
        };
})
"""

OFFLINE_RECORD_WAIT = f"""
async ({{ storeName, minimum, exact, savedHtmlContains, recordKey, recordValue }}) => {{
    const readRecords = {OFFLINE_RECORDS};
    const rows = await readRecords(storeName);
    if (!Array.isArray(rows)) return false;
    const scopedRows = recordValue === null
        ? rows
        : rows.filter((row) => row?.[recordKey] === recordValue);
    const countMatches = exact === null
        ? minimum === null || scopedRows.length >= minimum
        : scopedRows.length === exact;
    const contentMatches = savedHtmlContains.length === 0 || scopedRows.some((row) =>
        row?.save === true &&
        typeof row?.html === "string" &&
        savedHtmlContains.every((part) => row.html.includes(part))
    );
    return countMatches && contentMatches ? scopedRows : false;
}}
"""

SYNC_MANAGER_READY = """
async () => {
    const view = document.querySelector("[lp-view]")?._lp_view;
    const manager = await view?.syncReady;
    if (!manager) return false;
    await manager.ready;
    return true;
}
"""


@contextmanager
def expect_offline_sync_replay(
    user,
    *,
    request_payload_contains,
    expected_count=1,
):
    """Observe startup-owned document replay and await its SyncManager."""
    markers = (
        (request_payload_contains,)
        if isinstance(request_payload_contains, str)
        else tuple(request_payload_contains)
    )
    if not markers:
        raise ValueError("Offline sync replay waits require request payload markers.")
    if expected_count < 1:
        raise ValueError("Offline sync replay waits require a positive response count.")

    page = user.page
    responses = []

    def record_replay(response):
        request = response.request
        body = request.post_data or ""
        if (
            request.method == "POST"
            and urlsplit(response.url).path == "/l/sync"
            and all(marker in body for marker in markers)
        ):
            responses.append(response)

    page.on("response", record_replay)
    try:
        yield responses
        manager_ready = page.evaluate(SYNC_MANAGER_READY)
    finally:
        page.remove_listener("response", record_replay)

    assert manager_ready, "Persisted document replay did not start SyncManager"
    assert len(responses) == expected_count, (
        f"Expected {expected_count} matching offline sync replay response(s), "
        f"received {len(responses)}."
    )
    assert all(response.ok for response in responses), (
        "Offline sync replay returned a non-success response."
    )


def _validate_record_wait(*, minimum, exact, saved_html_contains):
    if minimum is not None and exact is not None:
        raise ValueError(
            "Offline record waits accept either minimum or exact, not both."
        )
    if minimum is None and exact is None and not saved_html_contains:
        raise ValueError("Offline record waits require a count or saved HTML condition.")
    for label, value in (("minimum", minimum), ("exact", exact)):
        if value is not None and value < 0:
            raise ValueError(f"Offline record {label} must be non-negative.")


def _record_wait_description(
    *, minimum, exact, saved_html_contains, record_key, record_value
):
    conditions = []
    if record_value is not None:
        conditions.append(f"{record_key}={record_value!r}")
    if exact is not None:
        conditions.append(f"exactly {exact} record(s)")
    elif minimum is not None:
        conditions.append(f"at least {minimum} record(s)")
    if saved_html_contains:
        conditions.append(f"saved HTML containing {saved_html_contains!r}")
    return " and ".join(conditions)


def _wait_for_offline_records(
    user,
    store_name,
    *,
    minimum=None,
    exact=None,
    saved_html_contains=(),
    record_key=None,
    record_value=None,
    timeout=None,
):
    saved_html_contains = tuple(saved_html_contains)
    _validate_record_wait(
        minimum=minimum,
        exact=exact,
        saved_html_contains=saved_html_contains,
    )
    args = {
        "storeName": store_name,
        "minimum": minimum,
        "exact": exact,
        "savedHtmlContains": list(saved_html_contains),
        "recordKey": record_key,
        "recordValue": record_value,
    }
    try:
        options = {"arg": args}
        if timeout is not None:
            options["timeout"] = timeout
        result = user.page.wait_for_function(OFFLINE_RECORD_WAIT, **options)
    except PlaywrightTimeoutError as error:
        all_rows = user.page.evaluate(OFFLINE_RECORDS, arg=store_name)
        read_failed = not isinstance(all_rows, list)
        all_rows = all_rows if isinstance(all_rows, list) else []
        rows = (
            all_rows
            if record_value is None
            else [
                row
                for row in all_rows
                if isinstance(row, dict) and row.get(record_key) == record_value
            ]
        )
        expected = _record_wait_description(
            minimum=minimum,
            exact=exact,
            saved_html_contains=saved_html_contains,
            record_key=record_key,
            record_value=record_value,
        )
        observed = (
            "the IndexedDB read failed"
            if read_failed
            else f"found {len(rows)} matching record(s) out of "
            f"{len(all_rows)} total: {rows!r}"
        )
        raise AssertionError(
            f"Expected offline {store_name} store to contain {expected}; "
            f"{observed}."
        ) from error

    try:
        return result.json_value()
    finally:
        result.dispose()


def wait_for_offline_mutations(
    user, *, minimum=None, exact=None, record_id=None, timeout=None
):
    """Wait for the durable mutation queue, not a timing or network proxy."""
    return _wait_for_offline_records(
        user,
        "mutations",
        minimum=minimum,
        exact=exact,
        record_key="id",
        record_value=record_id,
        timeout=timeout,
    )


def wait_for_offline_sync_records(
    user,
    *,
    minimum=None,
    exact=None,
    saved_html_contains=(),
    sync_id=None,
    timeout=None,
):
    """Wait for queued collaborative sync records in the browser."""
    return _wait_for_offline_records(
        user,
        "sync",
        minimum=minimum,
        exact=exact,
        saved_html_contains=saved_html_contains,
        record_key="sync_id",
        record_value=sync_id,
        timeout=timeout,
    )


def wait_for_connectivity_replay(user):
    """Await the latest background connectivity and replay cycles explicitly."""
    return user.page.evaluate(
        """
        async () => {
          await window.__CONNECTIVITY_READY__;
          const view = document.querySelector("[lp-view]")?._lp_view;
          if (view?.replayReady) await view.replayReady;
        }
        """
    )
