import type * as Sentry from "@sentry/browser";

import type { JobStatus as DeferredOperationStatus } from "../generated/poll.ts";

export type {
	JobStatus as DeferredOperationStatus,
	PollResponse,
} from "../generated/poll.ts";

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

export type NotificationState =
	| { generation: null; revision: null; count: null; miss: true }
	| { generation: string; revision: number; count: number; miss: false };

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
