/*! Third-party licenses: /third-party-licenses.txt */
import { E as ENDPOINTS } from './endpoints.js?v=b7488009';
import { captureError } from './errors.js?v=b7488009';
import { r as request } from './request.js?v=b7488009';

const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const CLIENT_ID_KEY = "lagniappe-poll-client";
const ORDINARY_INTERVALS = [15_000, 15_000, 30_000, 30_000, 60_000];
const TYPE_INTERVALS = Object.freeze({
	document: 2_000,
	ingress: 2_500,
	operation: 4_000,
});

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason page-scoped client identity creation is exercised through coordinator requests
 */
function clientId() {
	let value = null;
	try {
		value = sessionStorage.getItem(CLIENT_ID_KEY);
	} catch {
		// Storage can be unavailable in hardened/private browser contexts.
	}
	if (!value) {
		value =
			globalThis.crypto?.randomUUID?.() ||
			`poll-${Date.now()}-${Math.random().toString(16).slice(2)}`;
		try {
			sessionStorage.setItem(CLIENT_ID_KEY, value);
		} catch {
			// The in-memory identity remains valid for this page lifetime.
		}
	}
	return value;
}

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason bounded scheduling jitter is exercised through coordinator cadence
 */
function jitter(delay, factor = 0.9 + Math.random() * 0.2) {
	return Math.max(Math.round(delay * factor), 250);
}

/**
 * One view-scoped scheduler for every server-state subscription.
 *
 * @testable true
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_batches_due_subscriptions_and_applies_results
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_enqueues_reentrant_followup_without_waiting
 * @features polling
 * @dimensions batching cadence lifecycle coalescing acknowledgement reentrancy requested-cycle
 */
class PollingCoordinator {
	constructor(view) {
		this.view = view;
		this.clientId = clientId();
		this.subscriptions = new Map();
		this.timer = null;
		this.activePoll = null;
		this.activeIds = new Set();
		this.inflight = null;
		this.followup = false;
		this.queuedIds = new Set();
		this.destroyed = false;
	}

	init() {
		return this;
	}

	subscribe(descriptor, { onResult = null, beforePoll = null } = {}) {
		if (this.destroyed || !descriptor?.id || !descriptor?.type) return () => {};
		const existing = this.subscriptions.get(descriptor.id);
		const now = Date.now();
		this.subscriptions.set(descriptor.id, {
			...existing,
			descriptor: { ...existing?.descriptor, ...descriptor },
			onResult: onResult ?? existing?.onResult ?? null,
			beforePoll: beforePoll ?? existing?.beforePoll ?? null,
			dueAt: Math.min(existing?.dueAt ?? now, now),
			quiet: existing?.quiet ?? 0,
			errorCount: existing?.errorCount ?? 0,
		});
		this.pause();
		this._schedule(0);
		return () => this.unsubscribe(descriptor.id);
	}

	unsubscribe(id) {
		this.subscriptions.delete(id);
		this.queuedIds.delete(id);
		if (!this.subscriptions.size) this.pause();
		else this._schedule();
	}

	get(id) {
		return this.subscriptions.get(id)?.descriptor ?? null;
	}

	update(id, patch = {}) {
		const subscription = this.subscriptions.get(id);
		if (!subscription) return;
		Object.assign(subscription.descriptor, patch);
	}

	acknowledge(id, revision) {
		const subscription = this.subscriptions.get(id);
		if (!subscription || revision === undefined || revision === null) return;
		subscription.descriptor.revision = revision;
		subscription.quiet = 0;
	}

	/**
	 * Mark subscriptions for an immediate cycle without exposing a promise that
	 * a callback in the active cycle could accidentally await.
	 */
	enqueue(ids = null) {
		const requested =
			ids === null
				? new Set(this.subscriptions.keys())
				: new Set(Array.isArray(ids) ? ids : [ids]);
		const now = Date.now();
		for (const [id, subscription] of this.subscriptions) {
			if (!requested.has(id)) continue;
			subscription.dueAt = now;
			if (this.activePoll) this.queuedIds.add(id);
		}
		if (this.activePoll) {
			this.followup = true;
			return;
		}
		this._schedule(0);
	}

