/*! Third-party licenses: /third-party-licenses.txt */
const NOTIFICATION_STATE_HEADER = "X-Lagniappe-Notification-State";

/**
 * @testable false
 * @covered-by src/script/shared/notificationState.mjs::applyNotificationState
 * @reason input normalization is exercised through the public state publisher
 */
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
 * @testable true
 * @tests tests_js/test_036_notification_state.py::test_notification_state_updates_badge_and_reports_cache_miss
 * @pairs notifications:badge notifications:redis-projection notifications:cold-seed
 */
const applyNotificationState = (raw) => {
	const state = _normalized(raw);
	if (!state) return null;
	window.__NOTIFICATION_STATE__ = state;

	if (!state.miss) {
		const button = document.querySelector("[data-role='notifications']");
		const count = document.querySelector("[data-role='notification-count']");
		if (count) count.textContent = String(state.count);
		if (button) {
			button.dataset.visible = state.count > 0 ? "true" : "false";
			button.setAttribute("aria-label", `Notifications: ${state.count}`);
		}
	}

	window.dispatchEvent(
		new CustomEvent("notification-state", { detail: { ...state } }),
	);
	return state;
};

/**
 * @testable true
 * @tests tests_js/test_036_notification_state.py::test_notification_state_updates_badge_and_reports_cache_miss
 * @pair notifications:response-header
 */
const applyNotificationStateHeader = (headers) => {
	const raw = headers?.get?.(NOTIFICATION_STATE_HEADER);
	return raw ? applyNotificationState(raw) : null;
};

export { applyNotificationStateHeader as a };
