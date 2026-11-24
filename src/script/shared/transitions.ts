import { captureError, isSkippedViewTransitionError } from "./errors.ts";

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

let transitionQueue = Promise.resolve();
let transitionDepth = 0;
let pendingTransitionBatch = null;

const reportSlowCommit = (label, started) => {
	if (typeof performance === "undefined" || !performance.now) return;
	if (typeof __BUILD_ID__ !== "undefined") return;

	const duration = performance.now() - started;
	if (duration <= 50) return;
	console.warn(
		`View transition commit "${label}" took ${duration.toFixed(1)}ms.`,
	);
};

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

const executeTransition = async (entries) => {
	let batch = null;
	let updateStarted = false;
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
