/*! Third-party licenses: /third-party-licenses.txt */
import { c as createIcon, s as setIcon } from '../icons.js?v=b052d07c';
import { r as request, w as withTransition } from '../foundation.js?v=b052d07c';
import { C as Core } from '../core-foundation.js?v=b052d07c';
import '../upstreamUnavailable.js?v=b052d07c';
import '../connectivity.js?v=b052d07c';

const REPORT_FORM_SELECTOR =
	"[data-role='run-report-form'], [data-role='retry-report-form'], [data-role='undo-report-form'], [data-role='recovery-undo-report-form'], [data-role='revise-report-form']";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_runs_ready_report
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_failed_report_detail_offers_retry_and_partial_undo
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_action_dependencies
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_ask_report_detail_shows_answer_without_duplicate_proposal
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_report_detail_shows_revision_and_manual_execution
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_organize_report_detail_refreshes_when_submitted_revision_completes
 * @matrix ai-report : answer-html ask create deferred-refresh delete-modal detail execute failure links no-actions pending reload result-json revision skip-action
 */
class Report extends Core {
	async init() {
		await super.init();
		this._receiveDeferredOperation = this._receiveDeferredOperation.bind(this);
		window.addEventListener(
			"deferred-operation",
			this._receiveDeferredOperation,
		);
		const hasForms = this.elt.querySelector(REPORT_FORM_SELECTOR);
		if (hasForms) {
			this._installReportFormBootstrap();
			try {
				await this.ensureReportForms();
			} catch (error) {
				this.reportStartupError(error, hasForms, "report-forms");
			}
		}
		return this;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_038_startup_specializations.py::test_report_loads_base_form_only_for_present_forms_and_in_parallel
	 * @matrix ai-report : concurrent-form-init lazy-form-runtime
	 */
	ensureReportForms() {
		if (this._reportFormsReady) return Promise.resolve(this);
		if (this._reportFormsPromise) return this._reportFormsPromise;

		const pending = import('../baseForm.js?v=b052d07c').then(function (n) { return n.b; })
			.then(async ({ BaseForm }) => {
				if (this._destroyed) return null;
				await Promise.all([
					this._initRunReportForm(BaseForm),
					this._initUndoReportForm(BaseForm),
					this._initReviseReportForm(BaseForm),
				]);
				if (this._destroyed) return null;
				this._reportFormsReady = true;
				this._removeReportFormBootstrap();
				return this;
			})
			.catch((error) => {
				if (this._reportFormsPromise === pending) {
					this._reportFormsPromise = null;
				}
				throw error;
			});
		this._reportFormsPromise = pending;
		return pending;
	}

	_installReportFormBootstrap() {
		if (this._reportFormBootstrap) return;
		this._reportFormBootstrap = (event) => {
			const form = event.target?.matches?.(REPORT_FORM_SELECTOR)
				? event.target
				: null;
			if (!form || this._reportFormsReady) return;
			event.preventDefault();
			event.stopImmediatePropagation?.();
			const submitter = event.submitter;
			void this.runColdAction(
				form,
				() => this.ensureReportForms(),
				() => {
					if (!this._destroyed && form.isConnected) {
						form.requestSubmit(submitter || undefined);
					}
				},
				submitter || form,
			);
		};
		this.elt.addEventListener?.("submit", this._reportFormBootstrap, true);
	}

	_removeReportFormBootstrap() {
		if (!this._reportFormBootstrap) return;
		this.elt.removeEventListener?.("submit", this._reportFormBootstrap, true);
		this._reportFormBootstrap = null;
	}

	async _initRunReportForm(BaseForm) {
		const target = this.elt.querySelector(
			"[data-role='run-report-form'], [data-role='retry-report-form']",
		);
		if (!target) return;
		const retrying = target.dataset.role === "retry-report-form";

		this.RunReportForm = new BaseForm({
			target,
			view: this,
			messages: {
				submit: retrying ? "Retry Proposal" : "Execute Proposal",
				submitting: retrying ? "Starting Retry" : "Starting Execution",
				submitted: retrying ? "Retry Started" : "Execution Started",
			},
			icon: "run.active",
		});
		await this.RunReportForm.init();
		target.addEventListener("submit", this._runReport.bind(this));
	}

	async _initUndoReportForm(BaseForm) {
		const target = this.elt.querySelector(
			"[data-role='undo-report-form'], [data-role='recovery-undo-report-form']",
		);
		if (!target) return;

		this.UndoReportForm = new BaseForm({
			target,
			view: this,
			messages: {
				submit: target.dataset.submit || "Undo Report",
				submitting: target.dataset.submitting || "Undoing Report",
				submitted: target.dataset.submitted || "Report Undone",
			},
			icon: "undo",
		});
		await this.UndoReportForm.init();
		target.addEventListener("submit", this._undoReport.bind(this));
	}

	async _initReviseReportForm(BaseForm) {
		const target = this.elt.querySelector("[data-role='revise-report-form']");
		if (!target) return;

		this.ReviseReportForm = new BaseForm({
			target,
			view: this,
			messages: {
				submit: target.dataset.submit || "Revise Plan",
				submitting: target.dataset.submitting || "Revising Plan",
				submitted: target.dataset.submitted || "Revision Started",
			},
			icon: target.dataset.icon || "generate",
		});
		await this.ReviseReportForm.init();
		target.addEventListener("submit", this._reviseReport.bind(this));
	}

	_click(event) {
		const skipButton = event.target.closest("[data-role='skip-action']");
		if (skipButton && this.elt.contains(skipButton)) {
			event.preventDefault();
			event.stopPropagation();
			this._toggleActionSkip(skipButton);
			return;
		}

		const expandButton = event.target.closest("[lp-expand]");
		if (expandButton && this.elt.contains(expandButton)) {
			event.preventDefault();
			event.stopPropagation();
			this._toggleAccordion(expandButton);
			return;
		}

		super._click(event);
	}

	async _runReport(event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._runningReport) return;

		this._runningReport = true;
		const form = event.currentTarget;
		const data = new FormData(form);
		data.append("operation-id", this.operationId());
		this.RunReportForm?.submitting();

		const response = await request.post(form.action, data);
		this._runningReport = false;
		if (!response?.ok) {
			this.RunReportForm?.showError(
				response?.error || "This report could not be run.",
			);
			if (response?.reload) {
				if (this.RunReportForm?.submitButton) {
					this.RunReportForm.submitButton.disabled = true;
				}
				window.setTimeout(() => window.location.reload(), 1000);
			}
			return;
		}

		if (response.notification) {
			const notifications = await this.ensureNotifications();
			notifications?.upsertNotification?.(response.notification);
		}
		this.RunReportForm?.success();
		if (response.deferred) {
			const operations = await this.ensureDeferredOperations();
			operations?.track(response.operation, { node: this.elt });
			this._showDeferredReportStatus("running", "Saving report changes...");
			return;
		}
		window.setTimeout(() => window.location.reload(), 250);
	}

