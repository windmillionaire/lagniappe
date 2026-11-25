import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

function installMatchMedia() {
	window.matchMedia = () => ({
		matches: false,
		addEventListener() {},
		removeEventListener() {},
	});
}

test("test_page_deep_link_opens_user_settings_once_and_cleans_tab_param", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/user-page?tab=user-settings",
		html: `
			<div lp-view data-key="user-page" data-hash="hash-user" data-has-image="false">
				<div id="info" lp-component data-tab="true" data-default="PageInfo">
					<form data-widget="UserSettings" data-visible="false"></form>
				</div>
			</div>
		`,
	});
	installMatchMedia();

	const { default: Page } = await import("../../src/script/views/page.ts");
	const root = document.querySelector("[lp-view]");
	const page = new Page(root);

	try {
		assert.equal(page._requestedUserSettings(), true);
		page._pendingTabWidget = { tabId: "info", widget: "UserSettings" };
		assert.equal(page._initialTabId(), "info");
		assert.equal(page._initialTabWidget("info"), "UserSettings");
		// Consumed after the first activation so later layouts/resizes use default.
		assert.equal(page._initialTabWidget("info"), "default");

		page._replaceInitialTabUrl();
		assert.equal(window.location.pathname, "/pages/user-page");
		assert.equal(window.location.search, "");
	} finally {
		page.destroy();
	}
});

test("test_page_deep_link_ignores_user_settings_when_form_is_absent", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/other-page?tab=user-settings",
		html: `
			<div lp-view data-key="other-page" data-hash="hash-other" data-has-image="false">
				<div id="info" lp-component data-tab="true" data-default="PageInfo"></div>
			</div>
		`,
	});
	installMatchMedia();

	const { default: Page } = await import("../../src/script/views/page.ts");
	const root = document.querySelector("[lp-view]");
	const page = new Page(root);

	try {
		assert.equal(page._requestedUserSettings(), false);
		assert.equal(page._initialTabWidget("info"), "default");
	} finally {
		page.destroy();
	}
});
