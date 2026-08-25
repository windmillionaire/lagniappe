/*! Third-party licenses: /third-party-licenses.txt */
import { d as debounce, c as captureError } from './foundation.js?v=bdc368f0';
import './connectivity.js?v=bdc368f0';
import { Q as QueryLifecycle } from './queryLifecycle.js?v=bdc368f0';
import { C as Combobox } from './combobox.js?v=bdc368f0';

/**
 * Shared input, cancellation, publication, and teardown lifecycle for remote
 * comboboxes. Subclasses implement _input() and their result rendering only.
 *
 * @testable true
 * @tests tests_js/test_046_async_query_lifecycle.py::test_remote_combobox_invalidates_before_debounce_and_on_destroy
 * @features async-query combobox
 * @dimensions debounce stale-publication dismissal teardown
 */
class RemoteQueryCombobox extends Combobox {
	constructor(element, { queryWait = 200 } = {}) {
		super(element);
		this.queries = new QueryLifecycle();
		this._queryPending = false;
		this._queryInput = this._queryInput.bind(this);
		this._debouncedInput = debounce((event) => {
			const result = this._input(event);
			if (result?.catch) {
				result.catch((error) => captureError(error, this.element));
			}
		}, queryWait);
	}

	init() {
		if (this._destroyed) return;
		this.element.addEventListener("input", this._queryInput);
		super.init();
	}

	_queryInput(event) {
		if (this._destroyed) return;
		const inputValue = event.target?.value;
		this.queries.invalidate();
		this._queryPending = true;
		super.hidePanel();
		if (event.target === this.element && typeof inputValue === "string") {
			this.element.value = inputValue;
		}
		this._debouncedInput(event);
	}

	invalidateQuery() {
		this.queries.invalidate();
		this._queryPending = false;
	}

	settleQueryInput({ clear = false } = {}) {
		this.invalidateQuery();
		if (clear) this.clearQueryResults();
	}

	clearQueryResults() {
		this.options = [];
		this.focusedIndex = -1;
		this.element.removeAttribute("aria-activedescendant");
		this.panel?.replaceChildren();
		super.hidePanel();
	}

	runQuery(
		key,
		loader,
		publisher,
		{
			getCurrentKey = () => this.element.value.trim(),
			cancelTransport = true,
		} = {},
	) {
		if (this._destroyed) return Promise.resolve(false);
		this._queryPending = true;
		let activeToken = null;
		return this.queries
			.run(
				key,
				(token) => {
					activeToken = token;
					return loader(token);
				},
				(result, token) => {
					this._queryPending = false;
					return publisher(result, token);
				},
				{ getCurrentKey, cancelTransport },
			)
			.catch((error) => {
				if (this.queries.isCurrent(activeToken, getCurrentKey())) {
					this._queryPending = false;
				}
				throw error;
			});
	}

	showPanel() {
		if (this._queryPending) return Promise.resolve(false);
		return super.showPanel();
	}

	hidePanel() {
		this.invalidateQuery();
		return super.hidePanel();
	}

	destroy() {
		if (this._destroyed) return;
		this._debouncedInput.cancel();
		this.queries.destroy();
		this._queryPending = false;
		this.element.removeEventListener("input", this._queryInput);
		super.destroy();
	}
}

export { RemoteQueryCombobox as R };
