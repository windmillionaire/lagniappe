import type { DeferredOperationStatus } from "../../types/api.d.ts";
import type {
	DocumentCursor,
	DocumentPollPayload,
} from "../../types/sync.d.ts";

export const POLL_PROTOCOL_VERSION = 1;
export const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const MAX_KEY_LENGTH = 512;
const MAX_IDENTIFIER_LENGTH = MAX_KEY_LENGTH + 128;
export const MAX_CLIENT_ID_LENGTH = 128;
const MAX_CURSOR_LENGTH = 512;
const MAX_STATE_TOKEN_LENGTH = 128;
const MAX_REVISION = Number.MAX_SAFE_INTEGER;

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

export type PollType = keyof PollDescriptorFields;

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

export class PollContractError extends TypeError {
	declare readonly path: string;
	declare readonly reason: string;

	constructor(path: string, reason: string) {
		super(`${path}: ${reason}`);
		this.name = "PollContractError";
		this.path = path;
		this.reason = reason;
	}
}

export function isFieldMap(value: unknown): value is Record<string, unknown> {
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

export const documentId = (raw: unknown, path: string) => {
	const value = boundedString(raw, path, MAX_KEY_LENGTH);
	if (!value.endsWith(":document")) {
		throw new PollContractError(path, "unsupported");
	}
	return value;
};

export const normalizedDescriptor = (
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

export const normalizedNotificationState = (
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

export const normalizedRequest = (value: unknown): PollRequest => {
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

export const normalizedResult = (
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
