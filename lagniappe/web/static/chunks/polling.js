/*! Third-party licenses: /third-party-licenses.txt */
import { c as captureError, r as request, E as ENDPOINTS } from './foundation.js?v=b13679a7';
import './connectivity.js?v=b13679a7';

const POLL_PROTOCOL_VERSION = 1;
const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const MAX_KEY_LENGTH = 512;
const MAX_IDENTIFIER_LENGTH = MAX_KEY_LENGTH + 128;
const MAX_CLIENT_ID_LENGTH = 128;
const MAX_CURSOR_LENGTH = 512;
const MAX_STATE_TOKEN_LENGTH = 128;
const MAX_REVISION = Number.MAX_SAFE_INTEGER;
const CLIENT_ID_KEY = "lagniappe-poll-client";
const ORDINARY_INTERVALS = [15_000, 15_000, 30_000, 30_000, 60_000];
const TYPE_INTERVALS = Object.freeze({
	document: 2_000,
	ingress: 2_500,
	operation: 4_000,
});
const SUBSCRIPTION_MODES = new Set(["periodic", "foreground"]);
const INITIAL_MODES = new Set(["immediate", "scheduled"]);
const POLL_TYPES = new Set([
	"entity",
	"channel",
	"form-lock",
	"document",
	"operation",
	"ingress",
]);
const POLL_CHANNELS = new Set([
	"categories",
	"projects",
	"pages",
	"tasks",
	"forms",
	"users",
	"ingress",
	"home",
	"home-notes",
	"starred",
	"tool-reports",
]);
const POLL_STATUSES = new Set(["changed", "unchanged", "unavailable", "error"]);

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason safe field diagnostics are exercised through coordinator contract coverage
 */
