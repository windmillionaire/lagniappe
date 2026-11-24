import type { DirectUploadSession } from "../types/api";
import { request } from "./request.ts";

const DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024;
const DEFAULT_DIRECT_UPLOAD_RETRIES = 3;
const DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS = 500;
const RESUMABLE_UPLOAD_INCOMPLETE = 308;
const RETRYABLE_DIRECT_UPLOAD_STATUSES = new Set([
	408, 429, 500, 502, 503, 504,
]);

interface DirectUploadSessionOptions {
	route: string;
	file: File;
	inputName?: string;
	replaceErrorPage?: boolean;
}

type UnvalidatedSession = Partial<Record<keyof DirectUploadSession, unknown>>;
type UploadSession = Pick<DirectUploadSession, "session_url" | "token"> &
	Partial<Pick<DirectUploadSession, "chunk_size">>;

type UploadProgress = (loaded: number, total: number) => void;

interface UploadTarget {
	file: File;
	sessionUrl: string;
}

interface UploadRetry extends UploadTarget {
	attempt: number;
	retries: number;
	retryDelay: number;
	onProgress: UploadProgress;
}

interface UploadChunk extends UploadTarget {
	offset: number;
	end: number;
}

interface UploadOptions extends UploadTarget {
	chunkSize?: number;
	retries?: number;
	retryDelay?: number;
	onProgress?: UploadProgress;
}

interface UploadMetadata extends Record<string, unknown> {
	generation?: string | number;
	name?: string;
}

const directUploadRoute = (route?: string | null) => {
	if (!route) return null;

	const url = new URL(route, window.location.origin);
	url.pathname = `${url.pathname.replace(/\/$/, "")}/direct-upload`;
	return `${url.pathname}${url.search}`;
};

const createDirectUploadSession = async ({
	route,
	file,
	inputName,
	replaceErrorPage = true,
}: DirectUploadSessionOptions) => {
	const url = directUploadRoute(route);
	if (!url) throw new Error("Could not start direct upload");
	const response = await request.post<UnvalidatedSession>(
		url,
		{
			filename: file.name,
			content_type: file.type || "application/octet-stream",
			size: file.size,
			input_name: inputName,
		},
		{ replaceErrorPage },
	);
	if (!response?.ok) {
		throw new Error(response?.error || "Could not start direct upload");
	}
	if (!isDirectUploadSession(response)) {
		throw new Error("Could not start direct upload");
	}
	return response;
};

function isDirectUploadSession(
	response: UnvalidatedSession,
): response is UploadSession {
	const { session_url, token, chunk_size } = response;
	return (
		typeof session_url === "string" &&
		session_url.length > 0 &&
		typeof token === "string" &&
		token.length > 0 &&
		(chunk_size === undefined ||
			(typeof chunk_size === "number" &&
				Number.isInteger(chunk_size) &&
				chunk_size > 0))
	);
}

const directUploadRetryDelay = (attempt: number, baseDelay: number) =>
	baseDelay * 2 ** Math.max(0, attempt - 1);

const wait = (delayMs: number) =>
	delayMs > 0
		? new Promise<void>((resolve) => setTimeout(resolve, delayMs))
		: Promise.resolve();

const directUploadOffset = (response: Response) => {
	const range = response.headers.get("Range") || "";
	const match = /^bytes=0-(\d+)$/i.exec(range.trim());
	return match ? Number.parseInt(match[1], 10) + 1 : 0;
};

const directUploadStatusOffset = async ({ file, sessionUrl }: UploadTarget) => {
	const response = await fetch(sessionUrl, {
		method: "PUT",
		headers: {
			"Content-Range": `bytes */${file.size}`,
		},
	});

	if (response.status === RESUMABLE_UPLOAD_INCOMPLETE) {
		return directUploadOffset(response);
	}

	if (response.ok) return file.size;

	const message = await response.text().catch(() => "");
	throw new Error(message || "Could not resume direct upload");
};