	trigger(ids = null) {
		const requested =
			ids === null
				? new Set(this.subscriptions.keys())
				: new Set(Array.isArray(ids) ? ids : [ids]);
		if (
			this.activePoll &&
			Array.from(requested).every((id) => this.activeIds.has(id))
		) {
			return this.activePoll;
		}
		this.enqueue(ids);
		if (this.activePoll) {
			const current = this.activePoll;
			const followup = () =>
				Promise.resolve().then(() => this.activePoll ?? this._poll());
			return current.then(followup, followup);
		}
		return this._poll();
	}

	pause() {
		if (this.timer) window.clearTimeout(this.timer);
		this.timer = null;
	}

	resume() {
		if (this.destroyed) return Promise.resolve([]);
		return this.trigger();
	}

	async closeDocuments(syncIds) {
		const closed = Array.from(new Set(syncIds || [])).filter(Boolean);
		if (!closed.length || !this.view.online) return;
		if (this.activePoll) await this.activePoll;
		return request.post(
			ENDPOINTS.poll,
			{
				version: 1,
				client_id: this.clientId,
				subscriptions: [],
				closed_documents: closed,
			},
			{ keepalive: true },
		);
	}

	_interval(subscription, result) {
		if (result?.status === "error") {
			subscription.errorCount += 1;
			return Math.min(2 ** subscription.errorCount * 2_000, 60_000);
		}
		subscription.errorCount = 0;
		if (result?.status === "changed") subscription.quiet = 0;
		else subscription.quiet += 1;

		if (subscription.descriptor.type === "operation") {
			const steps = [4_000, 8_000, 16_000, 30_000];
			return steps[Math.min(subscription.quiet, steps.length - 1)];
		}
		if (TYPE_INTERVALS[subscription.descriptor.type]) {
			return (
				Number(result?.poll_after_ms) ||
				TYPE_INTERVALS[subscription.descriptor.type]
			);
		}
		return ORDINARY_INTERVALS[
			Math.min(subscription.quiet, ORDINARY_INTERVALS.length - 1)
		];
	}

	_applyProtocolState(subscription, result) {
		if (result.revision !== undefined) {
			subscription.descriptor.revision = result.revision;
		}
		if (result.operation_revision !== undefined) {
			subscription.descriptor.operation_revision = result.operation_revision;
		}
		if (subscription.descriptor.type === "document" && result.payload) {
			if (result.payload.generation) {
				subscription.descriptor.generation = result.payload.generation;
			}
			if (result.payload.presence_digest) {
				subscription.descriptor.presence_digest =
					result.payload.presence_digest;
			}
		}
	}

	_due() {
		const now = Date.now();
		return Array.from(this.subscriptions.values())
			.filter((subscription) => subscription.dueAt <= now)
			.slice(0, MAX_SUBSCRIPTIONS_PER_REQUEST);
	}

	_poll() {
		if (this.destroyed || this.view.hidden || !this.view.online) {
			return Promise.resolve([]);
		}
		if (this.activePoll) {
			this.followup = true;
			return this.activePoll;
		}

		const cycle = this._runPoll();
		this.activePoll = cycle;
		const complete = () => {
			if (this.activePoll !== cycle) return;
			this.activePoll = null;
			this.activeIds.clear();
			const followup = this.followup;
			this.followup = false;
			if (followup) {
				queueMicrotask(() => this._poll());
			} else {
				this._schedule();
			}
		};
		void cycle.then(complete, complete);
		return cycle;
	}

