import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

/**
 * @matrix notifications : accessible-state badge cold-seed redis-projection response-header
 */
test("test_notification_state_updates_badge_and_reports_cache_miss", async (t) => {
	createBrowser(t, {
		html: `
			<button data-role="notifications" data-visible="false" aria-hidden="true">
				<span data-role="notification-count">0</span>
			</button>
		`,
	});
	const captured = [];
	const captureError = t.mock.fn((...args) => captured.push(args));
	const { applyNotificationState, applyNotificationStateHeader } =
		await esmock.strict("../../src/script/shared/notificationState.mjs", {
			"../../src/script/shared/errors.mjs": { captureError },
		});
	const events = [];
	window.addEventListener("notification-state", (event) => events.push(event));
	const button = document.querySelector("[data-role='notifications']");
	const count = document.querySelector("[data-role='notification-count']");

	const miss = applyNotificationState(
		'{"generation":null,"revision":null,"count":null}',
	);
	assert.equal(miss?.miss, true, "Cache miss was not reported");
	assert.equal(
		button.dataset.visible,
		"false",
		"Cache miss changed the last rendered badge visibility",
	);
	assert.equal(
		count.textContent,
		"0",
		"Cache miss changed the last rendered badge count",
	);

	const applied = applyNotificationStateHeader(
		new Headers({
			"X-Lagniappe-Notification-State":
				'{"generation":"generation-a","revision":4,"count":3}',
		}),
	);
	assert.equal(applied?.miss, false);
	assert.equal(window.__NOTIFICATION_STATE__?.revision, 4);
	assert.equal(count.textContent, "3");
	assert.equal(button.dataset.visible, "true");
	assert.equal(button.getAttribute("aria-hidden"), "false");
	assert.equal(button.tabIndex, 0);
	assert.equal(button.getAttribute("aria-label"), "Notifications: 3");
	assert.equal(
		events.length,
		2,
		"Notification state was not published for miss and warm states",
	);
	assert.equal(
		events.at(-1).detail.count,
		3,
		"Warm notification count was not published to lazy consumers",
	);

	const before = window.__NOTIFICATION_STATE__;
	assert.equal(applyNotificationState('{"revision":"bad"}'), null);
	assert.equal(
		window.__NOTIFICATION_STATE__,
		before,
		"Invalid notification state replaced the accepted cursor",
	);
	applyNotificationState('{"revision":"still-bad"}');
	assert.equal(
		captured.length,
		1,
		"Invalid notification state was not captured exactly once",
	);
	assert.equal(captured[0][2]?.context, "notification-state-contract");
});
