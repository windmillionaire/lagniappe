import { captureError } from "../shared/errors.mjs";

/**
 * One notification surface for operation progress, schema changes, and remote edits.
 * @testable true
 * @pair forms:submission-choice
 */
export function renderReviewBar(widget, operation = null) {
	const target = widget?.target;
	const marker = target?.querySelector?.("[lp-edited-marker]");
	if (!marker) return;
	const state =
		widget.reviewState ?? JSON.parse(target.dataset.formState || "{}");
	widget.reviewState = state;
	if (operation) state.operation = operation;
	operation = state.operation;
	const running = operation && !operation.terminal;
	const reviews = (state.reviews ?? []).filter(
		(review) => !widget._reviewedOperations?.has(review.operation),
	);
	const migration =
		state.migration &&
		widget._reviewedMigration !== JSON.stringify(state.migration);
	const remote = marker._lp_edited_state?.response;
	const messages = [];
	if (reviews.length) messages.push("Autofill is complete.");
	if (migration || marker._lp_edited_state?.schemaChanged)
		messages.push("This form's fields have changed.");
	if (remote && !reviews.length && !migration)
		messages.push("Another user has edited this form.");
	const copy = marker.querySelector("[data-role='edited-message']");
	if (copy) {
		copy.textContent = messages.join(" ");
		copy.hidden = !messages.length;
	}
	const progress = marker.querySelector("[data-role='form-operation']");
	const showTerminal =
		operation?.terminal &&
		["failed", "cancelled", "superseded"].includes(operation.status);
	if (progress) {
		progress.hidden = !running && !showTerminal;
		progress.textContent = running
			? `${operation.type === "form-change" ? "Form update" : "Autofill"} is running · ${operation.phase_label || "Queued"} · ${Math.max(0, operation.elapsed_seconds || 0)}s${operation.retry_reason ? " · Retrying" : ""}`
			: showTerminal
				? `Autofill ${operation.status}.${operation.error ? ` ${operation.error}` : ""} Your saved answers and files were kept.`
				: "";
	}
	const review = marker.querySelector("[data-role='edited-reset']");
	if (review) {
		review.hidden = !messages.length;
		if (reviews.length || migration) review.textContent = "Review values";
	}
	const cancel = marker.querySelector("[data-role='autofill-cancel']");
	if (cancel) cancel.hidden = !running || !operation.can_cancel;
	const retry = marker.querySelector("[data-role='autofill-retry']");
	if (retry) retry.hidden = !state.retry_operation || !!running;
	for (const control of target.querySelectorAll(
		"[data-role='autofill-submit']",
	)) {
		control.disabled = !!running;
	}
	marker.dataset.visible =
		messages.length || running || showTerminal ? "true" : "false";
}

/**
 * @testable true
 * @tests tests_js/test_049_autofill_review.mjs::test_review_bar_cancel_uses_operation_identity
 * @pair ai:autofill
 */
export function installReviewBar(widget) {
	widget._migrationNotice?.destroy();
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
		button.disabled = true;
		try {
			if (button.dataset.role === "autofill-cancel") {
				const operation = widget.reviewState?.operation;
				if (!operation?.can_cancel) return;
				const data = new FormData();
				data.set("operation-id", operation.operation_id);
				const { request } = await import("../shared/request.mjs");
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
				widget._autofillRetry = widget.reviewState?.retry_operation;
				widget.target.dispatchEvent(
					new CustomEvent("submit", {
						bubbles: true,
						cancelable: true,
						detail: { role: "autofill-submit", update: true },
					}),
				);
			}
		} catch (error) {
			widget.component?.showError?.(error.message);
			captureError(error);
		} finally {
			button.disabled = false;
		}
	};
	widget.target.addEventListener("click", click);
	const target = widget.target;
	widget._migrationNotice = {
		destroy: () => target.removeEventListener("click", click),
	};
}
