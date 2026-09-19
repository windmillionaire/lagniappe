import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

function replace(t, target, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(target, name);
	Object.defineProperty(target, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(target, name, descriptor);
		else delete target[name];
	});
}

const flushTransitions = () => new Promise((resolve) => setImmediate(resolve));

function setupSharingBrowser(t) {
	createBrowser(t, {
		html: `
			<section data-role="public-share">
				<button
					data-role="share-button"
					data-share-url="https://site.test/pages/public/id"
				>
					<span data-role="share-label">Share</span>
				</button>
				<p data-role="share-status"></p>
				<div data-role="share-fallback" class="hidden">
					<input data-role="share-url">
				</div>
			</section>
		`,
	});
	const native = [];
	const clipboard = [];
	replace(t, navigator, "canShare", () => true);
	replace(t, navigator, "share", async (payload) => native.push(payload));
	replace(t, navigator, "clipboard", {
		async writeText(value) {
			clipboard.push(value);
		},
	});
	return {
		button: document.querySelector("[data-role='share-button']"),
		clipboard,
		fallback: document.querySelector("[data-role='share-fallback']"),
		input: document.querySelector("[data-role='share-url']"),
		label: document.querySelector("[data-role='share-label']"),
		native,
		status: document.querySelector("[data-role='share-status']"),
	};
}

/** @matrix public-pages : entrypoint initialization */
test("test_public_share_entry_initializes_once", async (t) => {
	const initializePublicSharing = t.mock.fn();
	await esmock.strict("../../src/script/public.mjs", {
		"../../src/script/shared/publicShare.mjs": { initializePublicSharing },
	});
	assert.equal(
		initializePublicSharing.mock.callCount(),
		1,
		"Public sharing entry did not initialize once",
	);
});

/**
 * @matrix public-pages : abort clipboard fallback native-share selectable-url sharing
 */
test("test_public_share_uses_native_api_and_clipboard_fallbacks", async (t) => {
	const env = setupSharingBrowser(t);
	const { sharePublicPage } = await import(
		"../../src/script/shared/publicShare.mjs"
	);
	let legacy = 0;
	replace(t, document, "execCommand", () => {
		legacy += 1;
		return true;
	});
	let selected = 0;
	t.mock.method(env.input, "select", () => {
		selected += 1;
	});

	await sharePublicPage(env.button, document);
	await flushTransitions();
	assert.equal(env.native.length, 1, "Native share was not preferred");
	assert.equal(env.clipboard.length, 0, "Clipboard ran before native share");
	assert.deepEqual(
		env.native[0],
		{ url: env.button.dataset.shareUrl },
		"Native share included content other than the public URL",
	);
	assert.equal(env.label.textContent, "Shared");
	assert.equal(env.status.textContent, "Page shared");

	navigator.share = async () => {
		throw new Error("unavailable");
	};
	await sharePublicPage(env.button, document);
	await flushTransitions();
	assert.deepEqual(env.clipboard, [env.button.dataset.shareUrl]);
	assert.equal(env.status.textContent, "Link copied");
	assert.equal(env.label.textContent, "Copied");

	navigator.share = async () => {
		const error = new Error("cancelled");
		error.name = "AbortError";
		throw error;
	};
	env.status.textContent = "";
	await sharePublicPage(env.button, document);
	await flushTransitions();
	assert.equal(
		env.clipboard.length,
		1,
		"Cancelled native sharing copied unexpectedly",
	);
	assert.equal(
		env.status.textContent,
		"",
		"Cancelled native sharing reported unexpectedly",
	);
	assert.equal(env.label.textContent, "Share");

	navigator.share = undefined;
	navigator.clipboard.writeText = async () => {
		throw new Error("denied");
	};
	await sharePublicPage(env.button, document);
	await flushTransitions();
	assert.equal(legacy, 1, "Legacy copy fallback did not run");
	assert.equal(env.status.textContent, "Link copied");
	assert.equal(env.label.textContent, "Copied");

	document.execCommand = () => false;
	await sharePublicPage(env.button, document);
	await flushTransitions();
	assert.equal(
		env.fallback.classList.contains("hidden"),
		false,
		"Selectable URL fallback was not revealed",
	);
	assert.equal(selected, 1, "Selectable URL fallback was not selected");
	assert.equal(env.label.textContent, "Copy link");
});

/** @matrix public-pages : initialization sharing */
test("test_public_share_initialization_binds_one_click_handler", async (t) => {
	const env = setupSharingBrowser(t);
	const { initializePublicSharing } = await import(
		"../../src/script/shared/publicShare.mjs"
	);
	initializePublicSharing(document);
	initializePublicSharing(document);
	assert.equal(env.button.dataset.shareInitialized, "true");
	env.button.click();
	await flushTransitions();
	assert.equal(
		env.native.length,
		1,
		"Sharing initialized more than one click handler",
	);
});
