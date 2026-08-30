/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=bdbb928b';
import './connectivity.js?v=bdbb928b';

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason metadata lookup is private analytics payload plumbing
 */
const meta = (name) =>
	document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") || "";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason CSRF token lookup is private analytics request plumbing
 */
const token = () => document.getElementById("token")?.value || "";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason analytics enablement is owned by the shared manager contract
 */
const analyticsEnabled = () => meta("analytics") === "true";

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason browser navigation metadata is private analytics payload plumbing
 */
const navigationType = () => {
	const navigation = performance.getEntriesByType?.("navigation")?.[0];
	return navigation?.type || "";
};

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason analytics title lookup prefers entity view headers without requiring every route to add metadata
 */
const pageTitle = () =>
	meta("analytics-title") ||
	document
		.querySelector("[lp-view] [data-nav='view'] [data-role='title']")
		?.textContent?.trim() ||
	document.title.trim();

/**
 * @testable false
 * @covered-by src/script/shared/analytics.mjs::AnalyticsManager
 * @reason view payload construction is owned by the shared analytics manager
 */
const viewData = (action) => {
	const view = document.querySelector("[lp-view]");
	return {
		action,
		path: window.location.pathname,
		query: window.location.search || "",
		page_title: pageTitle(),
		view_kind: view?.dataset.kind || "",
		entity_key: view?.dataset.key || "",
		entity_hash: view?.dataset.hash || "",
		index: view?.dataset.index || "",
		public_id: meta("analytics-public-id"),
		referrer: document.referrer || "",
		navigation_type: navigationType(),
	};
};

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
 * @pair analytics:page-load
 */
class AnalyticsManager {
	get enabled() {
		return analyticsEnabled();
	}

	get mode() {
		return meta("mode");
	}

	async tag(action, payload = {}) {
		if (!this.enabled) return;

		const path = payload.path || window.location.pathname;
		if (
			["view", "public_view"].includes(action) &&
			path.startsWith("/analytics")
		) {
			return;
		}

		try {
			const body = JSON.stringify({ ...payload, action, path });
			const send = () =>
				fetch("/analytics/track", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"X-CSRFToken": token(),
						"X-Lagniappe-Request": "true",
					},
					credentials: "include",
					keepalive: true,
					body,
				});
			const response = await send();
			if (request.csrfFailed(response) && (await request.token())) {
				await send();
			}
		} catch {
			// Analytics must never affect the page using it.
		}
	}

	view() {
		const action = meta("analytics-action") || "view";
		this.tag(action, viewData(action));
	}
}

const analytics = new AnalyticsManager();

export { analytics };
