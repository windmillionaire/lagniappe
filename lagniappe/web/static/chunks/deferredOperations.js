/*! Third-party licenses: /third-party-licenses.txt */
import { c as createIcon } from './icons.js?v=b26991f5';
import './styles.js?v=b26991f5';

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
 * Reconcile every visible deferred operation through the shared poll contract.
 *
 * @testable true
 * @tests tests_js/test_023_deferred_operations.py::test_deferred_operation_manager_batches_orders_and_renders_status
 * @features deferred-jobs
 * @dimensions status revision polling progress timing backoff teardown decoration-opt-out
 */
class DeferredOperationManager {
	constructor(view) {
		this.view = view;
		this.operations = new Map();
		this.destroyed = false;
		this.ignored = new Set();
		this.unsubscribers = new Map();
	}

	init() {
		this.scan();
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
			this.unsubscribers.get(previous)?.();
			this.unsubscribers.delete(previous);
			this._ignore(previous);
		}
		if (decorationNode) this.decorate(decorationNode, key);
		const current = this.operations.get(key);
		this.operations.set(key, {
			...current,
			revision: Math.max(Number(current?.revision) || 0, Number(revision) || 0),
		});
		if (!this.unsubscribers.has(key)) {
			const unsubscribe = this.view.PollingCoordinator?.subscribe(
				{
					id: `operation:${key}`,
					type: "operation",
					key,
					revision: null,
					operation_revision: null,
				},
				{
					onResult: async (result) => {
						if (result.status === "changed" && result.payload) {
							return await this.receive(result.payload);
						} else if (
							result.status === "error" ||
							result.status === "unavailable"
						) {
							this._renderStatusDelay([key]);
						} else {
							this._refreshCachedStatuses([key]);
						}
					},
				},
			);
			if (unsubscribe) this.unsubscribers.set(key, unsubscribe);
		}
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
		this.view.PollingCoordinator?.trigger(key ? `operation:${key}` : null);
		return true;
	}

	async poll() {
		return this.view.PollingCoordinator?.trigger(
			Array.from(this.operations.keys(), (key) => `operation:${key}`),
		);
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
				this.view.EditWatcher?.expectDeferredCompletion?.(
					status.entity_key,
					status.key,
				);
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
				this.unsubscribers.get(status.key)?.();
				this.unsubscribers.delete(status.key);
				this._ignore(status.key);
			} else {
				this._renderStatusDelay([status.key]);
			}
			return reconciled;
		}
		return true;
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
		for (const unsubscribe of this.unsubscribers.values()) unsubscribe();
		this.unsubscribers.clear();
		this.operations.clear();
		this.ignored.clear();
	}
}

export { DeferredOperationManager };
