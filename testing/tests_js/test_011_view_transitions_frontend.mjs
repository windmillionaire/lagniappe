import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

async function setupTransitions(t, { skipped = () => false } = {}) {
	createBrowser(t);
	const capturedErrors = [];
	const captureError = t.mock.fn((...args) => capturedErrors.push(args));
	const { withTransition } = await esmock.strict(
		"../../src/script/shared/transitions.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError,
				isSkippedViewTransitionError: skipped,
			},
		},
	);
	return { capturedErrors, withTransition };
}

function installTransitionApi(t, implementation) {
	const transitionDocument = document;
	Object.defineProperty(transitionDocument, "startViewTransition", {
		configurable: true,
		value: implementation,
		writable: true,
	});
	t.after(() => {
		delete transitionDocument.startViewTransition;
	});
}

function createPendingAnimation(callback) {
	let finish;
	const updateCallbackDone = Promise.resolve().then(callback);
	const finished = new Promise((resolve) => {
		finish = resolve;
	});
	return {
		finish,
		transition: {
			finished,
			ready: Promise.resolve(),
			updateCallbackDone,
		},
	};
}

/** @matrix view-transition : error-reporting nested-callback */
test("test_nested_transition_joins_active_transition_without_error_report", async (t) => {
	const { capturedErrors, withTransition } = await setupTransitions(t);
	const events = [];
	let transitionStarts = 0;
	let finishTransition;
	installTransitionApi(t, (callback) => {
		transitionStarts += 1;
		const pending = createPendingAnimation(callback);
		finishTransition = pending.finish;
		return pending.transition;
	});

	const result = await withTransition(() => {
		events.push("outer-start");
		void withTransition(() => events.push("inner"));
		events.push("outer-end");
	});

	assert.equal(result, true);
	assert.equal(transitionStarts, 1);
	assert.equal(capturedErrors.length, 0);
	assert.deepEqual(events, ["outer-start", "inner", "outer-end"]);
	finishTransition();
});

/** @matrix view-transition : animation-lifecycle queueing update-completion */
test("test_transition_resolves_after_update_without_waiting_for_animation", async (t) => {
	const { withTransition } = await setupTransitions(t);
	const events = [];
	let finishTransition;
	installTransitionApi(t, (callback) => {
		const pending = createPendingAnimation(callback);
		finishTransition = pending.finish;
		return pending.transition;
	});

	let resolved = false;
	await withTransition(() => events.push("commit")).then(() => {
		resolved = true;
		events.push("resolved");
	});

	assert.equal(resolved, true);
	assert.deepEqual(events, ["commit", "resolved"]);
	finishTransition();
});

/** @matrix view-transition : coalescing exact-once */
test("test_same_turn_commits_share_one_transition_and_run_once", async (t) => {
	const { withTransition } = await setupTransitions(t);
	const events = [];
	let transitionStarts = 0;
	let finishTransition;
	installTransitionApi(t, (callback) => {
		transitionStarts += 1;
		const pending = createPendingAnimation(callback);
		finishTransition = pending.finish;
		return pending.transition;
	});

	const results = await Promise.all([
		withTransition(() => events.push("first")),
		withTransition(() => events.push("second")),
	]);

	assert.equal(transitionStarts, 1);
	assert.deepEqual(events, ["first", "second"]);
	assert.deepEqual(results, [true, true]);
	finishTransition();
});

/** @matrix view-transition : exact-once ready-rejection */
test("test_ready_rejection_does_not_replay_commit", async (t) => {
	const skipped = new Error("Transition was skipped");
	const { capturedErrors, withTransition } = await setupTransitions(t, {
		skipped: (error) => /skipped/i.test(error?.message || ""),
	});
	installTransitionApi(t, (callback) => ({
		finished: Promise.resolve(),
		ready: Promise.reject(skipped),
		updateCallbackDone: Promise.resolve().then(callback),
	}));
	let commits = 0;

	const result = await withTransition(() => {
		commits += 1;
	});
	await Promise.resolve();

	assert.equal(result, true);
	assert.equal(commits, 1);
	assert.equal(capturedErrors.length, 0);
});