	async _undoReport(event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._undoingReport) return;

		this._undoingReport = true;
		const form = event.currentTarget;
		const data = new FormData(form);
		this.UndoReportForm?.submitting();

		const response = await request.post(form.action, data);
		this._undoingReport = false;
		if (!response?.ok) {
			this.UndoReportForm?.showError(
				response?.error || "This report could not be undone.",
			);
			return;
		}

		this.UndoReportForm?.success();
		window.setTimeout(() => window.location.reload(), 250);
	}

	async _reviseReport(event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._revisingReport) return;

		this._revisingReport = true;
		const form = event.currentTarget;
		const data = new FormData(form);
		data.append("operation-id", this.operationId());
		this.ReviseReportForm?.submitting();

		const response = await request.post(form.action, data);
		this._revisingReport = false;
		if (!response?.ok) {
			this.ReviseReportForm?.showError(
				response?.error || "This report could not be revised.",
			);
			return;
		}

		if (response.notification) {
			const notifications = await this.ensureNotifications();
			notifications?.upsertNotification?.(response.notification);
		}
		this.ReviseReportForm?.success();
		if (response.deferred) {
			const operations = await this.ensureDeferredOperations();
			operations?.track(response.operation, { node: this.elt });
			this._showDeferredReportStatus("revising", "Revising report...");
			return;
		}
		window.setTimeout(() => window.location.reload(), 250);
	}

	_showDeferredReportStatus(statusValue, message) {
		const section = this.elt.querySelector("#layout section");
		if (!section) return;
		void withTransition(
			() => {
				this.elt.dataset.pending = "true";
				this.elt.dataset.status = statusValue;

				let status = section.querySelector("[data-role='report-status']");
				if (!status) {
					status = document.createElement("div");
					status.dataset.role = "report-status";
					status.className = "flex flex-col gap-1";

					const heading = document.createElement("h2");
					heading.className = "text-base font-semibold text-base-dark";
					heading.textContent = "Status";

					const note = document.createElement("p");
					note.dataset.role = "report-status-note";
					note.className = "text-base-dark";
					status.append(heading, note);
					section.prepend(status);
				}

				const note =
					status.querySelector("[data-role='report-status-note']") || status;
				const spinner = createIcon("spinner", "mr-1");
				spinner.setAttribute("aria-hidden", "true");
				note.replaceChildren(spinner, ` ${message}`);
				let progress = status.querySelector("[data-role='deferred-progress']");
				if (!progress) {
					progress = document.createElement("p");
					progress.dataset.role = "deferred-progress";
					progress.className = "text-sm text-base-medium";
					const phase = document.createElement("span");
					phase.dataset.role = "deferred-phase";
					phase.textContent = "Waiting to start";
					const separator = document.createElement("span");
					separator.setAttribute("aria-hidden", "true");
					separator.textContent = " · ";
					const elapsed = document.createElement("span");
					elapsed.dataset.role = "deferred-elapsed";
					elapsed.textContent = "just now";
					progress.append(phase, separator, elapsed);
					status.append(progress);
				}
			},
			{ label: "report:show-deferred-status" },
		);
	}

	_receiveDeferredOperation(event) {
		const status = event.detail;
		if (!status?.terminal || status.key !== this.elt.dataset.operation) return;
		this._reloadReport();
	}

	_reloadReport(delay = 0) {
		if (this._reportReloadScheduled) return;
		this._reportReloadScheduled = true;
		window.setTimeout(() => window.location.reload(), delay);
	}

	destroy() {
		this._removeReportFormBootstrap();
		window.removeEventListener(
			"deferred-operation",
			this._receiveDeferredOperation,
		);
		this.RunReportForm?.destroy?.();
		this.UndoReportForm?.destroy?.();
		this.ReviseReportForm?.destroy?.();
		super.destroy();
	}

	async _toggleActionSkip(button) {
		if (button.disabled) return;

		button.disabled = true;
		const actionIndexes = (
			button.closest("[data-action-indexes]")?.dataset.actionIndexes || ""
		)
			.split(",")
			.map((value) => Number(value))
			.filter(Boolean);
		const includeDependencies =
			button.closest("[data-skip-dependencies]")?.dataset.skipDependencies !==
			"false";
		const response = await request.post(button.dataset.route, {
			action_indexes: actionIndexes,
			include_dependencies: includeDependencies,
		});
		button.disabled = false;
		if (!response?.ok) return;

		const skipped = new Set(response.skipped || []);
		await withTransition(
			() => {
				this.elt.querySelectorAll("[data-action-index]").forEach((item) => {
					this._setActionSkipped(
						item,
						skipped.has(Number(item.dataset.actionIndex)),
					);
				});
			},
			{ label: "report:toggle-skipped-actions" },
		);
	}

	_setActionSkipped(item, skipped) {
		item.dataset.skipped = skipped ? "true" : "false";
		const label = item.querySelector("[data-role='skipped-label']");
		if (label) label.dataset.visible = item.dataset.skipped;

		const button = item.querySelector("[data-role='skip-action']");
		if (!button) return;
		button.title = skipped ? "Restore action" : "Skip action";
		button.dataset.kind = skipped
			? button.dataset.restoreKind
			: button.dataset.skipKind;
		button.setAttribute(
			"aria-label",
			`${button.title} ${item.dataset.actionIndex}`,
		);
		const icon = button.querySelector("[data-icon]");
		if (icon) {
			setIcon(
				icon,
				skipped ? button.dataset.restoreIcon : button.dataset.skipIcon,
			);
		}
	}

	async _toggleAccordion(button) {
		const accordion = button.closest("[data-role='accordion']");
		const panel = accordion?.querySelector("[data-role='accordion-panel']");
		if (!accordion || !panel) return;

		await withTransition(
			() => {
				const open = accordion.dataset.open !== "true";
				accordion.dataset.open = open ? "true" : "false";
				button.dataset.open = accordion.dataset.open;
				button.setAttribute("aria-expanded", open ? "true" : "false");
				panel.dataset.visible = accordion.dataset.open;
			},
			{ label: "report:toggle-accordion" },
		);
	}
}

export { Report as default };
