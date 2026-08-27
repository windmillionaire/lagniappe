/*! Third-party licenses: /third-party-licenses.txt */
/**
 * @testable false
 * @covered-by src/script/shared/publicShare.mjs::copyPublicUrl
 * @reason legacy clipboard fallback is exercised through the public copy API
 */
function legacyCopy(url, documentRef) {
	const textarea = documentRef.createElement("textarea");
	textarea.value = url;
	textarea.setAttribute("readonly", "");
	textarea.style.position = "fixed";
	textarea.style.opacity = "0";
	documentRef.body.append(textarea);
	textarea.select();
	let copied = false;
	try {
		copied = documentRef.execCommand("copy");
	} finally {
		textarea.remove();
	}
	return copied;
}

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.py::test_public_share_uses_native_api_and_clipboard_fallbacks
 * @matrix public-pages : clipboard fallback sharing
 */
async function copyPublicUrl(url, root = document) {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(url);
			return true;
		}
	} catch {
		// Continue through the synchronous fallback when clipboard permission fails.
	}
	return legacyCopy(url, root);
}

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.py::test_public_share_uses_native_api_and_clipboard_fallbacks
 * @matrix public-pages : abort clipboard native-share selectable-url
 */
async function sharePublicPage(button, root = document) {
	const container = button.closest('[data-role="public-share"]');
	const status = container?.querySelector('[data-role="share-status"]');
	const fallback = container?.querySelector('[data-role="share-fallback"]');
	const input = fallback?.querySelector('[data-role="share-url"]');
	const payload = {
		title: button.dataset.shareTitle,
		text: button.dataset.shareText,
		url: button.dataset.shareUrl,
	};

	if (typeof navigator.share === "function") {
		let supported = true;
		try {
			supported =
				typeof navigator.canShare !== "function" || navigator.canShare(payload);
		} catch {
			supported = false;
		}
		if (supported) {
			try {
				await navigator.share(payload);
				return;
			} catch (error) {
				if (error?.name === "AbortError") return;
			}
		}
	}

	if (await copyPublicUrl(payload.url, root)) {
		if (status) status.textContent = "Link copied";
		return;
	}
	if (fallback && input) {
		fallback.classList.remove("hidden");
		input.focus();
		input.select();
		if (status) status.textContent = "Select and copy the page link";
	}
}

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.py::test_public_share_initialization_binds_one_click_handler
 * @matrix public-pages : initialization sharing
 */
function initializePublicSharing(root = document) {
	const button = root.querySelector('[data-role="share-button"]');
	if (!button || button.dataset.shareInitialized === "true") return;
	button.dataset.shareInitialized = "true";
	button.addEventListener("click", () => void sharePublicPage(button, root));
}

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.py::test_public_share_entry_initializes_once
 * @matrix public-pages : entrypoint initialization
 */
function startPublicPage() {
	initializePublicSharing();
}

startPublicPage();

export { startPublicPage };
