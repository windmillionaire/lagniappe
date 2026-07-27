import { ENDPOINTS } from "./endpoints";
import { createIcon } from "./icons";
import { request } from "./request";

const POLL_INTERVAL_MS = 4000;
const MAX_POLL_INTERVAL_MS = 30000;
const MAX_OPERATIONS_PER_REQUEST = 50;

/**
 * @testable false
 * @covered-by src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @reason coordinator-owned polling schedule helper
 */
function jitter(delay) {
	return Math.round(delay * (0.85 + Math.random() * 0.3));
}

/**
 * @testable false
 * @covered-by src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @reason coordinator-owned bounded elapsed-time presentation
 */
function elapsedLabel(seconds) {
	seconds = Math.max(Number(seconds) || 0, 0);
	if (seconds < 10) return "just now";
	if (seconds < 60) return `${Math.floor(seconds)} seconds`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes} min`;
	const hours = Math.floor(minutes / 60);
	return `${hours} hr ${minutes % 60} min`;
}

/**
 * @testable false
 * @covered-by src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @reason coordinator-owned DOM lookup for operation decorations
 */
function operationNodes(key) {
	return Array.from(document.querySelectorAll("[data-operation]")).filter(
		(node) => node.dataset.operation === key,
	);
}

/**
 * Reconcile every visible deferred operation through one owner-safe request.
 * Push messages only accelerate this loop; correctness does not depend on FCM.
 *
 * @testable true
 * @tests tests_js/test_023_deferred_operations.py::test_deferred_operation_manager_batches_orders_and_renders_status
 * @features deferred-jobs
 * @dimensions status batch request-limit revision polling progress timing push-acceleration etag backoff teardown decoration-opt-out
 */
export class DeferredOperationManager {
	constructor(view) {
		this.view = view;
		this.operations = new Map();
		this.timer = null;
		this.inflight = null;
		this.destroyed = false;
		this.etags = new Map();
		this.pollInterval = POLL_INTERVAL_MS;
		this.ignored = new Set();
	}

	init() {
		this.scan();
		this.schedule(0);
		return this;
	}

	scan(root = document) {
		const nodes = Array.from(root.querySelectorAll?.("[data-operation]") || []);
		if (root.matches?.("[data-operation]")) nodes.unshift(root);
		for (const node of nodes) {
			this.track(node.dataset.operation, {
				revision: Number(node.dataset.operationRevision) || 0,
				node,
			});
		}
	}

	track(key, { revision = 0, node = null } = {}) {
		if (this.destroyed || !key || this.ignored.has(key)) return false;
		const decorationNode =
			node?.dataset?.deferredStatus === "false" ? null : node;
		const previous = decorationNode?.dataset?.operation;
		if (previous && previous !== key) {
			this.operations.delete(previous);
			this._ignore(previous);
		}
		if (decorationNode) this.decorate(decorationNode, key);
		const current = this.operations.get(key);
		this.operations.set(key, {
			...current,
			revision: Math.max(Number(current?.revision) || 0, Number(revision) || 0),
		});
		this.etags.clear();
		this.pollInterval = POLL_INTERVAL_MS;
		this.schedule(0);
		return true;
	}

	decorate(node, key) {
		if (!node || !key) return;
		node.dataset.operation = key;
		const formLocked = node.dataset.deferredLock === "form";
		if (formLocked) {
			node.setAttribute("aria-busy", "true");
			for (const control of node.querySelectorAll(
				"input, textarea, select, button",
			)) {
				control.disabled = true;
			}
		}
		if (node.querySelector("[data-role='deferred-phase']")) return;
		const autofill = node.querySelector("[data-role='autofill']");
		const submitGroup = node.querySelector("[data-role='submit-group']");
		const autofillSubmitGroup = node.querySelector(
			"[data-role='autofill-submit-group']",
		);
		const autofillTarget = (autofill && submitGroup) || autofillSubmitGroup;
		const progress = document.createElement("p");
		progress.dataset.role = "deferred-progress";
		progress.dataset.operation = key;
		progress.className = autofillTarget
			? "flex min-h-10 items-center justify-center gap-2 rounded-md bg-kind-default px-4 py-2 text-sm font-semibold text-white shadow-sm"
			: "mt-2 text-sm text-base-medium";
		progress.setAttribute("aria-live", "polite");
		const icon = createIcon("spinner");
		icon.setAttribute("aria-hidden", "true");
		const phase = document.createElement("span");
		phase.dataset.role = "deferred-phase";
		phase.textContent = autofillTarget ? "Autofill queued" : "Waiting to start";
		const separator = document.createElement("span");
		separator.setAttribute("aria-hidden", "true");
		separator.textContent = " · ";
		const elapsed = document.createElement("span");
		elapsed.dataset.role = "deferred-elapsed";
		elapsed.textContent = "just now";
		if (autofillTarget) {
			progress.append(icon, phase, separator, elapsed);
			autofillTarget.replaceWith(progress);
			if (autofill && autofill !== autofillTarget) autofill.remove();
		} else {
			progress.append(phase, separator, elapsed);
			node.append(progress);
		}
	}

	nudge(key, revision = null) {
		const current = key ? this.operations.get(key) : null;
		if (
			current &&
			revision !== null &&
			revision !== undefined &&
			Number(revision) < (Number(current.revision) || 0)
		)
			return false;
		if (key && !this.track(key, { revision })) return false;
		this.etags.clear();
		this.pollInterval = POLL_INTERVAL_MS;
		this.schedule(0);
		return true;
	}

	schedule(delay = this.pollInterval) {
		if (this.destroyed || this.timer || !this.operations.size) return;
		this.timer = window.setTimeout(
			() => {
				this.timer = null;
				this.poll();
			},
			delay ? jitter(delay) : 0,
		);
	}

	async poll() {
		if (this.destroyed || this.inflight || !this.operations.size) return;
		if (document.hidden || !this.view.online) {
			this.schedule();
			return;
		}

		const batches = [];
		const keys = Array.from(this.operations.keys());
		for (
			let index = 0;
			index < keys.length;
			index += MAX_OPERATIONS_PER_REQUEST
		) {
			batches.push(keys.slice(index, index + MAX_OPERATIONS_PER_REQUEST));
		}
		this.inflight = Promise.all(
			batches.map((batch) => {
				const signature = batch.join("\n");
				const etag = this.etags.get(signature);
				return request
					.post(
						ENDPOINTS.deferredOperations,
						{ operations: batch },
						{
							headers: etag ? { "If-None-Match": etag } : {},
						},
					)
					.then((response) => ({ batch, signature, response }));
			}),
		);
		try {
			let changed = false;
			let delayed = false;
			const responses = await this.inflight;
			if (this.destroyed) return;
			for (const { batch, signature, response } of responses) {
				if (!response?.ok) {
					this._renderStatusDelay(batch);
					delayed = true;
					continue;
				}
				if (response.etag) this.etags.set(signature, response.etag);
				if (response.unchanged) {
					this._refreshCachedStatuses(batch);
					continue;
				}
				if (!Array.isArray(response.operations)) {
					this._renderStatusDelay(batch);
					delayed = true;
					continue;
				}
				const received = new Set();
				for (const status of response.operations) {
					received.add(status?.key);
					changed = (await this.receive(status)) || changed;
				}
				const missing = batch.filter((key) => !received.has(key));
				if (missing.length) this._renderStatusDelay(missing);
			}
			this.pollInterval = delayed
				? Math.min(this.pollInterval * 2, MAX_POLL_INTERVAL_MS)
				: changed
					? POLL_INTERVAL_MS
					: Math.min(Math.round(this.pollInterval * 1.5), MAX_POLL_INTERVAL_MS);
		} catch {
			this._renderStatusDelay();
			this.pollInterval = Math.min(this.pollInterval * 2, MAX_POLL_INTERVAL_MS);
		} finally {
			this.inflight = null;
			this.schedule();
		}
	}

	async receive(status) {
		if (this.destroyed || !status?.key || !this.operations.has(status.key))
			return false;
		const current = this.operations.get(status.key);
		const revision = Number(status.revision) || 0;
		const previousRevision = Number(current?.revision) || 0;
		if (revision < previousRevision) return false;
		this.operations.set(status.key, {
			revision,
			status: { ...status },
			receivedAt: Date.now(),
		});
		this._render(status);

		window.dispatchEvent(
			new CustomEvent("deferred-operation", { detail: { ...status } }),
		);
		if (status.terminal) {
			let reconciled = true;
			try {
				await this.view.reconcileChange?.({
					type: "deferred-complete",
					key: status.entity_key,
					source_widget: status.source_widget,
					destination: status.destination,
					deferred_revision: `${status.key}:${revision}`,
				});
			} catch {
				reconciled = false;
			}
			if (reconciled) {
				this.operations.delete(status.key);
				this._ignore(status.key);
				this.etags.clear();
			} else {
				this.etags.clear();
				this._renderStatusDelay([status.key]);
			}
			return reconciled;
		}
		return revision > previousRevision || Boolean(status.terminal);
	}

	_render(status, elapsedSeconds = status.elapsed_seconds) {
		for (const node of operationNodes(status.key)) {
			node.dataset.operationRevision = String(Number(status.revision) || 0);
			node.dataset.operationStatus = status.status || "unknown";
			node.dataset.operationPhase = status.phase || "unknown";
			node.dataset.operationTerminal = status.terminal ? "true" : "false";
			const phase = node.querySelector("[data-role='deferred-phase']");
			if (phase) {
				phase.textContent = status.error
					? `${status.phase_label}: ${status.error}`
					: status.recovering
						? `${status.phase_label}. Automatic recovery is active.`
						: status.phase_label;
			}
			const elapsed = node.querySelector("[data-role='deferred-elapsed']");
			if (elapsed) elapsed.textContent = elapsedLabel(elapsedSeconds);
		}
	}

	_refreshCachedStatuses(keys = Array.from(this.operations.keys())) {
		for (const key of keys) {
			const operation = this.operations.get(key);
			if (!operation?.status) continue;
			const elapsed =
				(Number(operation.status.elapsed_seconds) || 0) +
				Math.max(Math.floor((Date.now() - operation.receivedAt) / 1000), 0);
			this._render(operation.status, elapsed);
		}
	}

	_renderStatusDelay(keys = Array.from(this.operations.keys())) {
		for (const key of keys) {
			for (const node of operationNodes(key)) {
				const phase = node.querySelector("[data-role='deferred-phase']");
				if (phase) phase.textContent = "Status check delayed. Retrying.";
			}
		}
	}

	_ignore(key) {
		if (!key) return;
		this.ignored.add(key);
		if (this.ignored.size > 100) {
			this.ignored.delete(this.ignored.values().next().value);
		}
	}

	destroy() {
		this.destroyed = true;
		window.clearTimeout(this.timer);
		this.timer = null;
		this.operations.clear();
		this.ignored.clear();
		this.etags.clear();
	}
}
