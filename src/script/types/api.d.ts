import type * as Sentry from "@sentry/browser";

export interface EntityRevision {
	key: string;
	fingerprint: string;
	modified?: string | null;
}

export type UpstreamRetryOutcome =
	| "not_attempted"
	| "failed"
	| "recovered"
	| "service_worker";

interface ResponseMetadata {
	ok: boolean;
	status?: number;
	error?: string;
	code?: string;
	path?: string;
	reason?: string;
	html?: Document | "" | null;
	modal?: Document | string;
	redirect?: string;
	conflict?: boolean;
	removed?: boolean;
	unchanged?: true;
	updated?: boolean;
	etag?: string | null;
	pollChannel?: string | null;
	pollRevision?: string | null;
	reload?: boolean;
	entities?: EntityRevision[];
	upstreamUnavailable?: true;
	stale?: boolean;
	retryable?: boolean;
	outcomeUncertain?: boolean;
	retryOutcome?: UpstreamRetryOutcome;
}

export type RequestResult<T extends object = Record<never, never>> =
	ResponseMetadata & Partial<T>;

export interface DirectUploadSession {
	session_url: string;
	token: string;
	chunk_size: number;
}

export interface SessionUpdateResponse {
	userHash: string;
}

/** The coordinator validates the wire envelope and each result before use. */
export interface PollResponse {
	version: unknown;
	results: unknown;
}

export type NotificationState =
	| { generation: null; revision: null; count: null; miss: true }
	| { generation: string; revision: number; count: number; miss: false };

/** The owner-visible projection from deferred_job_lifecycle.status_projection. */
export interface DeferredOperationStatus {
	key: string;
	type: string | null;
	status: string | null;
	phase: string;
	phase_label: string;
	attempt: number;
	remaining_seconds: number | null;
	last_progress_at: string | null;
	retry_reason: string | null;
	elapsed_seconds: number;
	phase_elapsed_seconds: number;
	updated_at: string | null;
	next_attempt_at: string | null;
	revision: number;
	terminal: boolean;
	stale: boolean;
	recovering: boolean;
	source_widget: string | null;
	destination: string | null;
	entity_key: string | null;
	can_cancel?: boolean;
	target_key?: string | null;
	operation_id?: string | null;
	snapshot_revision?: string | null;
	error?: string;
}

declare global {
	interface Window {
		Sentry?: Pick<
			typeof Sentry,
			| "addEventProcessor"
			| "captureException"
			| "captureMessage"
			| "getClient"
			| "init"
		>;
		__NOTIFICATION_STATE__?: NotificationState;
		__TESTING__?: boolean;
		__TEST_UPSTREAM_UNAVAILABLE__?: () => Promise<RequestResult | undefined>;
	}

	interface WindowEventMap {
		"notification-state": CustomEvent<NotificationState>;
		"entity-updated": CustomEvent<EntityRevision>;
		"deferred-operation": CustomEvent<DeferredOperationStatus>;
	}
}