	async _runPoll() {
		let due = [];
		let results = [];
		try {
			due = this._due();
			if (!due.length) return [];
			this.activeIds = new Set(due.map(({ descriptor }) => descriptor.id));
			for (const { descriptor } of due) {
				this.queuedIds.delete(descriptor.id);
			}
			const hooks = new Set(
				due.map(({ beforePoll }) => beforePoll).filter(Boolean),
			);
			for (const hook of hooks) await hook();
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			due = due.filter(
				(subscription) =>
					this.subscriptions.get(subscription.descriptor.id) === subscription,
			);
			if (!due.length) return [];

			this.pause();
			const byId = new Map(
				due.map((subscription) => [subscription.descriptor.id, subscription]),
			);
			this.inflight = request.post(ENDPOINTS.poll, {
				version: 1,
				client_id: this.clientId,
				subscriptions: due.map(({ descriptor }) => ({ ...descriptor })),
				closed_documents: [],
			});
			const response = await this.inflight;
			if (!response?.ok) {
				const cycleJitter = 0.9 + Math.random() * 0.2;
				const scheduledAt = Date.now();
				for (const subscription of due) {
					subscription.dueAt =
						scheduledAt +
						jitter(
							this._interval(subscription, { status: "error" }),
							cycleJitter,
						);
					await subscription.onResult?.({
						id: subscription.descriptor.id,
						type: subscription.descriptor.type,
						status: "error",
					});
				}
				return [];
			}
			if (
				response.version !== 1 ||
				!Array.isArray(response.results)
			) {
				throw new Error("Invalid polling response");
			}
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			results = response.results;
			const received = new Set();
			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const result of results) {
				const subscription = byId.get(result?.id);
				if (!subscription || this.subscriptions.get(result.id) !== subscription)
					continue;
				received.add(result.id);
				const previousDescriptor = { ...subscription.descriptor };
				try {
					this._applyProtocolState(subscription, result);
					const accepted = await subscription.onResult?.(result);
					if (accepted === false) {
						subscription.descriptor = previousDescriptor;
					}
					subscription.dueAt =
						scheduledAt +
						jitter(this._interval(subscription, result), cycleJitter);
				} catch (error) {
					subscription.descriptor = previousDescriptor;
					captureError(error, this.view.elt, {
						context: "polling-subscription",
						subscription_id: result.id,
					});
					subscription.dueAt =
						scheduledAt +
						jitter(
							this._interval(subscription, {
								status: "error",
							}),
							cycleJitter,
						);
				}
			}
			for (const [id, subscription] of byId) {
				if (received.has(id)) continue;
				const missing = {
					id,
					status: "error",
					type: subscription.descriptor.type,
				};
				subscription.dueAt =
					scheduledAt +
					jitter(this._interval(subscription, missing), cycleJitter);
			}
		} catch (error) {
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			captureError(error, this.view.elt, { context: "polling-coordinator" });
			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const subscription of due) {
				subscription.dueAt =
					scheduledAt +
					jitter(
						this._interval(subscription, {
							status: "error",
						}),
						cycleJitter,
					);
				await subscription.onResult?.({
					id: subscription.descriptor.id,
					type: subscription.descriptor.type,
					status: "error",
				});
			}
		} finally {
			this.inflight = null;
			const now = Date.now();
			for (const id of this.queuedIds) {
				const subscription = this.subscriptions.get(id);
				if (subscription) subscription.dueAt = now;
			}
		}
		return results;
	}

	_schedule(delay = null) {
		if (
			this.destroyed ||
			this.timer ||
			!this.subscriptions.size ||
			this.view.hidden ||
			!this.view.online
		)
			return;
		const nextDue = Math.min(
			...Array.from(this.subscriptions.values(), ({ dueAt }) => dueAt),
		);
		const wait = delay ?? Math.max(nextDue - Date.now(), 0);
		this.timer = window.setTimeout(() => {
			this.timer = null;
			void this._poll();
		}, wait);
	}

	destroy() {
		this.destroyed = true;
		this.pause();
		this.subscriptions.clear();
		this.activeIds.clear();
		this.queuedIds.clear();
	}
}

export { PollingCoordinator };
