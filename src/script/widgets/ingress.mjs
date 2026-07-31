import { buttons } from "../elements/buttons.mjs";
import { FacetsBox, SelectBox } from "../elements/combobox";
import { formatting } from "../elements/formatting";
import { primitives } from "../elements/primitives";
import { Modal, request, withTransition } from "../shared";

/**
 * @testable infrastructure
 */
export class ImportData {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.stageElt = this.target.querySelector("[data-role='stage']");
		this.progressElt = this.target.querySelector("[data-role='progress']");
		this.stage = this.target.dataset.stage;
		this.stageSettings = null;
		this.error = null;
		this.stopButton = null;
		this.stopped = false;
		this.actions = new Set();
		this.runStatus = "idle";
		this.pollAfterMs = null;
		this.importRequestStarted = false;
		this._unsubscribeImport = null;

		this._parser = new DOMParser();
		this._refreshProgress = this._refreshProgress.bind(this);
		this._updateVisibility = this._updateVisibility.bind(this);
		this._click = this._click.bind(this);
		this._change = this._change.bind(this);
		this._next = this._next.bind(this);
		this._deleteImported = this._deleteImported.bind(this);
	}

	init() {
		request.get(this.endpoints.get(this.key)).then((resp) => {
			this._setStage(resp);
		});

		this.target.addEventListener("click", this._click);
		this.progressElt.addEventListener("change", this._change);
		this.progressElt.addEventListener("input", this._updateVisibility);
	}

	async _click(e) {
		const button = e.target.closest("button");
		if (!button) return;

		if (button.dataset.role === "next") {
			formatting.working(button, "Processing...");
			this._next();
		} else if (button.dataset.role === "import") {
			formatting.working(button, "Starting Import...");
			this._startImport();
		} else if (button.dataset.role === "set-stage") {
			const stage = button.dataset.stage;
			this._setStage(
				await request.put(this.endpoints.setStage(this.key), { stage }),
			);
		} else if (button.dataset.role === "delete-imported") {
			await this._deleteImported(button);
		} else if (button.dataset.role === "stop" && this.actions.has("stop")) {
			this.stopButton.activate("Stopping...", "delete");
			this._setImportStopped();
			this._setStage(await request.post(this.endpoints.stop(this.key)));
		} else if (button.dataset.role === "stop" && this.actions.has("restart")) {
			this.stopButton.activate("Restarting...", "project");
			this.stopped = false;
			this.importRequestStarted = false;
			this._startImport();
			button.dataset.stopped = "false";
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @features ingress
	 * @dimensions choose-type
	 */
	async _change(e) {
		const form = e.target.closest("form");
		if (!form) return;

		this.stageElt
			.querySelectorAll("[data-process]")
			.forEach((processButton) => {
				if (processButton.dataset.process === this.stage) {
					processButton.dataset.visible = "true";
				} else {
					processButton.dataset.visible = "false";
				}
			});

		const updates = new FormData(form);
		request.patch(this.endpoints.update(this.key), updates);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @features ingress
	 * @dimensions stage-wizard
	 */
	_setStage(resp) {
		const {
			stage,
			error,
			progress,
			status,
			stopped = false,
			actions = [],
			run_status: runStatus = "idle",
			poll_after_ms: pollAfterMs = null,
		} = resp;
		if (!stage) return false;

		withTransition(() => {
			this.stageElt.innerHTML = progress;
			this.progressElt.innerHTML = status;
			this.stage = stage;
			this.stopped = stopped === true || stopped === "true";
			this.actions = new Set(actions);
			this.runStatus = runStatus;
			this.pollAfterMs = pollAfterMs;

			if (this.stageSettings) {
				this._destroyStage();
			}

			this.stageSettings = {
				target: this.progressElt.querySelector("form"),
				destroyables: [],
			};

			if (stage === "CHOOSE_FORM") {
				this._setChooseForm();
			} else if (stage === "CHOOSE_PARENT") {
				this._setChooseParent();
			} else if (stage === "ASSIGN_COLUMNS") {
				this._setAssignColumns();
			} else if (stage === "VERIFY_IMPORT") {
				this._setVerifyImport();
			} else if (stage === "IMPORTING") {
				this._setImportControls();
				if (this.actions.has("restart")) {
					this._setImportStopped();
				} else if (
					["queued", "running", "stop_requested"].includes(this.runStatus)
				) {
					this._startImportPolling();
				}
			} else {
				this._setImportStopped();
			}

			if (error) {
				if (stage === "IMPORTING") {
					this._setImportStopped();
				}
				this._showError(error);
			} else {
				this._clearError();
			}
		});
		return true;
	}

	_updateVisibility(e) {
		if (e.target.dataset?.optionToggle !== "true") return;

		const option =
			e.target.type === "checkbox" ? e.target.name : e.target.value;
		const section = e.target.closest("[data-section]");

		section.querySelectorAll("[data-option]").forEach((section) => {
			if (e.target.checked && section.dataset.option === option) {
				section.dataset.visible = "true";
			} else {
				section.dataset.visible = "false";
			}
			const visible = section.dataset.visible === "true";
			if (!visible) {
				this.stageSettings.destroyables.forEach((destroyable) => {
					if (destroyable.clear) destroyable.clear();
				});
				section.querySelectorAll("input").forEach((input) => {
					input.checked = false;
					input.value = "";
				});
			}
		});
	}

	_showError(message) {
		this._clearError();
		this.error = primitives.error(message);
		this.error.dataset.visible = "true";
		this.progressElt.prepend(this.error);
	}

	_clearError() {
		if (!this.error) return;
		this.error.remove();
		this.error = null;
	}

	_destroyStage() {
		if (this.stageSettings) {
			this.stageSettings.destroyables.forEach((destroyable) => {
				destroyable.destroy();
			});
		}
		this.stageSettings = null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_ignored_columns_are_not_imported
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_task_page_form_lookup_updates_index_fields
	 * @features ingress
	 * @dimensions verify-import page-form-lookup
	 */
	_setVerifyImport() {
		const target = this.stageSettings.target;
		let section = target.querySelector("[data-section='page-form-index']");
		if (!section) return;

		const setupSelects = () => {
			const pageSelect = section.querySelector("[data-option='page-form']");
			const indexFrom = section.querySelector("[data-role='index-from']");
			const indexTo = section.querySelector("[data-role='index-to']");

			if (pageSelect) {
				const selectPageForm = new FacetsBox(pageSelect);
				selectPageForm.init();
				this.stageSettings.destroyables.push(selectPageForm);
			}

			if (indexFrom) {
				const selectIndexFrom = new SelectBox(indexFrom);
				selectIndexFrom.init();
				this.stageSettings.destroyables.push(selectIndexFrom);
			}

			if (indexTo?.hasAttribute("lp-select")) {
				const selectIndexTo = new SelectBox(indexTo);
				selectIndexTo.init();
				this.stageSettings.destroyables.push(selectIndexTo);
			}
		};

		setupSelects();

		target.addEventListener("change", async (e) => {
			if (!["page-form-id", "index-field-choice"].includes(e.target.name)) {
				return;
			} else if (
				e.target.name === "index-field-choice" &&
				e.target.value === "page-form"
			) {
				return;
			}

			e.stopPropagation();

			section.classList.add("opacity-50", "pointer-events-none");
			const params = new URLSearchParams();
			params.set("update-form-index", e.target.value);
			const resp = await request.get(
				this.endpoints.getPageForm(this.key),
				params,
			);
			const html =
				resp.html instanceof Document
					? resp.html
					: this._parser.parseFromString(resp.html, "text/html");
			const newSection = html.querySelector("[data-section='page-form-index']");
			if (!newSection) return;

			withTransition(() => {
				this.stageSettings.destroyables.forEach((destroyable) => {
					destroyable.destroy();
				});
				this.stageSettings.destroyables = [];
				section.replaceWith(newSection);
				section = newSection;
				setupSelects();
			});
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_selects_existing_parent_and_form
	 * @features ingress
	 * @dimensions choose-form existing-form
	 */
	_setChooseForm() {
		const formElt = this.stageSettings.target;
		const selectButton = formElt.querySelector("[data-option='existing-form']");
		const selectForm = new FacetsBox(selectButton);

		selectForm.init();
		this.stageSettings.destroyables.push(selectForm);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_selects_existing_parent_and_form
	 * @features ingress
	 * @dimensions choose-parent existing-parent
	 */
	_setChooseParent() {
		const parentElt = this.stageSettings.target;
		const selectButton = parentElt.querySelector(
			"[data-option='existing-parent']",
		);
		const selectParent = new FacetsBox(selectButton);
		selectParent.init();
		this.stageSettings.destroyables.push(selectParent);

		const createModel = this.stageSettings.target.querySelector(
			"[data-section='create-model']",
		);
		if (!createModel) return;

		if (createModel.dataset.parentKind === "project") {
			createModel.dataset.visible = "true";
		} else {
			createModel.dataset.visible = "false";
		}

		this.stageSettings.target.addEventListener("updated", (e) => {
			Object.values(e.detail.options).forEach((option) => {
				if (option.kind === "project") {
					createModel.dataset.visible = "true";
					createModel.dataset.parentKind = "project";
				} else if (option.kind === "model") {
					createModel.dataset.parentKind = "model";
					createModel.dataset.visible = "false";
				}
			});
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
	 * @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_ignored_columns_are_not_imported
	 * @features ingress
	 * @dimensions assign-columns ignored-columns
	 */
	_setAssignColumns() {
		const target = this.stageSettings.target;
		const columns = target.querySelectorAll("[lp-select]");

		columns.forEach((column) => {
			const select = new SelectBox(column);
			select.init();
			this.stageSettings.destroyables.push(select);
		});

		const _setOpacity = (checkbox) => {
			const select = checkbox.closest("tr").querySelector("[lp-select]");
			if (checkbox.checked) {
				select.classList.add("opacity-50", "pointer-events-none");
				select._lp_combobox?.clear();
			} else {
				select.classList.remove("opacity-50", "pointer-events-none");
			}
		};

		target.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
			if (checkbox.checked) {
				_setOpacity(checkbox);
			}
		});

		target.addEventListener("change", (e) => {
			if (e.target.type === "checkbox") {
				_setOpacity(e.target);
			}
		});
	}

	async _next() {
		const form = this.stageSettings.target;
		const updates = form ? new FormData(form) : new FormData();
		updates.append("stage", this.stage);

		this._setStage(await request.put(this.endpoints.next(this.key), updates));
	}

	_setImportControls() {
		const button = this.stageElt.querySelector("[data-role='stop']");
		if (!button) return;

		this.stopButton = buttons.active({ existingButton: button });
	}

	_setImportStopped() {
		this.importRequestStarted = false;
		this._stopImportPolling();
	}

	async _refreshProgress() {
		const response = await request.get(this.endpoints.get(this.key));
		if (!response?.ok) return false;
		return this._setStage(response);
	}

	_startImportPolling() {
		this.importRequestStarted = true;
		return this.syncPollingSubscription();
	}

	_pollingVisible() {
		if (
			this.component?.active !== this ||
			this.component?.visible !== true ||
			this.visible !== true
		)
			return false;
		let ancestor =
			this.component?.elt?.parentElement?.closest?.("[lp-component]");
		while (ancestor) {
			if (ancestor.dataset.visible === "false") return false;
			ancestor = ancestor.parentElement?.closest?.("[lp-component]");
		}
		return true;
	}

	/**
	 * Import progress is only useful while its wizard is the active visible
	 * widget. A running import is remembered and catches up when reopened.
	 *
	 * @testable true
	 * @tests tests_js/test_035_ingress_polling.py::test_ingress_polling_tracks_widget_visibility
	 * @features ingress polling
	 * @dimensions active-widget visibility subscription-lifecycle catch-up
	 * @pairs ingress:active-widget ingress:visibility ingress:subscription-lifecycle ingress:catch-up
	 * @pairs polling:active-widget polling:visibility polling:subscription-lifecycle polling:catch-up
	 */
	async syncPollingSubscription() {
		if (!this.importRequestStarted || !this._pollingVisible()) {
			this._stopImportPolling();
			return;
		}
		if (!this.view.PollingCoordinator) {
			await this.view.ensurePollingCoordinator?.();
			if (!this.importRequestStarted || !this._pollingVisible()) return;
		}
		if (this._unsubscribeImport) return;
		this._unsubscribeImport = this.view.PollingCoordinator?.subscribe(
			{
				id: `ingress:${this.key}`,
				type: "ingress",
				key: this.key,
				revision: this.target.dataset.fingerprint ?? null,
			},
			{
				onResult: (result) => {
					if (!this._pollingVisible()) return false;
					if (result.status === "changed") return this._refreshProgress();
				},
			},
		);
	}

	_stopImportPolling() {
		this._unsubscribeImport?.();
		this._unsubscribeImport = null;
	}

	async _deleteImported(button) {
		const modal = new Modal(this.view, button);
		await modal.load(this.endpoints.deleteImported(this.key));

		const deleteButton = modal.modal?.querySelector(
			"[data-role='delete-imported']",
		);
		if (!deleteButton) return;

		deleteButton.addEventListener(
			"click",
			async () => {
				deleteButton.disabled = true;
				deleteButton.querySelector("#spinner").dataset.visible = "true";
				const response = await request.delete(deleteButton.dataset.route);
				if (!response.ok) {
					deleteButton.disabled = false;
					deleteButton.querySelector("#spinner").dataset.visible = "false";
					return;
				}

				await modal.remove();
				this._setStage(response);
			},
			{ once: true },
		);
		deleteButton.focus();
	}

	_startImport() {
		this._setImportControls();
		this.importRequestStarted = true;
		this.stopButton?.deactivate("Stop Import", "delete");

		this._startImportPolling();

		request.post(this.endpoints.import(this.key), {}).then((resp) => {
			if (!resp.ok) {
				this._setImportStopped();
				this._showError(
					resp.error || "Import could not be started. Please try again.",
				);
				return;
			}
			if (resp.stage) {
				this._setStage(resp);
			} else {
				this._refreshProgress();
			}
		});
	}

	destroy() {
		this._destroyStage();
		this._stopImportPolling();
	}
}
