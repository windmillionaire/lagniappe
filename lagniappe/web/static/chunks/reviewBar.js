/*! Third-party licenses: /third-party-licenses.txt */
import { c as captureError } from './foundation.js?v=b518b165';

/**
 * @testable true
 * @pair forms:autofill-completion-review
 */
function currentReviewOperation(widget, incoming) {
	const current = widget.reviewState?.operation;
	if (current?.key === incoming?.key)
		return Number(current?.revision) > Number(incoming?.revision)
			? current
			: incoming;
	// A response captured before a new run started cannot replace its controls.
	return current?.type === "autofill" &&
		!current.terminal &&
		incoming?.type !== "form-change" &&
		(!incoming || incoming.terminal)
		? current
		: incoming;
}

/**
 * One notification surface for operation progress, schema changes, and remote edits.
 * @testable true
 * @pair forms:submission-choice
 * @pair forms:autofill-completion-review
 * @pair form-migration:informational-notice
 */
function renderReviewBar(widget, operation = null) {
	const target = widget?.target;
	const marker = target?.querySelector?.("[lp-edited-marker]");
	if (!marker) return;
	const state =
		widget.reviewState ?? JSON.parse(target.dataset.formState || "{}");
	widget.reviewState = state;
	if (operation) state.operation = operation;
	operation = state.operation;
	const running = operation && !operation.terminal;
	const runningAutofill = running && operation.type === "autofill";
	const unresolvedReviews = (state.reviews ?? []).filter(
		(review) => !widget._reviewedOperations?.has(review.operation),
	);
	const awaitingNewAutofill =
		!state.stale_autofill &&
		operation?.type === "autofill" &&
		(running || (operation.terminal && operation.status === "succeeded")) &&
		!widget._reviewedOperations?.has(operation.key) &&
		!unresolvedReviews.some((review) => review.operation === operation.key);
	const reviews =
		runningAutofill || awaitingNewAutofill ? [] : unresolvedReviews;
	const migration =
		JSON.parse(target.dataset.migrationNotice || "[]").length > 0;
	const remote = marker._lp_edited_state?.response;
	const messages = [];
	if (reviews.length) messages.push("Autofill is complete.");
	if (migration || (remote && marker._lp_edited_state?.schemaChanged))
		messages.push("This form's fields have changed.");
	if (state.stale_autofill && !running)
		messages.push("Run Autofill again for new suggestions.");
	const remoteNotice =
		remote &&
		!runningAutofill &&
		!reviews.length &&
		!marker._lp_edited_state?.schemaChanged;
	if (remoteNotice) messages.push("Another user has edited this form.");
	const copy = marker.querySelector("[data-role='edited-message']");
	if (copy) {
		copy.textContent = messages.join(" ");
		copy.hidden = !messages.length;
	}
	const progress = marker.querySelector("[data-role='form-operation']");
	const showTerminal =
		operation?.terminal &&
		["failed", "cancelled", "superseded"].includes(operation.status);
	const awaitingReview =
		!state.stale_autofill &&
		operation?.terminal &&
		operation.status === "succeeded" &&
		operation.type === "autofill" &&
		!widget._reviewedOperations?.has(operation.key) &&
		!reviews.some((review) => review.operation === operation.key) &&
		!remoteNotice;
	if (progress) {
		progress.hidden =
			!running && (!!remoteNotice || (!showTerminal && !awaitingReview));
		progress.textContent = running
			? `${operation.type === "form-change" ? "Form update" : "Autofill"} is running · ${operation.phase_label || "Queued"} · ${Math.max(0, operation.elapsed_seconds || 0)}s${operation.retry_reason ? " · Retrying" : ""}`
			: showTerminal
				? operation.status === "cancelled"
					? "Autofill cancelled. Retry can reuse the uploaded file."
					: `Autofill ${operation.status}.${operation.error ? ` ${operation.error}` : ""} Saved answers were unchanged. Retry can reuse the uploaded file.`
				: awaitingReview
					? "Autofill is complete. Loading values to review…"
					: "";
	}
	const review = marker.querySelector("[data-role='edited-reset']");
	if (review) {
		review.hidden = !!runningAutofill || (!reviews.length && !remote);
		if ((reviews.length || remote) && !review.dataset?.reviewPending)
			review.textContent = "Review values";
	}
	const changes = marker.querySelector("[data-role='migration-changes']");
	if (changes) changes.hidden = !migration;
	const cancel = marker.querySelector("[data-role='autofill-cancel']");
	if (cancel) cancel.hidden = !running || !operation.can_cancel;
	const retry = marker.querySelector("[data-role='autofill-retry']");
	if (retry) {
		retry.hidden = !state.retry_operation || !!running;
		retry.disabled = !!widget._autofillRetryPending;
		retry.textContent = widget._autofillRetryPending
			? "Retrying…"
			: "Retry autofill";
	}
	for (const control of target.querySelectorAll(
		"[data-role='autofill-submit']",
	)) {
		control.disabled = !!running;
	}
	marker.dataset.visible =
		messages.length || running || showTerminal || awaitingReview
			? "true"
			: "false";
}

