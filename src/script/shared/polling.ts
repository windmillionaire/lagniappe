import type {
	DeferredOperationStatus,
	NotificationState,
	PollResponse,
	RequestResult,
} from "../types/api.d.ts";
import type { DocumentCursor, DocumentPollPayload } from "../types/sync.d.ts";
import { ENDPOINTS } from "./endpoints.ts";
import { captureError } from "./errors.ts";
import { request } from "./request.ts";

declare global {
	interface Window {
		__PING_PENDING__?: Promise<boolean> | null;
	}
}

const POLL_PROTOCOL_VERSION = 1;
const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const MAX_KEY_LENGTH = 512;
const MAX_IDENTIFIER_LENGTH = MAX_KEY_LENGTH + 128;
const MAX_CLIENT_ID_LENGTH = 128;
const MAX_CURSOR_LENGTH = 512;
const MAX_STATE_TOKEN_LENGTH = 128;
const MAX_REVISION = Number.MAX_SAFE_INTEGER;
const CLIENT_ID_KEY = "lagniappe-poll-client";
const VISIBLE_BLUR_POLLING_MS = 10 * 60 * 1000;
const ORDINARY_INTERVALS = [15_000, 15_000, 30_000, 30_000, 60_000];
const TYPE_INTERVALS: Readonly<
	Partial<Record<PollType, number>> &
		Record<"document" | "ingress" | "operation", number>
> = Object.freeze({
	document: 2_000,
	ingress: 2_500,
	operation: 4_000,
});
const SUBSCRIPTION_MODES = new Set(["periodic", "foreground"]);
const INITIAL_MODES = new Set(["immediate", "scheduled"]);
const POLL_TYPES = new Set<PollType>([
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
	"messages",
	"home",
	"home-notes",
	"starred",
	"tool-reports",
] as const);
const POLL_STATUSES = new Set<PollResult["status"]>([
	"changed",
	"unchanged",
	"unavailable",
	"error",
]);

type PollChannel =
	typeof POLL_CHANNELS extends ReadonlySet<infer Channel> ? Channel : never;

interface PollDescriptorFields {
	entity: { key: string; revision: string | null };
	channel: { channel: PollChannel; revision: string | null };
	"form-lock": { key: string; revision: string };
	document: DocumentCursor & { key: string; sync_id: string };
	operation: { key: string; revision: number };
	ingress: { key: string; revision: string | null };
}

type PollType = keyof PollDescriptorFields;

export type PollDescriptor<T extends PollType = PollType> = {
	[K in T]: { id: string; type: K } & PollDescriptorFields[K];
}[T];

interface PollPayloads {
	entity: { fingerprint: string; modified: string | null };
	channel: { refresh: true };
	"form-lock":
		| { locked: false }
		| {
				key: string;
				locked: true;
				scope: string | null;
				operation: string;
				revision: number;
		  };
	document: DocumentPollPayload;
	operation: DeferredOperationStatus;
	ingress: { refresh: true };
}

type PollRevision<T extends PollType> = NonNullable<
	PollDescriptorFields[T]["revision"]
>;

export type PollResult<T extends PollType = PollType> = {
	[K in T]: { id: string; type: K } & (
		| {
				status: "changed";
				revision: PollRevision<K>;
				payload: PollPayloads[K];
				poll_after_ms: number;
		  }
		| {
				status: "unchanged";
				revision: PollRevision<K>;
				payload?: never;
				poll_after_ms: number;
		  }
		| {
				status: "unavailable";
				revision?: never;
				payload?: never;
				poll_after_ms: number;
		  }
		| {
				status: "error";
				revision?: never;
				payload?: never;
				poll_after_ms?: number;
		  }
	);
}[T];

type NotificationCursor =
	| { generation: null; revision: null; seed: true }
	| { generation: string; revision: number; seed: false };

interface PollRequest {
	version: typeof POLL_PROTOCOL_VERSION;
	client_id: string;
	subscriptions: PollDescriptor[];
	closed_documents: string[];
	notification_state?: NotificationCursor;
}

interface PollView {
	elt?: HTMLElement | null;
	online: boolean;
	hidden: boolean;
}

interface ScheduleOptions<T extends PollType> {
	onResult?: ((result: PollResult<T>) => unknown) | null;
	beforePoll?: (() => unknown) | null;
	whileBlurred?: (() => boolean) | null;
	mode?: "periodic" | "foreground";
	initial?: "immediate" | "scheduled";
}

