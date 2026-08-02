from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


OFFLINE_RECORDS = """
async (storeName) => await new Promise((resolve) => {
        const request = indexedDB.open("offline-db", 5);
        request.onerror = () => resolve([]);
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
            recordsRequest.onerror = () => resolve([]);
            transaction.oncomplete = () => db.close();
            transaction.onerror = () => {
                db.close();
                resolve([]);
            };
        };
})
"""

OFFLINE_RECORD_WAIT = f"""
async ({{ storeName, minimum, exact, savedHtmlContains }}) => {{
    const readRecords = {OFFLINE_RECORDS};
    const rows = await readRecords(storeName);
    const countMatches = exact === null
        ? minimum === null || rows.length >= minimum
        : rows.length === exact;
    const contentMatches = savedHtmlContains.length === 0 || rows.some((row) =>
        row?.save === true &&
        typeof row?.html === "string" &&
        savedHtmlContains.every((part) => row.html.includes(part))
    );
    return countMatches && contentMatches ? rows : false;
}}
"""


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


def _record_wait_description(*, minimum, exact, saved_html_contains):
    conditions = []
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
    }
    try:
        result = user.page.wait_for_function(OFFLINE_RECORD_WAIT, arg=args)
    except PlaywrightTimeoutError as error:
        rows = user.page.evaluate(OFFLINE_RECORDS, arg=store_name)
        expected = _record_wait_description(
            minimum=minimum,
            exact=exact,
            saved_html_contains=saved_html_contains,
        )
        raise AssertionError(
            f"Expected offline {store_name} store to contain {expected}; "
            f"found {len(rows)} record(s): {rows!r}."
        ) from error

    try:
        return result.json_value()
    finally:
        result.dispose()


def wait_for_offline_mutations(user, *, minimum=None, exact=None):
    """Wait for the durable mutation queue, not a timing or network proxy."""
    return _wait_for_offline_records(
        user,
        "mutations",
        minimum=minimum,
        exact=exact,
    )


def wait_for_offline_sync_records(
    user,
    *,
    minimum=None,
    exact=None,
    saved_html_contains=(),
):
    """Wait for queued collaborative sync records in the browser."""
    return _wait_for_offline_records(
        user,
        "sync",
        minimum=minimum,
        exact=exact,
        saved_html_contains=saved_html_contains,
    )
