import { captureError, isSkippedViewTransitionError } from "./errors.ts";

type TransitionCommit = () => unknown;

interface TransitionEntry {
	callback: TransitionCommit;
	label: string;
	resolve: (committed: boolean) => void;
}

interface TransitionBatch {
	results: boolean[];
	pending: Promise<unknown> | null;
}

const hasThen = (result: unknown) =>
	Boolean((result as { then?: unknown } | null | undefined)?.then);

const runWithoutTransition = async (
	callback: TransitionCommit,
	label = "unlabeled",
) => {
	try {
		const result = callback();
		if (hasThen(result)) {
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
let pendingTransitionBatch: TransitionEntry[] | null = null;

const reportSlowCommit = (label: string, started: number) => {
	if (typeof performance === "undefined" || !performance.now) return;
	if (typeof __BUILD_ID__ !== "undefined") return;

	const duration = performance.now() - started;
	if (duration <= 50) return;
	console.warn(
		`View transition commit "${label}" took ${duration.toFixed(1)}ms.`,
	);
};

const runCommit = (callback: TransitionCommit, label: string) => {
	const started =
		typeof performance !== "undefined" && performance.now
			? performance.now()
			: null;
	try {
		const result = callback();
		if (!hasThen(result)) {
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

const runTransitionBatch = (entries: TransitionEntry[]): TransitionBatch => {
	const results = new Array<boolean>(entries.length).fill(false);
	const pending: Promise<void>[] = [];

	transitionDepth += 1;
	entries.forEach(({ callback, label }, index) => {
		const result = runCommit(callback, label);
		if (typeof result !== "boolean") {
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

const executeTransition = async (entries: TransitionEntry[]) => {
	const updateState: { started: boolean; batch: TransitionBatch | null } = {
		started: false,
		batch: null,
	};
	const update = () => {
		updateState.started = true;
		updateState.batch = runTransitionBatch(entries);
		return updateState.batch.pending || undefined;
	};

	let transition: ViewTransition | null = null;
	if (document.startViewTransition) {
		try {
			transition = document.startViewTransition(update);
		} catch (error) {
			if (!isSkippedViewTransitionError(error)) captureError(error);
		}
	}

	if (transition) {
		const observeTransitionError = (error: unknown) => {
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
	}

	if (!updateState.started) {
		update();
	}
	if (updateState.batch?.pending) {
		await updateState.batch.pending;
	}

	entries.forEach((entry, index) => {
		entry.resolve(updateState.batch?.results[index] ?? false);
	});
};

export const withTransition = (
	callback: TransitionCommit,
	{ label = "unlabeled" } = {},
): Promise<boolean> => {
	if (transitionDepth > 0) {
		// Nested callers are already inside the browser's transition update.
		return runWithoutTransition(callback, label);
	}

	return new Promise((resolve) => {
		if (!pendingTransitionBatch) {
			const entries: TransitionEntry[] = [];
			pendingTransitionBatch = entries;
			queueMicrotask(() => {
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