interface PollSubscription
	extends Required<Omit<ScheduleOptions<PollType>, "initial">> {
	descriptor: PollDescriptor;
	dueAt: number;
	quiet: number;
	errorCount: number;
	boostedUntil?: number;
	boostedInterval?: number;
}

class PollContractError extends TypeError {
	declare readonly path: string;
	declare readonly reason: string;

	constructor(path: string, reason: string) {
		super(`${path}: ${reason}`);
		this.name = "PollContractError";
		this.path = path;
		this.reason = reason;
	}
}

function isFieldMap(value: unknown): value is Record<string, unknown> {
	return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

const exactFields = (
	value: unknown,
	path: string,
	required: string[],
	optional: string[] = [],
) => {
	if (!isFieldMap(value)) {
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

function boundedString(value: unknown, path: string, maximum: number): string;
function boundedString(
	value: unknown,
	path: string,
	maximum: number,
	options: { nullable: boolean },
): string | null;
function boundedString(
	value: unknown,
	path: string,
	maximum: number,
	{ nullable = false } = {},
) {
	if (nullable && value === null) return null;
	if (typeof value !== "string") throw new PollContractError(path, "type");
	if (!value.trim()) throw new PollContractError(path, "blank");
	if (value.length > maximum) throw new PollContractError(path, "limit");
	return value;
}

const integerRevision = (value: unknown, path: string) => {
	if (typeof value !== "number" || !Number.isInteger(value))
		throw new PollContractError(path, "type");
	if (value < 0) throw new PollContractError(path, "state");
	if (value > MAX_REVISION) throw new PollContractError(path, "limit");
	return value;
};

const documentId = (raw: unknown, path: string) => {
	const value = boundedString(raw, path, MAX_KEY_LENGTH);
	if (!value.endsWith(":document")) {
		throw new PollContractError(path, "unsupported");
	}
	return value;
};

const normalizedDescriptor = (
	value: unknown,
	path = "descriptor",
): PollDescriptor => {
	const raw = exactFields(
		value,
		path,
		["id", "type", "revision"],
		["key", "channel", "sync_id", "generation", "presence_digest"],
	);
	const id = boundedString(raw.id, `${path}.id`, MAX_IDENTIFIER_LENGTH);
	const type = boundedString(raw.type, `${path}.type`, 32) as PollType;
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
	switch (type) {
		case "channel": {
			const revision = boundedString(
				raw.revision,
				`${path}.revision`,
				MAX_CURSOR_LENGTH,
				{ nullable: true },
			);
			const channel = boundedString(
				raw.channel,
				`${path}.channel`,
				64,
			) as PollChannel;
			if (!POLL_CHANNELS.has(channel)) {
				throw new PollContractError(`${path}.channel`, "unsupported");
			}
			return { id, type, revision, channel };
		}
		case "operation":
			return {
				id,
				type,
				revision: integerRevision(raw.revision, `${path}.revision`),
				key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH),
			};
		case "document":
			return {
				id,
				type,
				revision: integerRevision(raw.revision, `${path}.revision`),
				key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH),
				sync_id: documentId(raw.sync_id, `${path}.sync_id`),
				generation: boundedString(
					raw.generation,
					`${path}.generation`,
					MAX_STATE_TOKEN_LENGTH,
					{ nullable: true },
				),
				presence_digest: boundedString(
					raw.presence_digest,
					`${path}.presence_digest`,
					MAX_STATE_TOKEN_LENGTH,
					{ nullable: true },
				),
			};
		case "form-lock":
			return {
				id,
				type,
				revision: boundedString(
					raw.revision,
					`${path}.revision`,
					MAX_CURSOR_LENGTH,
				),
				key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH),
			};
		default:
			return {
				id,
				type,
				revision: boundedString(
					raw.revision,
					`${path}.revision`,
					MAX_CURSOR_LENGTH,
					{ nullable: true },
				),
				key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH),
			};
	}
};

const normalizedNotificationState = (
	value: unknown,
	path = "notification_state",
): NotificationCursor => {
	const raw = exactFields(value, path, ["generation", "revision", "seed"]);
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
	if (cold) return { generation, revision, seed: true };
	if (warm) return { generation, revision, seed: false };
	throw new PollContractError(path, "state");
};