class PollContractError extends TypeError {
	constructor(path, reason) {
		super(`${path}: ${reason}`);
		this.name = "PollContractError";
		this.path = path;
		this.reason = reason;
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason exact object shape checks are exercised through coordinator contract coverage
 */
const exactFields = (value, path, required, optional = []) => {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		throw new PollContractError(path, "type");
	}
	const allowed = new Set([...required, ...optional]);
	for (const name of required) {
		if (!Object.hasOwn(value, name)) {
			throw new PollContractError(`${path}.${name}`, "missing");
		}
	}
	for (const name of Object.keys(value)) {
		if (!allowed.has(name)) {
			throw new PollContractError(`${path}.${name}`, "unexpected");
		}
	}
	return value;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason bounded string checks are exercised through coordinator contract coverage
 */
const boundedString = (value, path, maximum, { nullable = false } = {}) => {
	if (nullable && value === null) return null;
	if (typeof value !== "string") throw new PollContractError(path, "type");
	if (!value.trim()) throw new PollContractError(path, "blank");
	if (value.length > maximum) throw new PollContractError(path, "limit");
	return value;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason integer cursor checks are exercised through coordinator contract coverage
 */
const integerRevision = (value, path) => {
	if (!Number.isInteger(value)) throw new PollContractError(path, "type");
	if (value < 0) throw new PollContractError(path, "state");
	if (value > MAX_REVISION) throw new PollContractError(path, "limit");
	return value;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason document identity checks are exercised through coordinator contract coverage
 */
const documentId = (value, path) => {
	value = boundedString(value, path, MAX_KEY_LENGTH);
	if (!value.endsWith(":document")) {
		throw new PollContractError(path, "unsupported");
	}
	return value;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason descriptor normalization is exercised through coordinator requests
 */
const normalizedDescriptor = (raw, path = "descriptor") => {
	exactFields(
		raw,
		path,
		["id", "type", "revision"],
		["key", "channel", "sync_id", "generation", "presence_digest"],
	);
	const id = boundedString(raw.id, `${path}.id`, MAX_IDENTIFIER_LENGTH);
	const type = boundedString(raw.type, `${path}.type`, 32);
	if (!POLL_TYPES.has(type)) {
		throw new PollContractError(`${path}.type`, "unsupported");
	}

	const typedFields =
		type === "channel"
			? ["channel"]
			: type === "document"
				? ["key", "sync_id", "generation", "presence_digest"]
				: ["key"];
	exactFields(raw, path, ["id", "type", "revision", ...typedFields]);
	const revision =
		type === "operation" || type === "document"
			? integerRevision(raw.revision, `${path}.revision`)
			: boundedString(raw.revision, `${path}.revision`, MAX_CURSOR_LENGTH, {
					nullable: type !== "form-lock",
				});
	const descriptor = { id, type, revision };

	if (type === "channel") {
		descriptor.channel = boundedString(raw.channel, `${path}.channel`, 64);
		if (!POLL_CHANNELS.has(descriptor.channel)) {
			throw new PollContractError(`${path}.channel`, "unsupported");
		}
		return descriptor;
	}

	descriptor.key = boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH);
	if (type === "document") {
		descriptor.sync_id = documentId(raw.sync_id, `${path}.sync_id`);
		descriptor.generation = boundedString(
			raw.generation,
			`${path}.generation`,
			MAX_STATE_TOKEN_LENGTH,
			{ nullable: true },
		);
		descriptor.presence_digest = boundedString(
			raw.presence_digest,
			`${path}.presence_digest`,
			MAX_STATE_TOKEN_LENGTH,
			{ nullable: true },
		);
	}
	return descriptor;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason notification request modes are exercised through coordinator requests
 */
const normalizedNotificationState = (raw, path = "notification_state") => {
	exactFields(raw, path, ["generation", "revision", "seed"]);
	if (typeof raw.seed !== "boolean") {
		throw new PollContractError(`${path}.seed`, "type");
	}
	const generation = boundedString(
		raw.generation,
		`${path}.generation`,
		MAX_STATE_TOKEN_LENGTH,
		{ nullable: true },
	);
	const revision =
		raw.revision === null
			? null
			: integerRevision(raw.revision, `${path}.revision`);
	const cold = raw.seed && generation === null && revision === null;
	const warm = !raw.seed && generation !== null && revision !== null;
	if (!cold && !warm) throw new PollContractError(path, "state");
	return { generation, revision, seed: raw.seed };
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason final request normalization is exercised through coordinator requests
 */
const normalizedRequest = (raw) => {
	exactFields(
		raw,
		"request",
		["version", "client_id", "subscriptions", "closed_documents"],
		["notification_state"],
	);
	if (raw.version !== POLL_PROTOCOL_VERSION) {
		throw new PollContractError("request.version", "unsupported");
	}
	const client_id = boundedString(
		raw.client_id,
		"request.client_id",
		MAX_CLIENT_ID_LENGTH,
	);
	if (!Array.isArray(raw.subscriptions)) {
		throw new PollContractError("request.subscriptions", "type");
	}
	if (raw.subscriptions.length > MAX_SUBSCRIPTIONS_PER_REQUEST) {
		throw new PollContractError("request.subscriptions", "limit");
	}
	const identifiers = new Set();
	const subscriptions = raw.subscriptions.map((descriptor, index) => {
		const normalized = normalizedDescriptor(
			descriptor,
			`request.subscriptions[${index}]`,
		);
		if (identifiers.has(normalized.id)) {
			throw new PollContractError(
				`request.subscriptions[${index}].id`,
				"duplicate",
			);
		}
		identifiers.add(normalized.id);
		return normalized;
	});
	if (!Array.isArray(raw.closed_documents)) {
		throw new PollContractError("request.closed_documents", "type");
	}
	if (raw.closed_documents.length > MAX_SUBSCRIPTIONS_PER_REQUEST) {
		throw new PollContractError("request.closed_documents", "limit");
	}
	const closedIds = new Set();
	const closed_documents = raw.closed_documents.map((syncId, index) => {
		const path = `request.closed_documents[${index}]`;
		const normalized = documentId(syncId, path);
		if (closedIds.has(normalized)) {
			throw new PollContractError(path, "duplicate");
		}
		closedIds.add(normalized);
		return normalized;
	});
	const requestBody = {
		version: POLL_PROTOCOL_VERSION,
		client_id,
		subscriptions,
		closed_documents,
	};
	if (Object.hasOwn(raw, "notification_state")) {
		requestBody.notification_state = normalizedNotificationState(
			raw.notification_state,
			"request.notification_state",
		);
	}
	return requestBody;
};

/**
 * @testable false
 * @covered-by src/script/shared/polling.mjs::PollingCoordinator
 * @reason result normalization is exercised through coordinator response coverage
 */
const normalizedResult = (raw, descriptor, path) => {
	exactFields(
		raw,
		path,
		["id", "type", "status", "poll_after_ms"],
		["revision", "payload"],
	);
	if (raw.id !== descriptor.id)
		throw new PollContractError(`${path}.id`, "state");
	if (raw.type !== descriptor.type) {
		throw new PollContractError(`${path}.type`, "state");
	}
	if (!POLL_STATUSES.has(raw.status)) {
		throw new PollContractError(`${path}.status`, "unsupported");
	}
	if (!Number.isSafeInteger(raw.poll_after_ms)) {
		throw new PollContractError(`${path}.poll_after_ms`, "type");
	}
	if (raw.poll_after_ms <= 0) {
		throw new PollContractError(`${path}.poll_after_ms`, "state");
	}

	const carriesRevision =
		raw.status === "changed" || raw.status === "unchanged";
	if (carriesRevision && !Object.hasOwn(raw, "revision")) {
		throw new PollContractError(`${path}.revision`, "missing");
	}
	if (!carriesRevision && Object.hasOwn(raw, "revision")) {
		throw new PollContractError(`${path}.revision`, "unexpected");
	}
	let revision;
	if (carriesRevision) {
		revision =
			descriptor.type === "operation" || descriptor.type === "document"
				? integerRevision(raw.revision, `${path}.revision`)
				: boundedString(raw.revision, `${path}.revision`, MAX_CURSOR_LENGTH);
	}

	if (raw.status === "changed") {
		if (!Object.hasOwn(raw, "payload")) {
			throw new PollContractError(`${path}.payload`, "missing");
		}
		if (
			!raw.payload ||
			typeof raw.payload !== "object" ||
			Array.isArray(raw.payload)
		) {
			throw new PollContractError(`${path}.payload`, "type");
		}
	} else if (Object.hasOwn(raw, "payload")) {
		throw new PollContractError(`${path}.payload`, "unexpected");
	}

	if (raw.status === "changed" && descriptor.type === "document") {
		boundedString(
			raw.payload.generation,
			`${path}.payload.generation`,
			MAX_STATE_TOKEN_LENGTH,
		);
		const payloadRevision = integerRevision(
			raw.payload.revision,
			`${path}.payload.revision`,
		);
		if (payloadRevision !== revision) {
			throw new PollContractError(`${path}.payload.revision`, "state");
		}
		if (Object.hasOwn(raw.payload, "presence_digest")) {
			boundedString(
				raw.payload.presence_digest,
				`${path}.payload.presence_digest`,
				MAX_STATE_TOKEN_LENGTH,
			);
		}
	}
	if (raw.status === "changed" && descriptor.type === "operation") {
		const payloadRevision = integerRevision(
			raw.payload.revision,
			`${path}.payload.revision`,
		);
		if (payloadRevision !== revision || raw.payload.key !== descriptor.key) {
			throw new PollContractError(`${path}.payload`, "state");
		}
	}
	return {
		id: raw.id,
		type: raw.type,
		status: raw.status,
		poll_after_ms: raw.poll_after_ms,
		...(carriesRevision ? { revision } : {}),
		...(raw.status === "changed" ? { payload: raw.payload } : {}),
	};
};

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
	if (
		value !== null &&
		(!value.trim() || value.length > MAX_CLIENT_ID_LENGTH)
	) {
		captureError(new PollContractError("client_id", "state"), null, {
			context: "polling-request-contract",
			path: "client_id",
			reason: "state",
		});
		value = null;
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
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_schedules_modes_and_notification_seed
 * @tests tests_js/test_034_polling_coordinator.py::test_polling_coordinator_captures_and_isolates_contract_failures
 * @features polling
 * @dimensions batching cadence lifecycle coalescing acknowledgement reentrancy requested-cycle freshness
 * @pairs polling:batching polling:cadence polling:lifecycle polling:coalescing polling:acknowledgement
 * @pairs polling:reentrancy polling:requested-cycle polling:freshness polling:foreground polling:scheduled-initial
 * @pairs polling:protocol polling:validation polling:diagnostics polling:revision polling:presence
 * @pair notifications:cold-seed
 */
class PollingCoordinator {
	constructor(view) {
		this.view = view;
		this.clientId = clientId();
		this.subscriptions = new Map();
		this.protocolFailures = new Set();
		this.timer = null;
		this.activePoll = null;
		this.activeIds = new Set();
		this.inflight = null;
		this.followup = false;
		this.queuedIds = new Set();
		this.destroyed = false;
		this.notificationSeedPending = Boolean(window.__NOTIFICATION_STATE__?.miss);
		this._notificationState = (event) => {
			if (!event?.detail?.miss) return;
			this.notificationSeedPending = true;
			if (this.activePoll) this.followup = true;
			else this._schedule(0);
		};
	}

	init() {
		window.addEventListener?.("notification-state", this._notificationState);
		if (this.notificationSeedPending) this._schedule(0);
		return this;
	}

	_captureContract(error, context, details = {}) {
		const path = error?.path || "polling";
		const reason = error?.reason || "state";
		const signature = `${context}:${path}:${reason}:${details.subscription_type || ""}`;
		if (this.protocolFailures.has(signature)) return;
		this.protocolFailures.add(signature);
		captureError(error, this.view?.elt, {
			context,
			path,
			reason,
			...details,
		});
	}

	subscribe(
		descriptor,
		{
			onResult = null,
			beforePoll = null,
			mode = "periodic",
			initial = "immediate",
		} = {},
	) {
		if (this.destroyed) return () => {};
		if (!SUBSCRIPTION_MODES.has(mode) || !INITIAL_MODES.has(initial)) {
			throw new TypeError("Invalid polling subscription schedule.");
		}
		const existing = this.subscriptions.get(descriptor?.id);
		let normalized;
		try {
			normalized = normalizedDescriptor(
				{ ...existing?.descriptor, ...descriptor },
				"subscription",
			);
		} catch (error) {
			this._captureContract(error, "polling-request-contract", {
				subscription_type: descriptor?.type || "missing",
			});
			return () => {};
		}
		const now = Date.now();
		const schedule = existing
			? existing.dueAt
			: mode === "foreground"
				? Number.POSITIVE_INFINITY
				: initial === "immediate"
					? now
					: now + this._baseInterval(normalized.type);
		this.subscriptions.set(normalized.id, {
			...existing,
			descriptor: normalized,
			onResult: onResult ?? existing?.onResult ?? null,
			beforePoll: beforePoll ?? existing?.beforePoll ?? null,
			mode,
			dueAt: schedule,
			quiet: existing?.quiet ?? 0,
			errorCount: existing?.errorCount ?? 0,
		});
		this.pause();
		this._schedule(initial === "immediate" && mode === "periodic" ? 0 : null);
		return () => this.unsubscribe(normalized.id);
	}

	unsubscribe(id) {
		this.subscriptions.delete(id);
		this.queuedIds.delete(id);
		if (!this.subscriptions.size && !this.notificationSeedPending) this.pause();
		else this._schedule();
	}

	get(id) {
		const descriptor = this.subscriptions.get(id)?.descriptor;
		return descriptor ? { ...descriptor } : null;
	}

	update(id, patch = {}) {
		const subscription = this.subscriptions.get(id);
		if (!subscription) return;
		try {
			subscription.descriptor = normalizedDescriptor(
				{ ...subscription.descriptor, ...patch },
				"subscription",
			);
		} catch (error) {
			this._captureContract(error, "polling-request-contract", {
				subscription_type: subscription.descriptor.type,
			});
		}
	}

	acknowledge(id, revision) {
		const subscription = this.subscriptions.get(id);
		if (!subscription || revision === undefined || revision === null) return;
		const previous = subscription.descriptor;
		try {
			subscription.descriptor = normalizedDescriptor(
				{ ...previous, revision },
				"subscription",
			);
		} catch (error) {
			this._captureContract(error, "polling-request-contract", {
				subscription_type: previous.type,
			});
			return;
		}
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

	trigger(ids = null, { fresh = false } = {}) {
		const requested =
			ids === null
				? new Set(this.subscriptions.keys())
				: new Set(Array.isArray(ids) ? ids : [ids]);
		if (
			this.activePoll &&
			!fresh &&
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
		this._schedule();
		return Promise.resolve([]);
	}

	catchUp() {
		if (this.destroyed) return Promise.resolve([]);
		return this.trigger();
	}

	async closeDocuments(syncIds) {
		if (!Array.isArray(syncIds)) {
			this._captureContract(
				new PollContractError("closed_documents", "type"),
				"polling-request-contract",
			);
			return;
		}
		const closed = [];
		const identifiers = new Set();
		for (const [index, raw] of syncIds.entries()) {
			try {
				const syncId = documentId(raw, `closed_documents[${index}]`);
				if (!identifiers.has(syncId)) closed.push(syncId);
				identifiers.add(syncId);
			} catch (error) {
				this._captureContract(error, "polling-request-contract");
			}
		}
		if (!closed.length || !this.view.online) return;
		if (this.activePoll) await this.activePoll;
		let response = null;
		for (
			let offset = 0;
			offset < closed.length;
			offset += MAX_SUBSCRIPTIONS_PER_REQUEST
		) {
			const body = normalizedRequest({
				version: POLL_PROTOCOL_VERSION,
				client_id: this.clientId,
				subscriptions: [],
				closed_documents: closed.slice(
					offset,
					offset + MAX_SUBSCRIPTIONS_PER_REQUEST,
				),
			});
			response = await request.post(ENDPOINTS.poll, body, { keepalive: true });
			if (response?.status === 422) {
				this._captureContract(
					new PollContractError(
						response.path || "request",
						response.reason || "state",
					),
					"polling-request-rejected",
				);
			}
		}
		return response;
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
				result?.poll_after_ms ?? TYPE_INTERVALS[subscription.descriptor.type]
			);
		}
		return ORDINARY_INTERVALS[
			Math.min(subscription.quiet, ORDINARY_INTERVALS.length - 1)
		];
	}

	_baseInterval(type) {
		return TYPE_INTERVALS[type] || ORDINARY_INTERVALS[0];
	}

	_notificationRequest() {
		const state = window.__NOTIFICATION_STATE__;
		if (!state) return null;
		try {
			return normalizedNotificationState(
				state.miss
					? { generation: null, revision: null, seed: true }
					: {
							generation: state.generation,
							revision: state.revision,
							seed: false,
						},
			);
		} catch (error) {
			this._captureContract(error, "polling-request-contract");
			return null;
		}
	}

	_applyProtocolState(subscription, result) {
		const patch = {};
		if (result.revision !== undefined) patch.revision = result.revision;
		if (subscription.descriptor.type === "document" && result.payload) {
			patch.generation = result.payload.generation;
			if (Object.hasOwn(result.payload, "presence_digest")) {
				patch.presence_digest = result.payload.presence_digest;
			}
		}
		subscription.descriptor = normalizedDescriptor(
			{ ...subscription.descriptor, ...patch },
			"subscription",
		);
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
		const results = [];
		try {
			due = this._due();
			if (!due.length && !this.notificationSeedPending) return [];
			this.activeIds = new Set(due.map(({ descriptor }) => descriptor.id));
			for (const { descriptor } of due) {
				this.queuedIds.delete(descriptor.id);
			}
			const hooks = new Set(
				due.map(({ beforePoll }) => beforePoll).filter(Boolean),
			);
			for (const hook of hooks) await hook();
			await window.__PING_PENDING__;
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			const notificationState = this._notificationRequest();
			due = due.filter(
				(subscription) =>
					this.subscriptions.get(subscription.descriptor.id) === subscription,
			);
			if (!due.length && !this.notificationSeedPending) return [];

			this.pause();
			const byId = new Map(
				due.map((subscription) => [subscription.descriptor.id, subscription]),
			);
			const body = normalizedRequest({
				version: POLL_PROTOCOL_VERSION,
				client_id: this.clientId,
				subscriptions: due.map(({ descriptor }) => ({ ...descriptor })),
				closed_documents: [],
				...(notificationState ? { notification_state: notificationState } : {}),
			});
			if (notificationState?.seed) this.notificationSeedPending = false;
			this.inflight = request.post(ENDPOINTS.poll, body);
			const response = await this.inflight;
			if (!response?.ok) {
				if (
					response?.status === 422 &&
					response?.code === "invalid_poll_contract"
				) {
					this._captureContract(
						new PollContractError(
							response.path || "request",
							response.reason || "state",
						),
						"polling-request-rejected",
					);
				}
				const cycleJitter = 0.9 + Math.random() * 0.2;
				const scheduledAt = Date.now();
				for (const subscription of due) {
					subscription.dueAt =
						subscription.mode === "foreground"
							? Number.POSITIVE_INFINITY
							: scheduledAt +
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
			if (response.version !== POLL_PROTOCOL_VERSION) {
				throw new PollContractError("response.version", "unsupported");
			}
			if (!Array.isArray(response.results)) {
				throw new PollContractError("response.results", "type");
			}
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			const acceptedResults = new Map();
			const invalidIds = new Set();
			const seenIds = new Set();
			for (const [index, raw] of response.results.entries()) {
				const path = `response.results[${index}]`;
				const id = raw?.id;
				const subscription = byId.get(id);
				if (!subscription) {
					this._captureContract(
						new PollContractError(`${path}.id`, "unsupported"),
						"polling-response-contract",
					);
					continue;
				}
				if (seenIds.has(id)) {
					this._captureContract(
						new PollContractError(`${path}.id`, "duplicate"),
						"polling-response-contract",
						{ subscription_type: subscription.descriptor.type },
					);
					acceptedResults.delete(id);
					invalidIds.add(id);
					continue;
				}
				seenIds.add(id);
				try {
					acceptedResults.set(
						id,
						normalizedResult(raw, subscription.descriptor, path),
					);
				} catch (error) {
					invalidIds.add(id);
					this._captureContract(error, "polling-response-contract", {
						subscription_type: subscription.descriptor.type,
					});
				}
			}

			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const [id, subscription] of byId) {
				if (this.subscriptions.get(id) !== subscription) continue;
				const result = acceptedResults.get(id);
				if (!result) {
					if (!invalidIds.has(id)) {
						this._captureContract(
							new PollContractError("response.results", "missing"),
							"polling-response-contract",
							{ subscription_type: subscription.descriptor.type },
						);
					}
					const synthetic = {
						id,
						type: subscription.descriptor.type,
						status: "error",
					};
					results.push(synthetic);
					subscription.dueAt =
						subscription.mode === "foreground"
							? Number.POSITIVE_INFINITY
							: scheduledAt +
								jitter(this._interval(subscription, synthetic), cycleJitter);
					try {
						await subscription.onResult?.(synthetic);
					} catch (error) {
						captureError(error, this.view.elt, {
							context: "polling-subscription",
							subscription_id: id,
						});
					}
					continue;
				}
				results.push(result);
				const previousDescriptor = { ...subscription.descriptor };
				try {
					this._applyProtocolState(subscription, result);
					const accepted = await subscription.onResult?.(result);
					if (accepted === false) {
						subscription.descriptor = previousDescriptor;
					}
					subscription.dueAt =
						subscription.mode === "foreground"
							? Number.POSITIVE_INFINITY
							: scheduledAt +
								jitter(this._interval(subscription, result), cycleJitter);
				} catch (error) {
					subscription.descriptor = previousDescriptor;
					captureError(error, this.view.elt, {
						context: "polling-subscription",
						subscription_id: result.id,
					});
					subscription.dueAt =
						subscription.mode === "foreground"
							? Number.POSITIVE_INFINITY
							: scheduledAt +
								jitter(
									this._interval(subscription, {
										status: "error",
									}),
									cycleJitter,
								);
				}
			}
		} catch (error) {
			if (this.destroyed || this.view.hidden || !this.view.online) return [];
			if (error instanceof PollContractError) {
				this._captureContract(error, "polling-response-contract");
			} else {
				captureError(error, this.view.elt, { context: "polling-coordinator" });
			}
			const cycleJitter = 0.9 + Math.random() * 0.2;
			const scheduledAt = Date.now();
			for (const subscription of due) {
				subscription.dueAt =
					subscription.mode === "foreground"
						? Number.POSITIVE_INFINITY
						: scheduledAt +
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
			(!this.subscriptions.size && !this.notificationSeedPending) ||
			this.view.hidden ||
			!this.view.online
		)
			return;
		const periodicDue = Array.from(this.subscriptions.values())
			.filter(({ mode }) => mode === "periodic")
			.map(({ dueAt }) => dueAt);
		if (!this.notificationSeedPending && !periodicDue.length) return;
		const nextDue = this.notificationSeedPending
			? Date.now()
			: Math.min(...periodicDue);
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
		this.protocolFailures.clear();
		window.removeEventListener?.("notification-state", this._notificationState);
	}
}

export { PollingCoordinator };
