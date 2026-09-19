import { request } from "./request.mjs";

const DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024;
const DEFAULT_DIRECT_UPLOAD_RETRIES = 3;
const DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS = 500;
const RESUMABLE_UPLOAD_INCOMPLETE = 308;
const RETRYABLE_DIRECT_UPLOAD_STATUSES = new Set([
	408, 429, 500, 502, 503, 504,
]);

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::createDirectUploadSession
 * @reason route derivation is exercised through session creation
 */
const directUploadRoute = (route) => {
	if (!route) return null;

	const url = new URL(route, window.location.origin);
	url.pathname = `${url.pathname.replace(/\/$/, "")}/direct-upload`;
	return `${url.pathname}${url.search}`;
};

/**
 * @testable true
 * @tests tests_js/test_014_direct_upload_retry.mjs::test_builder_direct_upload_failure_preserves_owner_page
 * @matrix direct-upload forms : retryable-action persistent-error
 */
const createDirectUploadSession = async ({
	route,
	file,
	inputName,
	replaceErrorPage = true,
}) => {
	const response = await request.post(
		directUploadRoute(route),
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
	return response;
};

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason small timing helper is exercised through the retry contract
 */
const directUploadRetryDelay = (attempt, baseDelay) =>
	baseDelay * 2 ** Math.max(0, attempt - 1);

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason sleep wrapper lets retry tests use a zero delay
 */
const wait = (delayMs) =>
	delayMs > 0
		? new Promise((resolve) => setTimeout(resolve, delayMs))
		: Promise.resolve();

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason GCS resumable uploads report persisted bytes through Range headers
 */
const directUploadOffset = (response) => {
	const range = response.headers.get("Range") || "";
	const match = /^bytes=0-(\d+)$/i.exec(range.trim());
	return match ? Number.parseInt(match[1], 10) + 1 : 0;
};

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason resumable upload status probing is part of retry recovery
 */
const directUploadStatusOffset = async ({ file, sessionUrl }) => {
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

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason retryability rules are shared by thrown fetch failures and storage 5xxs
 */
const shouldRetryDirectUpload = (response) =>
	RETRYABLE_DIRECT_UPLOAD_STATUSES.has(response.status);

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason recovery needs to sync the browser offset with the storage session
 */
const resumeDirectUpload = async ({
	file,
	sessionUrl,
	attempt,
	retries,
	retryDelay,
	onProgress,
}) => {
	let statusAttempt = attempt;
	let lastError = null;

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

/**
 * @testable false
 * @covered-by src/script/shared/directUpload.mjs::uploadDirectFile
 * @reason browser-to-GCS chunk PUT is exercised through the retry contract
 */
const directUploadChunk = ({ file, sessionUrl, offset, end }) =>
	fetch(sessionUrl, {
		method: "PUT",
		headers: {
			"Content-Type": file.type || "application/octet-stream",
			"Content-Range": `bytes ${offset}-${end}/${file.size}`,
		},
		body: file.slice(offset, end + 1),
	});

/**
 * @testable true
 * @tests tests_js/test_014_direct_upload_retry.mjs::test_direct_upload_resumes_after_network_reset
 * @matrix direct-upload : resumable-range retry
 */
const uploadDirectFile = async ({
	file,
	sessionUrl,
	chunkSize = DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE,
	retries = DEFAULT_DIRECT_UPLOAD_RETRIES,
	retryDelay = DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS,
	onProgress = () => {},
}) => {
	if (!file.size) return {};

	let offset = 0;
	let retryAttempt = 0;
	while (offset < file.size) {
		const end = Math.min(offset + chunkSize, file.size) - 1;
		let response;

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
			return (await response.json()) || {};
		}
		return {};
	}

	return {};
};

export const directUpload = {
	route: directUploadRoute,
	createSession: createDirectUploadSession,
	upload: uploadDirectFile,
};
