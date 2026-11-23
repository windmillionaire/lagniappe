import { captureError } from "./errors.mjs";

export const NOTIFICATION_STATE_HEADER = "X-Lagniappe-Notification-State";

let invalidStateReported = false;

/**
 * Publish the notification badge's count, visibility, and accessible state as
 * one DOM commit.
 *
 */
export const renderNotificationBadge = (count) => {
	const normalized = Number.isInteger(Number(count)) ? Number(count) : 0;
	const button = document.querySelector("[data-role='notifications']");
	const countElement = document.querySelector(
		"[data-role='notification-count']",
	);
	if (countElement) countElement.textContent = String(normalized);
	if (!button) return normalized;

	button.dataset.visible = "true";
	button.setAttribute("aria-hidden", "false");
	button.setAttribute("aria-busy", "false");
	button.setAttribute("aria-label", `Notifications: ${normalized}`);
	button.tabIndex = 0;
	return normalized;
};

const _normalized = (raw) => {
	if (typeof raw === "string") {
		try {
			raw = JSON.parse(raw);
		} catch {
			return null;
		}
	}
	if (!raw || typeof raw !== "object") return null;
	if (raw.generation === null && raw.revision === null && raw.count === null) {
		return { generation: null, revision: null, count: null, miss: true };
	}
	if (
		typeof raw.generation !== "string" ||
		!raw.generation ||
		!Number.isInteger(raw.revision) ||
		raw.revision < 0 ||
		!Number.isInteger(raw.count) ||
		raw.count < 0
	) {
		return null;
	}
	return {
		generation: raw.generation,
		revision: raw.revision,
		count: raw.count,
		miss: false,
	};
};

/**
 * Publish compact notification state before the lazy menu module is loaded.
 *
 */
export const applyNotificationState = (raw) => {
	const state = _normalized(raw);
	if (!state) {
		if (raw !== null && raw !== undefined && !invalidStateReported) {
			invalidStateReported = true;
			captureError(
				new TypeError("Invalid notification state response."),
				null,
				{
					context: "notification-state-contract",
				},
			);
		}
		return null;
	}
	window.__NOTIFICATION_STATE__ = state;

	if (!state.miss) {
		renderNotificationBadge(state.count);
	}

	window.dispatchEvent(
		new CustomEvent("notification-state", { detail: { ...state } }),
	);
	return state;
};

export const applyNotificationStateHeader = (headers) => {
	const raw = headers?.get?.(NOTIFICATION_STATE_HEADER);
	return raw ? applyNotificationState(raw) : null;
};
