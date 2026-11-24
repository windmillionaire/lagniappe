import { captureError } from "../../shared/errors.ts";
import {
	QueryLifecycle,
	type QueryToken,
} from "../../shared/queryLifecycle.ts";
import { debounce } from "../../shared/utilities.ts";
import { Combobox } from "./combobox.ts";

export type RemoteInputEvent = { target: { value: string } };

export type ComboboxQueryResponse = { results: string };

function hasInputValue(event: Event): event is Event & RemoteInputEvent {
	const { target } = event;
	return (
		target != null && "value" in target && typeof target.value === "string"
	);
}

type RemoteQueryOptions = {
	getCurrentKey?: () => string;
	cancelTransport?: boolean;
};

/**
 * Shared input, cancellation, publication, and teardown lifecycle for remote
 * comboboxes. Subclasses implement _input() and their result rendering only.
 *
 */
export abstract class RemoteQueryCombobox extends Combobox {
	// Button-backed facets install their input before calling init().
	declare element: HTMLInputElement;
	declare queries: QueryLifecycle;
	declare _queryPending: boolean;
	declare _debouncedInput: ReturnType<
		typeof debounce<RemoteQueryCombobox, [RemoteInputEvent]>
	>;

	constructor(element: HTMLElement, { queryWait = 200 } = {}) {
		super(element);
		this.queries = new QueryLifecycle();
		this._queryPending = false;
		this._queryInput = this._queryInput.bind(this);
		this._debouncedInput = debounce((event) => {
			const result = this._input(event);
			if (result?.catch) {
				result.catch((error: unknown) => captureError(error, this.element));
			}
		}, queryWait);
	}

	init() {
		if (this._destroyed) return;
		this.element.addEventListener("input", this._queryInput);
		super.init();
		this.element.setAttribute("aria-busy", "false");
	}

	abstract _input(event: RemoteInputEvent): Promise<unknown> | undefined;

	_queryInput(event: Event) {
		if (this._destroyed || !hasInputValue(event)) return;
		const inputValue = event.target.value;
		this.queries.invalidate();
		this._queryPending = true;
		this.element.setAttribute("aria-busy", "true");
		super.hidePanel();
		if (event.target === this.element) {
			this.element.value = inputValue;
		}
		this._debouncedInput(event);
	}

	invalidateQuery() {
		this.queries.invalidate();
		this._queryPending = false;
		this.element.setAttribute("aria-busy", "false");
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

	runQuery<Result>(
		key: string,
		loader: (token: QueryToken<string>) => Result | PromiseLike<Result>,
		publisher: (result: Result, token: QueryToken<string>) => unknown,
		{
			getCurrentKey = () => this.element.value.trim(),
			cancelTransport = true,
		}: RemoteQueryOptions = {},
	): Promise<boolean> {
		if (this._destroyed) return Promise.resolve(false);
		this._queryPending = true;
		this.element.setAttribute("aria-busy", "true");
		let activeToken: QueryToken<string> | null = null;
		return this.queries
			.run(
				key,
				(token) => {
					activeToken = token;
					return loader(token);
				},
				(result, token) => {
					this._queryPending = false;
					this.element.setAttribute("aria-busy", "false");
					return publisher(result, token);
				},
				{ getCurrentKey, cancelTransport },
			)
			.catch((error: unknown) => {
				if (this.queries.isCurrent(activeToken, getCurrentKey())) {
					this._queryPending = false;
					this.element.setAttribute("aria-busy", "false");
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
		this.element.removeAttribute("aria-busy");
	}
}