const shouldRetryDirectUpload = (response: Response) =>
	RETRYABLE_DIRECT_UPLOAD_STATUSES.has(response.status);

const resumeDirectUpload = async ({
	file,
	sessionUrl,
	attempt,
	retries,
	retryDelay,
	onProgress,
}: UploadRetry) => {
	let statusAttempt = attempt;
	let lastError: unknown = null;

	while (statusAttempt <= retries) {
		await wait(directUploadRetryDelay(statusAttempt, retryDelay));
		try {
			const offset = await directUploadStatusOffset({ file, sessionUrl });
			onProgress(offset, file.size);
			return { attempt: statusAttempt, offset };
		} catch (error) {
			lastError = error;
			if (statusAttempt >= retries) break;
			statusAttempt += 1;
		}
	}

	throw lastError || new Error("Could not resume direct upload");
};

const directUploadChunk = ({ file, sessionUrl, offset, end }: UploadChunk) =>
	fetch(sessionUrl, {
		method: "PUT",
		headers: {
			"Content-Type": file.type || "application/octet-stream",
			"Content-Range": `bytes ${offset}-${end}/${file.size}`,
		},
		body: file.slice(offset, end + 1),
	});

const uploadDirectFile = async ({
	file,
	sessionUrl,
	chunkSize = DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE,
	retries = DEFAULT_DIRECT_UPLOAD_RETRIES,
	retryDelay = DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS,
	onProgress = () => {},
}: UploadOptions): Promise<UploadMetadata> => {
	if (!file.size) return {};

	let offset = 0;
	let retryAttempt = 0;
	while (offset < file.size) {
		const end = Math.min(offset + chunkSize, file.size) - 1;
		let response: Response;

		try {
			response = await directUploadChunk({ file, sessionUrl, offset, end });
		} catch (error) {
			if (retryAttempt >= retries) throw error;
			retryAttempt += 1;
			const resume = await resumeDirectUpload({
				file,
				sessionUrl,
				attempt: retryAttempt,
				retries,
				retryDelay,
				onProgress,
			});
			retryAttempt = resume.attempt;
			offset = resume.offset;
			continue;
		}

		if (shouldRetryDirectUpload(response)) {
			if (retryAttempt >= retries) {
				const message = await response.text().catch(() => "");
				throw new Error(message || "Direct upload failed");
			}
			retryAttempt += 1;
			const resume = await resumeDirectUpload({
				file,
				sessionUrl,
				attempt: retryAttempt,
				retries,
				retryDelay,
				onProgress,
			});
			retryAttempt = resume.attempt;
			offset = resume.offset;
			continue;
		}

		if (response.status === RESUMABLE_UPLOAD_INCOMPLETE) {
			const nextOffset = directUploadOffset(response);
			if (nextOffset <= offset) {
				throw new Error("Direct upload did not advance");
			}
			offset = nextOffset;
			retryAttempt = 0;
			onProgress(offset, file.size);
			continue;
		}

		if (!response.ok) {
			const message = await response.text().catch(() => "");
			throw new Error(message || "Direct upload failed");
		}

		retryAttempt = 0;
		onProgress(file.size, file.size);
		const contentType = response.headers.get("content-type") || "";
		if (contentType.includes("application/json")) {
			const metadata: unknown = await response.json();
			if (isUploadMetadata(metadata)) return metadata;
		}
		return {};
	}

	return {};
};

function isUploadMetadata(value: unknown): value is UploadMetadata {
	return (
		value !== null &&
		typeof value === "object" &&
		!Array.isArray(value) &&
		(!("generation" in value) ||
			typeof value.generation === "string" ||
			typeof value.generation === "number") &&
		(!("name" in value) || typeof value.name === "string")
	);
}

export const directUpload = {
	route: directUploadRoute,
	createSession: createDirectUploadSession,
	upload: uploadDirectFile,
};
