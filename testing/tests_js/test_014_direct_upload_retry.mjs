import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

const cloneHeaders = (headers) =>
	headers instanceof Headers
		? Object.fromEntries(headers.entries())
		: { ...(headers || {}) };

async function setupDirectUpload(t) {
	createBrowser(t, { formData: "native", url: "https://app.example.test/" });
	const fetchCalls = [];
	const progress = [];
	let post = async () => ({ ok: true });
	const fetchImpl = async (_url, config = {}) => {
		const headers = cloneHeaders(config.headers);
		fetchCalls.push({
			body: config.body,
			headers,
			method: config.method || "GET",
		});
		const contentRange = headers["Content-Range"];
		if (contentRange === "bytes 0-3/12") {
			return new Response("", {
				status: 308,
				headers: { Range: "bytes=0-3" },
			});
		}
		if (contentRange === "bytes 4-7/12") {
			throw new TypeError("connection termination");
		}
		if (contentRange === "bytes */12") {
			return new Response("", {
				status: 308,
				headers: { Range: "bytes=0-7" },
			});
		}
		if (contentRange === "bytes 8-11/12") {
			return new Response(
				JSON.stringify({ generation: "3", name: "tmp/uploads/file.txt" }),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}
		throw new Error(`Unexpected upload request: ${contentRange}`);
	};
	t.mock.method(globalThis, "fetch", fetchImpl);
	t.mock.method(window, "fetch", fetchImpl);
	const { directUpload } = await esmock.strict(
		"../../src/script/shared/directUpload.mjs",
		{
			"../../src/script/shared/request.mjs": {
				request: {
					post: (...args) => post(...args),
				},
			},
		},
	);
	return {
		directUpload,
		fetchCalls,
		progress,
		setPost(callback) {
			post = callback;
		},
	};
}

async function setupBaseUpload(t) {
	createBrowser(t, { formData: "native", url: "https://app.example.test/" });
	const errors = [];
	const directUpload = {};
	const { BaseUpload } = await esmock.strict(
		"../../src/script/elements/base/baseUpload.mjs",
		{
			"../../src/script/forms/controller.mjs": {
				FormController: class {},
			},
			"../../src/script/shared/directUpload.mjs": { directUpload },
			"../../src/script/elements/upload.mjs": { uploadElement: {} },
		},
	);
	return { BaseUpload, directUpload, errors };
}

/** @matrix direct-upload : resumable-range retry */
test("test_direct_upload_resumes_after_network_reset", async (t) => {
	const context = await setupDirectUpload(t);
	const file = new File(["abcdefghijkl"], "file.txt", { type: "text/plain" });
	const metadata = await context.directUpload.upload({
		file,
		sessionUrl: "https://storage.example.test/session",
		chunkSize: 4,
		retryDelay: 0,
		onProgress: (loaded, total) => context.progress.push([loaded, total]),
	});
	assert.deepEqual(
		context.fetchCalls.map((call) => call.headers["Content-Range"]),
		["bytes 0-3/12", "bytes 4-7/12", "bytes */12", "bytes 8-11/12"],
	);
	assert.deepEqual(metadata, {
		generation: "3",
		name: "tmp/uploads/file.txt",
	});
	assert.deepEqual(
		context.progress.map(([loaded]) => loaded),
		[4, 8, 12],
	);
});

/** @matrix direct-upload forms : retryable-action persistent-error */
test("test_builder_direct_upload_failure_preserves_owner_page", async (t) => {
	const context = await setupDirectUpload(t);
	context.setPost(async (route, _body, options) => {
		assert.equal(route, "/forms/draft/update/direct-upload");
		assert.equal(options.replaceErrorPage, false);
		return { ok: false, error: "Editing permission changed" };
	});
	await assert.rejects(
		context.directUpload.createSession({
			route: "/forms/draft/update",
			inputName: "draft-image-local",
			replaceErrorPage: false,
			file: new File(["image"], "image.png", { type: "image/png" }),
		}),
		/Editing permission changed/,
	);
});

/** @matrix direct-upload : compatibility multipart-fallback single-file */
test("test_single_file_keeps_compatibility_multipart_fallback", async (t) => {
	const { BaseUpload, directUpload, errors } = await setupBaseUpload(t);
	const file = new File(["one"], "one.txt", { type: "text/plain" });
	const instance = new BaseUpload({});
	instance.inputName = "upload";
	instance.route = "/files/upload";
	instance.fileInput = { element: { files: [file] } };
	instance.showError = (message) => errors.push(message);
	directUpload.createSession = async () => {
		throw new Error("session unavailable");
	};
	assert.equal(await instance.prepareSubmit(), true);
	assert.deepEqual(errors, []);
	assert.deepEqual(instance.directUploads, []);
});

/** @matrix upload : directory-rejection drag-drop */
test("test_directory_drop_is_rejected_before_file_processing", async (t) => {
	const { BaseUpload, errors } = await setupBaseUpload(t);
	let dropHandler;
	const instance = new BaseUpload({});
	instance.dropzone = {
		element: {
			addEventListener(name, handler) {
				if (name === "drop") dropHandler = handler;
			},
		},
	};
	instance.showError = (message) => errors.push(message);
	let processed = false;
	instance._processNewFiles = async () => {
		processed = true;
	};
	instance._initDropZone();
	await dropHandler({
		preventDefault() {},
		dataTransfer: {
			files: [{ name: "documents", size: 0, type: "" }],
			items: [
				{
					kind: "file",
					webkitGetAsEntry: () => ({ isDirectory: true }),
				},
			],
		},
	});
	assert.equal(processed, false);
	assert.deepEqual(errors, ["Only individual files are supported"]);
});

/** @pair upload:async-file-snapshot */
test("test_file_drop_survives_async_directory_check", async (t) => {
	const { BaseUpload } = await setupBaseUpload(t);
	let dropHandler;
	const instance = new BaseUpload({});
	instance.dropzone = {
		element: {
			addEventListener(name, handler) {
				if (name === "drop") dropHandler = handler;
			},
		},
	};
	const received = [];
	instance._processNewFiles = async (files) => received.push(...files);
	instance._initDropZone();
	const file = new File(["evidence"], "evidence.txt", { type: "text/plain" });
	let reads = 0;
	await dropHandler({
		preventDefault() {},
		dataTransfer: {
			get files() {
				return reads++ === 0 ? [file] : [];
			},
			items: [{
				kind: "file",
				async getAsFileSystemHandle() {
					return { kind: "file" };
				},
			}],
		},
	});
	assert.deepEqual(received, [file]);
});

/** @matrix direct-upload : aggregate-limit multipart-fallback partial-resume */
test("test_large_multi_file_retry_preserves_completed_direct_uploads", async (t) => {
	const { BaseUpload, directUpload, errors } = await setupBaseUpload(t);
	const files = Array.from(
		{ length: 6 },
		(_, index) =>
			new File([`file-${index}`], `file-${index}.txt`, {
				type: "text/plain",
				lastModified: index + 1,
			}),
	);
	const instance = new BaseUpload({});
	instance.inputName = "tool-files";
	instance.route = "/tools/organize";
	instance.fileInput = { element: { files } };
	instance.showError = (message) => errors.push(message);
	let sessionCalls = 0;
	let uploadCalls = 0;
	let failThird = true;
	directUpload.createSession = async ({ file }) => {
		sessionCalls += 1;
		return {
			chunk_size: 8,
			session_url: `https://storage.example.test/${file.name}`,
			token: `token:${file.name}`,
		};
	};
	directUpload.upload = async ({ file }) => {
		uploadCalls += 1;
		if (failThird && file.name === "file-2.txt") {
			throw new Error("temporary upload failure");
		}
		return {
			generation: `${uploadCalls}`,
			name: `tmp/uploads/${file.name}`,
		};
	};
	assert.equal(await instance.prepareSubmit(), false);
	assert.equal(instance.directUploads.length, 2);
	assert.match(errors[0], /file-2\.txt/);
	failThird = false;
	assert.equal(await instance.prepareSubmit(), true);
	assert.equal(instance.directUploads.length, 6);
	assert.equal(sessionCalls, 7);
	const submitted = new Map([["tool-files", "multipart"]]);
	const data = {
		delete: (key) => submitted.delete(key),
		set: (key, value) => submitted.set(key, value),
	};
	instance.applyDirectUploads(data);
	const records = JSON.parse(submitted.get("direct_uploads"));
	assert.equal(records.length, 6);
	assert.equal(
		records.some((record) => "_fileSignature" in record),
		false,
	);
	assert.equal(submitted.has("tool-files"), false);
});