/**
 * @testable true
 * @tests tests_js/test_049_autofill_review.mjs::test_review_bar_cancel_uses_operation_identity
 * @pair ai:autofill
 */
function installReviewBar(widget) {
	widget._reviewBar?.destroy();
	if (widget.revisionPreview || !widget.target?.dataset.formState) return;
	widget.reviewState = JSON.parse(widget.target.dataset.formState);
	renderReviewBar(widget);
	/**
	 * @testable false
	 * @covered-by src/script/forms/reviewBar.mjs::installReviewBar
	 * @reason button actions belong to the installed notification bar
	 */
	const click = async (event) => {
		const button = event.target.closest(
			"[data-role='autofill-cancel'], [data-role='autofill-retry']",
		);
		if (!button) return;
		event.preventDefault();
		if (button.disabled) return;
		button.disabled = true;
		if (button.dataset.role === "autofill-cancel") {
			button.textContent = "Cancelling…";
			const progress = widget.target.querySelector(
				"[data-role='form-operation']",
			);
			if (progress) progress.textContent = "Cancellation requested…";
		}
		try {
			if (button.dataset.role === "autofill-cancel") {
				const operation = widget.reviewState?.operation;
				if (!operation?.can_cancel) return;
				const data = new FormData();
				data.set("operation-id", operation.operation_id);
				const { request } = await import('./foundation.js?v=b518b165').then(function (n) { return n.k; });
				const response = await request.post(
					`/tools/operations/${encodeURIComponent(operation.key)}/cancel`,
					data,
				);
				if (!response?.ok)
					throw new Error(
						response?.error || "Could not cancel autofill. Try again.",
					);
				if (response.status) {
					renderReviewBar(widget, response.status);
					const manager = await widget.view.ensureDeferredOperations?.();
					await manager?.receive(response.status);
				}
			} else {
				widget._autofillRetryPending = true;
				renderReviewBar(widget);
				widget._autofillRetry = widget.reviewState?.retry_operation;
				widget.target.dispatchEvent(
					new CustomEvent("submit", {
						bubbles: true,
						cancelable: true,
						detail: {
							role: "autofill-submit",
							update: true,
							onSettled: () => {
								widget._autofillRetryPending = false;
								renderReviewBar(widget);
							},
						},
					}),
				);
			}
		} catch (error) {
			if (button.dataset.role === "autofill-retry") {
				widget._autofillRetryPending = false;
				renderReviewBar(widget);
			}
			widget.component?.showError?.(error.message);
			captureError(error);
		} finally {
			if (button.dataset.role === "autofill-cancel")
				button.textContent = "Cancel autofill";
			if (button.dataset.role === "autofill-cancel") button.disabled = false;
		}
	};
	widget.target.addEventListener("click", click);
	const target = widget.target;
	widget._reviewBar = {
		destroy: () => target.removeEventListener("click", click),
	};
}

export { currentReviewOperation as c, installReviewBar as i, renderReviewBar as r };
