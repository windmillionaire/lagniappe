import { withTransition } from "./transitions.mjs";

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

export async function copyPublicUrl(url, root = document) {
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

function updateShareLabel(label, text) {
	if (!label) return;
	void withTransition(
		() => {
			label.textContent = text;
		},
		{ label: "public-share:feedback" },
	);
}

export async function sharePublicPage(button, root = document) {
	const container = button.closest('[data-role="public-share"]');
	const status = container?.querySelector('[data-role="share-status"]');
	const fallback = container?.querySelector('[data-role="share-fallback"]');
	const input = fallback?.querySelector('[data-role="share-url"]');
	const label = button.querySelector?.('[data-role="share-label"]');
	const payload = { url: button.dataset.shareUrl };
	if (status) status.textContent = "";

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
				updateShareLabel(label, "Shared");
				if (status) status.textContent = "Page shared";
				return;
			} catch (error) {
				if (error?.name === "AbortError") {
					updateShareLabel(label, "Share");
					return;
				}
			}
		}
	}

	if (await copyPublicUrl(payload.url, root)) {
		updateShareLabel(label, "Copied");
		if (status) status.textContent = "Link copied";
		return;
	}
	if (fallback && input) {
		fallback.classList.remove("hidden");
		input.focus();
		input.select();
		updateShareLabel(label, "Copy link");
		if (status) status.textContent = "Select and copy the page link";
	} else {
		updateShareLabel(label, "Share");
	}
}

export function initializePublicSharing(root = document) {
	const button = root.querySelector('[data-role="share-button"]');
	if (!button || button.dataset.shareInitialized === "true") return;
	button.dataset.shareInitialized = "true";
	button.addEventListener("click", () => void sharePublicPage(button, root));
}
