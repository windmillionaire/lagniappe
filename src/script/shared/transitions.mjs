import { captureError, isSkippedViewTransitionError } from "./errors";

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason no-transition fallback is part of the transition wrapper
 */
const runWithoutTransition = async (callback, label = "unlabeled") => {
	try {
		const result = callback();
		if (result?.then) {
			captureError(
				new TypeError(
					`View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`,
				),
			);
			await result;
		}
		return true;
	} catch (error) {
		captureError(error);
		return false;
	}
};

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason transition queue prevents concurrent View Transitions API aborts
 */
let transitionQueue = Promise.resolve();
let transitionDepth = 0;
let pendingTransitionBatch = null;

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason development-only timing diagnostic is part of the transition wrapper
 */
const reportSlowCommit = (label, started) => {
	if (typeof performance === "undefined" || !performance.now) return;
	if (typeof __BUILD_ID__ !== "undefined") return;

	const duration = performance.now() - started;
	if (duration <= 50) return;
	console.warn(
		`View transition commit "${label}" took ${duration.toFixed(1)}ms.`,
	);
};

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason exact-once commit execution is exercised through the public transition wrapper
 */
const runCommit = (callback, label) => {
	const started =
		typeof performance !== "undefined" && performance.now
			? performance.now()
			: null;
	try {
		const result = callback();
		if (!result?.then) {
			if (started !== null) reportSlowCommit(label, started);
			return true;
		}

		captureError(
			new TypeError(
				`View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`,
			),
		);
		return Promise.resolve(result)
			.then(() => true)
			.catch((error) => {
				captureError(error);
				return false;
			})
			.finally(() => {
				if (started !== null) reportSlowCommit(label, started);
			});
	} catch (error) {
		captureError(error);
		if (started !== null) reportSlowCommit(label, started);
		return false;
	}
};

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason same-turn commit batching is exercised through the public transition wrapper
 */
const runTransitionBatch = (entries) => {
	const results = new Array(entries.length).fill(false);
	const pending = [];

	transitionDepth += 1;
	entries.forEach(({ callback, label }, index) => {
		const result = runCommit(callback, label);
		if (result?.then) {
			pending.push(
				result.then((successful) => {
					results[index] = successful;
				}),
			);
		} else {
			results[index] = result;
		}
	});

	if (!pending.length) {
		transitionDepth -= 1;
		return { results, pending: null };
	}

	return {
		results,
		pending: Promise.all(pending).finally(() => {
			transitionDepth -= 1;
		}),
	};
};

/**
 * @testable false
 * @covered-by src/script/shared/transitions.mjs::withTransition
 * @reason single-transition runner is private to the queued wrapper
 */
const executeTransition = async (entries) => {
	let batch = null;
	let updateStarted = false;
	/**
	 * @testable false
	 * @covered-by src/script/shared/transitions.mjs::withTransition
	 * @reason browser update callback is private transition-wrapper plumbing
	 */
	const update = () => {
		updateStarted = true;
		batch = runTransitionBatch(entries);
		return batch.pending || undefined;
	};

	let transition = null;
	if (document.startViewTransition) {
		try {
			transition = document.startViewTransition(update);
		} catch (error) {
			if (!isSkippedViewTransitionError(error)) captureError(error);
		}
	}

	if (!transition) {
		if (!updateStarted) update();
		if (batch?.pending) await batch.pending;
		entries.forEach((entry, index) => {
			entry.resolve(batch.results[index]);
		});
		return;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/transitions.mjs::withTransition
	 * @reason transition promise observation is exercised through public error handling
	 */
	const observeTransitionError = (error) => {
		if (!isSkippedViewTransitionError(error)) captureError(error);
	};
	void transition.ready?.catch(observeTransitionError);

	const updateDone = transition.updateCallbackDone || transition.finished;
	if (transition.finished !== updateDone) {
		void transition.finished?.catch(observeTransitionError);
	}
	try {
		await updateDone;
	} catch (error) {
		observeTransitionError(error);
	}

	entries.forEach((entry, index) => {
		entry.resolve(batch?.results[index] ?? false);
	});
};

/**
 * @testable true
 * @tests tests_js/test_011_view_transitions_frontend.py::test_nested_transition_joins_active_transition_without_error_report
 * @tests tests_js/test_011_view_transitions_frontend.py::test_transition_resolves_after_update_without_waiting_for_animation
 * @tests tests_js/test_011_view_transitions_frontend.py::test_same_turn_commits_share_one_transition_and_run_once
 * @tests tests_js/test_011_view_transitions_frontend.py::test_ready_rejection_does_not_replay_commit
 * @matrix view-transition : animation-lifecycle coalescing error-reporting exact-once nested-callback queueing ready-rejection update-completion
 */
export const withTransition = (callback, { label = "unlabeled" } = {}) => {
	if (transitionDepth > 0) {
		// Nested callers are already inside the browser's transition update.
		return runWithoutTransition(callback, label);
	}

	return new Promise((resolve) => {
		if (!pendingTransitionBatch) {
			pendingTransitionBatch = [];
			queueMicrotask(() => {
				const entries = pendingTransitionBatch;
				pendingTransitionBatch = null;
				transitionQueue = transitionQueue
					.then(() => executeTransition(entries))
					.catch((error) => {
						captureError(error);
						entries.forEach((entry) => {
							entry.resolve(false);
						});
					});
			});
		}
		pendingTransitionBatch.push({ callback, label, resolve });
	});
};
