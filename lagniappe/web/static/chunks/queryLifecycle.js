/*! Third-party licenses: /third-party-licenses.txt */
/**
 * Coordinate an asynchronous read with the UI state that requested it.
 * Epoch checks remain authoritative even when AbortController is unavailable
 * or a transport cannot be cancelled.
 *
 * @testable true
 * @tests tests_js/test_046_async_query_lifecycle.py::test_query_lifecycle_publishes_only_the_current_request
 * @tests tests_js/test_046_async_query_lifecycle.py::test_query_lifecycle_invalidates_repeated_keys_and_destroyed_owners
 * @tests tests_js/test_046_async_query_lifecycle.py::test_query_lifecycle_propagates_current_loader_errors
 * @features async-query
 * @dimensions ordering repeated-key cancellation teardown error-propagation
 */
class QueryLifecycle {
	constructor() {
		this.epoch = 0;
		this.controller = null;
		this.destroyed = false;
	}

	begin(key, { cancelTransport = true } = {}) {
		if (this.destroyed) return null;

		this.invalidate();
		if (this.destroyed) return null;

		if (cancelTransport && typeof AbortController !== "undefined") {
			this.controller = new AbortController();
		}
		return {
			epoch: this.epoch,
			key,
			signal: this.controller?.signal,
		};
	}

	isCurrent(token, currentKey = token?.key) {
		return Boolean(
			token &&
				!this.destroyed &&
				token.epoch === this.epoch &&
				token.key === currentKey,
		);
	}

	invalidate() {
		this.epoch += 1;
		this.controller?.abort();
		this.controller = null;
	}

	destroy() {
		if (this.destroyed) return;
		this.destroyed = true;
		this.invalidate();
	}

	async run(
		key,
		loader,
		publisher,
		{ getCurrentKey = () => key, cancelTransport = true } = {},
	) {
		const token = this.begin(key, { cancelTransport });
		if (!token) return false;

		try {
			const result = await loader(token);
			if (!this.isCurrent(token, getCurrentKey())) return false;
			await publisher(result, token);
			return this.isCurrent(token, getCurrentKey());
		} catch (error) {
			if (
				error?.name === "AbortError" &&
				!this.isCurrent(token, getCurrentKey())
			) {
				return false;
			}
			throw error;
		}
	}
}

export { QueryLifecycle as Q };