const normalizedRequest = (value: unknown): PollRequest => {
	const raw = exactFields(
		value,
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
	const identifiers = new Set<string>();
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
	const closedIds = new Set<string>();
	const closed_documents = raw.closed_documents.map((syncId, index) => {
		const path = `request.closed_documents[${index}]`;
		const normalized = documentId(syncId, path);
		if (closedIds.has(normalized)) {
			throw new PollContractError(path, "duplicate");
		}
		closedIds.add(normalized);
		return normalized;
	});
	const requestBody: PollRequest = {
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

const normalizedResult = (
	value: unknown,
	descriptor: PollDescriptor,
	path: string,
): PollResult => {
	const raw = exactFields(
		value,
		path,
		["id", "type", "status", "poll_after_ms"],
		["revision", "payload"],
	);
	if (raw.id !== descriptor.id)
		throw new PollContractError(`${path}.id`, "state");
	if (raw.type !== descriptor.type) {
		throw new PollContractError(`${path}.type`, "state");
	}
	const status = raw.status as PollResult["status"];
	if (!POLL_STATUSES.has(status)) {
		throw new PollContractError(`${path}.status`, "unsupported");
	}
	if (
		typeof raw.poll_after_ms !== "number" ||
		!Number.isSafeInteger(raw.poll_after_ms)
	) {
		throw new PollContractError(`${path}.poll_after_ms`, "type");
	}
	if (raw.poll_after_ms <= 0) {
		throw new PollContractError(`${path}.poll_after_ms`, "state");
	}

	const carriesRevision = status === "changed" || status === "unchanged";
	if (carriesRevision && !Object.hasOwn(raw, "revision")) {
		throw new PollContractError(`${path}.revision`, "missing");
	}
	if (!carriesRevision && Object.hasOwn(raw, "revision")) {
		throw new PollContractError(`${path}.revision`, "unexpected");
	}
	let revision: string | number | undefined;
	if (carriesRevision) {
		revision =
			descriptor.type === "operation" || descriptor.type === "document"
				? integerRevision(raw.revision, `${path}.revision`)
				: boundedString(raw.revision, `${path}.revision`, MAX_CURSOR_LENGTH);
	}

	let payload: Record<string, unknown> | undefined;
	if (status === "changed") {
		if (!Object.hasOwn(raw, "payload")) {
			throw new PollContractError(`${path}.payload`, "missing");
		}
		if (!isFieldMap(raw.payload)) {
			throw new PollContractError(`${path}.payload`, "type");
		}
		payload = raw.payload;
	} else if (Object.hasOwn(raw, "payload")) {
		throw new PollContractError(`${path}.payload`, "unexpected");
	}

	if (payload && descriptor.type === "document") {
		boundedString(
			payload.generation,
			`${path}.payload.generation`,
			MAX_STATE_TOKEN_LENGTH,
		);
		const payloadRevision = integerRevision(
			payload.revision,
			`${path}.payload.revision`,
		);
		if (payloadRevision !== revision) {
			throw new PollContractError(`${path}.payload.revision`, "state");
		}
		if (Object.hasOwn(payload, "presence_digest")) {
			boundedString(
				payload.presence_digest,
				`${path}.payload.presence_digest`,
				MAX_STATE_TOKEN_LENGTH,
			);
		}
	}
	if (payload && descriptor.type === "operation") {
		const payloadRevision = integerRevision(
			payload.revision,
			`${path}.payload.revision`,
		);
		if (payloadRevision !== revision || payload.key !== descriptor.key) {
			throw new PollContractError(`${path}.payload`, "state");
		}
	}
	// The checks above enforce the envelope and cursor. The route supplies the
	// remaining type-specific payload fields.
	return {
		id: descriptor.id,
		type: descriptor.type,
		status,
		poll_after_ms: raw.poll_after_ms,
		...(carriesRevision ? { revision } : {}),
		...(status === "changed" ? { payload } : {}),
	} as PollResult;
};

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

function jitter(delay: number, factor = 0.9 + Math.random() * 0.2) {
	return Math.max(Math.round(delay * factor), 250);
}

/**
 * One view-scoped scheduler for every server-state subscription.
 *
 */
export class PollingCoordinator {
	declare view: PollView;
	declare clientId: string;
	declare subscriptions: Map<string, PollSubscription>;
	declare protocolFailures: Set<string>;
	declare timer: number | null;
	declare activePoll: Promise<PollResult[]> | null;
	declare activeIds: Set<string>;
	declare inflight: Promise<RequestResult<PollResponse> | undefined> | null;
	declare followup: boolean;
	declare queuedIds: Set<string>;
	declare destroyed: boolean;
	declare blurredUntil: number | null;
	declare notificationSeedPending: boolean;
	declare notificationSeedDueAt: number;
	declare notificationSeedErrorCount: number;
	declare notificationSeedActive: boolean;
	declare _notificationState: (event: CustomEvent<NotificationState>) => void;

	constructor(view: PollView) {
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
		this.blurredUntil = null;
		this.notificationSeedPending = Boolean(window.__NOTIFICATION_STATE__?.miss);
		this.notificationSeedDueAt = this.notificationSeedPending
			? Date.now()
			: Number.POSITIVE_INFINITY;
		this.notificationSeedErrorCount = 0;
		this.notificationSeedActive = false;
		this._notificationState = (event) => {
			if (!event?.detail?.miss) {
				this.notificationSeedPending = false;
				this.notificationSeedDueAt = Number.POSITIVE_INFINITY;
				this.notificationSeedErrorCount = 0;
				if (!this.activePoll) {
					this._clearTimer();
					this._schedule();
				}
				return;
			}

			const alreadyPending = this.notificationSeedPending;
			this.notificationSeedPending = true;
			if (this.notificationSeedActive) return;
			if (!alreadyPending) {
				this.notificationSeedErrorCount = 0;
				this.notificationSeedDueAt = Date.now();
			}
			if (this.activePoll) this.followup = true;
			else {
				this._clearTimer();
				this._schedule(this.view.hidden ? null : 0);
			}
		};
	}

	init() {
		window.addEventListener?.("notification-state", this._notificationState);
		if (this.notificationSeedPending) this._schedule(0);
		return this;
	}

	_captureContract(
		error: unknown,
		context: string,
		details: { subscription_type?: string } = {},
	) {
		const contract = error as Partial<PollContractError> | null | undefined;
		const path = contract?.path || "polling";
		const reason = contract?.reason || "state";
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

	subscribe<T extends PollType>(
		descriptor: PollDescriptor & { type: T },
		{
			onResult = null,
			beforePoll = null,
			whileBlurred = null,
			mode = "periodic",
			initial = "immediate",
		}: ScheduleOptions<NoInfer<T>> = {},
	) {
		if (this.destroyed) return () => {};
		if (
			!SUBSCRIPTION_MODES.has(mode) ||
			!INITIAL_MODES.has(initial) ||
			(whileBlurred !== null && typeof whileBlurred !== "function")
		) {
			throw new TypeError("Invalid polling subscription schedule.");
		}
		const existing = this.subscriptions.get(descriptor?.id);
		let normalized: PollDescriptor;
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
			// A result dispatches to its own ID after its descriptor type is checked.
			onResult:
				(onResult as PollSubscription["onResult"]) ??
				existing?.onResult ??
				null,
			beforePoll: beforePoll ?? existing?.beforePoll ?? null,
			whileBlurred: whileBlurred ?? existing?.whileBlurred ?? null,
			mode,
			dueAt: schedule,
			quiet: existing?.quiet ?? 0,
			errorCount: existing?.errorCount ?? 0,
		});
		this._clearTimer();
		this._schedule(initial === "immediate" && mode === "periodic" ? 0 : null);
		return () => this.unsubscribe(normalized.id);
	}

	unsubscribe(id: string) {
		this.subscriptions.delete(id);
		this.queuedIds.delete(id);
		if (!this.subscriptions.size && !this.notificationSeedPending)
			this._clearTimer();
		else this._schedule();
	}

	get(id: string) {
		const descriptor = this.subscriptions.get(id)?.descriptor;
		return descriptor ? { ...descriptor } : null;
	}

	update(id: string, patch: Partial<PollDescriptor> = {}) {
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

	boost(
		id: string,
		{ durationMs = 60_000, pollAfterMs = TYPE_INTERVALS.document } = {},
	) {
		const subscription = this.subscriptions.get(id);
		if (!subscription) return false;
		if (
			!Number.isSafeInteger(durationMs) ||
			durationMs <= 0 ||
			!Number.isSafeInteger(pollAfterMs) ||
			pollAfterMs < 250
		) {
			throw new TypeError("Invalid polling boost schedule.");
		}
		const now = Date.now();
		subscription.boostedUntil = Math.max(
			subscription.boostedUntil || 0,
			now + durationMs,
		);
		subscription.boostedInterval = pollAfterMs;
		subscription.quiet = 0;
		const awaitingActiveResult =
			this.activeIds.has(id) && subscription.dueAt <= now;
		if (!awaitingActiveResult) {
			subscription.dueAt = Math.min(subscription.dueAt, now + pollAfterMs);
			this._clearTimer();
			this._schedule();
		}
		return true;
	}

	acknowledge(id: string, revision: PollDescriptor["revision"] | undefined) {
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
	enqueue(ids: string | string[] | null = null) {
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

	trigger(
		ids: string | string[] | null = null,
		{ fresh = false } = {},
	): Promise<PollResult[]> {
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

	_clearTimer() {
		if (this.timer) window.clearTimeout(this.timer);
		this.timer = null;
	}

	pause() {
		this.blurredUntil = null;
		this._clearTimer();
	}

	blur(startedAt = Date.now()) {
		if (this.destroyed) return;
		if (this.blurredUntil === null) {
			this.blurredUntil = startedAt + VISIBLE_BLUR_POLLING_MS;
		}
		this._clearTimer();
		this._schedule();
	}

	reschedule() {
		if (this.destroyed) return;
		this._clearTimer();
		this._schedule();
	}

	resume() {
		if (this.destroyed) return Promise.resolve([]);
		this.blurredUntil = null;
		this._schedule();
		return Promise.resolve([]);
	}

	catchUp() {
		if (this.destroyed) return Promise.resolve([]);
		this.blurredUntil = null;
		return this.trigger();
	}

	async closeDocuments(syncIds: string[]) {
		if (!Array.isArray(syncIds)) {
			this._captureContract(
				new PollContractError("closed_documents", "type"),
				"polling-request-contract",
			);
			return;
		}
		const closed = [];
		const identifiers = new Set<string>();
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
			response = await request.post<PollResponse>(ENDPOINTS.poll, body, {
				keepalive: true,
				replaceErrorPage: false,
			});
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

	_interval(
		subscription: PollSubscription,
		result: Pick<PollResult, "status" | "poll_after_ms">,
	) {
		if (result?.status === "error") {
			subscription.errorCount += 1;
			return Math.min(2 ** subscription.errorCount * 2_000, 60_000);
		}
		subscription.errorCount = 0;
		if (result?.status === "changed") subscription.quiet = 0;
		else subscription.quiet += 1;
		if (
			subscription.boostedUntil !== undefined &&
			subscription.boostedUntil > Date.now() &&
			subscription.boostedInterval
		) {
			return subscription.boostedInterval;
		}

		if (subscription.descriptor.type === "operation") {
			const steps = [4_000, 8_000, 16_000, 30_000];
			return steps[Math.min(subscription.quiet, steps.length - 1)];
		}
		const interval = TYPE_INTERVALS[subscription.descriptor.type];
		if (interval) {
			return result?.poll_after_ms ?? interval;
		}
		return ORDINARY_INTERVALS[
			Math.min(subscription.quiet, ORDINARY_INTERVALS.length - 1)
		];
	}

	_baseInterval(type: PollType) {
		return TYPE_INTERVALS[type] || ORDINARY_INTERVALS[0];
	}

	_eligible(subscription: PollSubscription) {
		if (this.destroyed || !this.view.online) return false;
		if (!this.view.hidden) return true;
		if (this.blurredUntil === null || Date.now() >= this.blurredUntil) {
			return false;
		}
		return subscription?.whileBlurred?.() === true;
	}

	_hasEligible(
		subscriptions: Iterable<PollSubscription> = this.subscriptions.values(),
	) {
		return Array.from(subscriptions).some((subscription) =>
			this._eligible(subscription),
		);
	}

	_notificationRequest() {
		const state = window.__NOTIFICATION_STATE__;
		if (!state) return null;
		if (
			state.miss &&
			(!this.notificationSeedPending || this.notificationSeedDueAt > Date.now())
		) {
			return null;
		}
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

	_notificationSeedFailed() {
		if (!this.notificationSeedPending) return;
		this.notificationSeedErrorCount += 1;
		const delay = Math.min(
			2 ** this.notificationSeedErrorCount * 2_000,
			60_000,
		);
		this.notificationSeedDueAt = Date.now() + jitter(delay);
	}

	_applyProtocolState(subscription: PollSubscription, result: PollResult) {
		const patch: {
			revision?: string | number;
			generation?: string;
			presence_digest?: string;
		} = {};
		if (result.revision !== undefined) patch.revision = result.revision;
		if (subscription.descriptor.type === "document" && result.payload) {
			const document = result.payload as DocumentPollPayload;
			patch.generation = document.generation;
			if (Object.hasOwn(document, "presence_digest")) {
				patch.presence_digest = document.presence_digest;
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
			.filter(
				(subscription) =>
					subscription.dueAt <= now && this._eligible(subscription),
			)
			.slice(0, MAX_SUBSCRIPTIONS_PER_REQUEST);
	}

	_poll(): Promise<PollResult[]> {
		if (
			this.destroyed ||
			!this.view.online ||
			(this.view.hidden && !this._hasEligible())
		) {
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

	async _runPoll(): Promise<PollResult[]> {
		let due: PollSubscription[] = [];
		const results: PollResult[] = [];
		let seededNotification = false;
		try {
			due = this._due();
			const notificationOnly =
				!this.view.hidden &&
				this.notificationSeedPending &&
				this.notificationSeedDueAt <= Date.now();
			if (!due.length && !notificationOnly) return [];
			this.activeIds = new Set(due.map(({ descriptor }) => descriptor.id));
			for (const { descriptor } of due) {
				this.queuedIds.delete(descriptor.id);
			}
			const hooks = new Set(due.map(({ beforePoll }) => beforePoll));
			for (const hook of hooks) if (hook) await hook();
			await window.__PING_PENDING__;
			if (this.destroyed || !this.view.online) return [];
			const notificationState = this._notificationRequest();
			due = due.filter(
				(subscription) =>
					this.subscriptions.get(subscription.descriptor.id) === subscription &&
					this._eligible(subscription),
			);
			if (!due.length && (this.view.hidden || !notificationState?.seed)) {
				return [];
			}

			this._clearTimer();
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
			seededNotification = notificationState?.seed === true;
			if (seededNotification) this.notificationSeedActive = true;
			this.inflight = request.post<PollResponse>(ENDPOINTS.poll, body, {
				replaceErrorPage: false,
			});
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
				for (const subscription of due.filter((item) => this._eligible(item))) {
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
			if (
				this.destroyed ||
				!this.view.online ||
				(this.view.hidden && !this._hasEligible(byId.values()))
			)
				return [];
			const acceptedResults = new Map<string, PollResult>();
			const invalidIds = new Set<string>();
			const seenIds = new Set<string>();
			const rawResults: unknown[] = response.results;
			for (const [index, raw] of rawResults.entries()) {
				const path = `response.results[${index}]`;
				const id = isFieldMap(raw) ? raw.id : undefined;
				const subscription = typeof id === "string" ? byId.get(id) : undefined;
				if (typeof id !== "string" || !subscription) {
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
			const resultPriority = ([id]: [string, PollSubscription]) => {
				const result = acceptedResults.get(id);
				return result?.type === "operation" &&
					result.status === "changed" &&
					result.payload?.terminal
					? 0
					: 1;
			};
			const orderedSubscriptions = Array.from(byId);
			orderedSubscriptions.sort(
				(left, right) => resultPriority(left) - resultPriority(right),
			);
			for (const [id, subscription] of orderedSubscriptions) {
				if (this.subscriptions.get(id) !== subscription) continue;
				if (!this._eligible(subscription)) continue;
				const result = acceptedResults.get(id);
				if (!result) {
					if (!invalidIds.has(id)) {
						this._captureContract(
							new PollContractError("response.results", "missing"),
							"polling-response-contract",
							{ subscription_type: subscription.descriptor.type },
						);
					}
					const synthetic: PollResult = {
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
			if (this.destroyed || !this.view.online) return [];
			due = due.filter((subscription) => this._eligible(subscription));
			if (!due.length && this.view.hidden) return [];
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
			if (seededNotification) {
				this.notificationSeedActive = false;
				this._notificationSeedFailed();
			}
			this.inflight = null;
			const now = Date.now();
			for (const id of this.queuedIds) {
				const subscription = this.subscriptions.get(id);
				if (subscription) subscription.dueAt = now;
			}
		}
		return results;
	}

	_schedule(delay: number | null = null) {
		if (
			this.destroyed ||
			this.timer ||
			(!this.subscriptions.size && !this.notificationSeedPending) ||
			!this.view.online
		)
			return;
		const periodicDue = Array.from(this.subscriptions.values())
			.filter(
				(subscription) =>
					subscription.mode === "periodic" && this._eligible(subscription),
			)
			.map(({ dueAt }) => dueAt);
		const notificationDueAt =
			!this.view.hidden && this.notificationSeedPending
				? this.notificationSeedDueAt
				: Number.POSITIVE_INFINITY;
		if (!Number.isFinite(notificationDueAt) && !periodicDue.length) return;
		const nextDue = Math.min(notificationDueAt, ...periodicDue);
		if (
			this.view.hidden &&
			this.blurredUntil !== null &&
			nextDue >= this.blurredUntil
		)
			return;
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
