/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseForm } from './baseForm.js?v=be1b1fb2';

/**
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_form_revision_snapshot_is_canonical_and_memory_only
 * @features forms edited-entity-notice
 * @dimensions formdata canonicalization repeated-values revision-only-state
 */
class FormElement {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.destroyables = [];
		this.messages = {};
		this.schema = attributes.schema || null;
		this.submission = attributes.submission || null;
		this.form = null;
		this.initialTarget = this.target ? this.target.cloneNode(true) : null;
		this.initialized = false;
		this.unsavedState = false;
		this._revisionBaseline = null;

		this._created = false;
		this._updated = false;
		this._success = false;

		this._deferredOperation = this.target?.dataset?.operation || null;

		this._click = this._click.bind(this);
	}

	get deferredLocked() {
		return Boolean(
			this._deferredOperation && this.target?.dataset?.deferredLock,
		);
	}

	lockDeferredOperation(descriptor = {}) {
		const operation = descriptor.operation || descriptor.key;
		if (!operation) return false;
		this._deferredOperation = operation;
		for (const target of [this.target, this.initialTarget]) {
			if (!target) continue;
			target.dataset.operation = operation;
			target.dataset.operationRevision = String(
				Number(descriptor.revision) || 0,
			);
			target.dataset.deferredLock = "form";
		}
		this.clearUnsavedState();
		return true;
	}

	get showEmptyFields() {
		return this.readonly && this.component?.showEmptyFields === true;
	}
	get formData() {
		return this.target instanceof HTMLFormElement
			? new FormData(this.target)
			: new FormData();
	}

	get revisionEntries() {
		return [];
	}

	get revisionBaseline() {
		return this._revisionBaseline;
	}

	revisionSnapshot() {
		const grouped = new Map();
		const entries = [...this.formData.entries(), ...this.revisionEntries];
		for (const [name, rawValue] of entries) {
			let value = rawValue;
			if (typeof File !== "undefined" && rawValue instanceof File) {
				if (!rawValue.name && rawValue.size === 0) continue;
				value = JSON.stringify({
					name: rawValue.name,
					size: rawValue.size,
					type: rawValue.type,
					lastModified: rawValue.lastModified,
				});
			}
			const values = grouped.get(name) ?? [];
			values.push(String(value));
			grouped.set(name, values);
		}

		return JSON.stringify(
			Array.from(grouped.entries())
				.sort(([left], [right]) => left.localeCompare(right))
				.map(([name, values]) => [name, values.sort()]),
		);
	}

	commitRevisionBaseline({ clearUnsaved = false } = {}) {
		this._revisionBaseline = this.revisionSnapshot();
		if (clearUnsaved) this.clearUnsavedState();
		return this._revisionBaseline;
	}

	revisionCanReset(preview) {
		return Boolean(preview && preview.name === this.name);
	}

	captureFormState() {
		const fields = [];
		const files = [];
		for (const [name, value] of this.formData.entries()) {
			if (typeof File !== "undefined" && value instanceof File) {
				if (value.name && value.size > 0) {
					files.push({
						name,
						file: value,
						filename: value.name,
						type: value.type,
					});
				}
			} else {
				fields.push([name, value]);
			}
		}

		const formControls = Array.from(
			this.target?.querySelectorAll?.("[data-combobox-id]") || [],
		)
			.filter((control) => !control.closest?.(".form-element"))
			.map((control) => {
				const combobox = control._lp_combobox;
				if (!combobox?.name) return null;
				return {
					name: combobox.name,
					options: (combobox.options || []).filter((option) =>
						combobox.values?.has(option.id),
					),
				};
			})
			.filter(Boolean);

		return {
			fields,
			files,
			form_controls: formControls,
			renderer_submission: this.form?.renderer?._packageSubmission?.() ?? null,
		};
	}

	buildLocalRevision(response, state = this.captureFormState()) {
		const latestSchema = response.schema ?? [];
		const latestIds = new Set(
			latestSchema.map((field) => field?.id).filter(Boolean),
		);
		const localIds = new Set(
			(this.schema ?? []).map((field) => field?.id).filter(Boolean),
		);
		const remoteSubmission = response.submission ?? {};
		const mergedSubmission = structuredClone(remoteSubmission);
		const localSubmission = state.renderer_submission ?? {};
		for (const id of localIds) {
			if (!latestIds.has(id) || !Object.hasOwn(localSubmission, id)) continue;
			mergedSubmission[id] = structuredClone(localSubmission[id]);
		}

		const html = response.html?.cloneNode(true) ?? null;
		const target = html?.querySelector(`[data-widget='${this.name}']`);
		this._applyQueuedFields(target, state);
		return {
			state,
			response: {
				...response,
				html,
				schema: latestSchema,
				submission: mergedSubmission,
			},
		};
	}

	async applyRevision(response) {
		await this.updated(response);
		this._success = false;
		await this.postreconcile();
		this.commitRevisionBaseline({ clearUnsaved: true });
	}

	async applyLocalRevision(
		response,
		{
			remoteSnapshot = null,
			markUnsaved = false,
			selectedSubmission = undefined,
		} = {},
	) {
		const wasUnsaved = this.unsavedState === true;
		const wasQueued = this.form?._queued === true;
		const local = this.buildLocalRevision(response);
		if (selectedSubmission !== undefined) {
			local.response.submission = selectedSubmission;
		}
		this._skipQueuedRestore = true;
		try {
			await this.updated(local.response);
			this._success = false;
			await this.postreconcile();
			this._restoreQueuedFiles(local.state);
		} finally {
			this._skipQueuedRestore = false;
		}

		if (remoteSnapshot !== null) this._revisionBaseline = remoteSnapshot;
		if (wasQueued) {
			this.form?.queued();
		} else if (wasUnsaved || markUnsaved) {
			this.markUnsavedState();
		} else {
			this.commitRevisionBaseline({ clearUnsaved: true });
		}
		return local;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_form_submit_is_guarded_only_by_durable_autofill_lock
	 * @features forms submission deferred-jobs
	 * @dimensions deliberate-submit form-lock no-live-sync
	 */
	async prepareSubmit() {
		if (this.deferredLocked) return false;
		return true;
	}

	markUnsavedState() {
		if (this.readonly || this.headless) return;

		this.unsavedState = true;
		this.form?.syncOfflineState?.();
	}

	clearUnsavedState() {
		this.unsavedState = false;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_offline_queue_does_not_block_initial_form_render
	 * @pair forms:queue-independent-initial-render
	 */
	async init() {
		await this._initForm();
		this.commitRevisionBaseline();
		this.initialized = true;
		this.target.setAttribute("initialized", "");
	}

	/** @testable infrastructure */
	async stageOfflineConflict(conflict = this._offlineConflict) {
		if (!conflict) return;
		const watcher =
			this.view?.EditWatcher || (await this.view?.ensureEditWatcher?.());
		return watcher?.stageConflict?.(this, conflict);
	}

	_applyQueuedFields(target, record) {
		if (!target) return;

		const fields = new Map();
		for (const [name, value] of record.fields || []) {
			const values = fields.get(name) || [];
			values.push(String(value));
			fields.set(name, values);
		}

		for (const name of ["name", "description"]) {
			if (fields.has(name)) target.dataset[name] = fields.get(name)[0] || "";
		}

		for (const control of target.querySelectorAll("[name]")) {
			const values = fields.get(control.name) || [];
			if (control instanceof HTMLInputElement) {
				if (["checkbox", "radio"].includes(control.type)) {
					const checked = values.includes(control.value);
					control.checked = checked;
					control.defaultChecked = checked;
					control.toggleAttribute("checked", checked);
					const attribute = control.closest("[data-role='attribute']");
					if (attribute) attribute.dataset.selected = checked.toString();
				} else if (control.type !== "file" && values.length > 0) {
					control.value = values[0];
					control.defaultValue = values[0];
					control.setAttribute("value", values[0]);
				}
			} else if (control instanceof HTMLTextAreaElement) {
				control.value = values[0] || "";
				control.defaultValue = control.value;
				control.textContent = control.value;
			} else if (control instanceof HTMLSelectElement) {
				for (const option of control.options) {
					const selected = values.includes(option.value);
					option.selected = selected;
					option.defaultSelected = selected;
					option.toggleAttribute("selected", selected);
				}
			}
		}

		const preloadSources = Array.from(
			target.querySelectorAll("[name], [data-index]"),
		);
		for (const state of record.form_controls || []) {
			const source = preloadSources.find(
				(element) =>
					element.getAttribute("name") === state.name ||
					element.dataset.index === state.name,
			);
			if (!source) continue;
			const root = source.closest("[lp-select]") || source;
			const preload = JSON.stringify(state.options || []);
			source.dataset.preload = preload;
			root.dataset.preload = preload;
		}
	}

	_restoreQueuedFiles(record) {
		if (typeof DataTransfer === "undefined") return;

		const files = new Map();
		for (const entry of record.files || []) {
			const values = files.get(entry.name) || [];
			values.push(entry.file);
			files.set(entry.name, values);
		}

		for (const input of this.target.querySelectorAll(
			"input[type='file'][name]",
		)) {
			const saved = files.get(input.name);
			if (!saved?.length) continue;
			try {
				const transfer = new DataTransfer();
				for (const file of saved) transfer.items.add(file);
				input.files = transfer.files;
			} catch {
				// Some browsers do not allow programmatic file-input restoration.
			}
		}
	}

	async _initForm() {
		if (this.initialTarget) {
			const visible = this.target?.dataset.visible;
			if (visible !== undefined) {
				this.initialTarget.dataset.visible = visible;
			}
			this.target.replaceWith(this.initialTarget);
			this.target = this.initialTarget;
			this.initialTarget = this.target.cloneNode(true);
		} else {
			this.initialTarget = this.target.cloneNode(true);
		}
		this.target._lp_widget = this;
		this.form = new BaseForm(this);
		await this.form.init();
		this.target.addEventListener("click", this._click);
		const hasDeferredOperation =
			this.target.matches?.("[data-operation]") ||
			this.target.querySelector?.("[data-operation]");
		if (hasDeferredOperation) {
			const manager = await this.view?.ensureDeferredOperations?.();
			manager?.scan(this.target);
		}
	}

	_click(e) {
		if (this.readonly) return;

		const element = e.target.closest(".form-element");
		const role = e.target.closest("[data-role]")?.dataset.role;
		if (role !== "edit" && role !== "clear") return;

		e.preventDefault();
		e.stopPropagation();

		if (role === "edit") {
			element.dataset.mode = "edit";
		} else if (role === "clear") {
			const field =
				element?._lp_element ?? this.form.renderer?.elements.get(element.id);
			field?.clear?.();
		}
	}

	get header() {
		return this.target?.querySelector("[data-role='header']");
	}

	get submitGroup() {
		return this.target?.querySelector("[data-role='submit-group']");
	}

	get submitButton() {
		return this.target?.querySelector('button[type="submit"]:not([data-role])');
	}

	async reset() {
		this.clearUnsavedState();
		this.destroy();
		await this._initForm();
		this.commitRevisionBaseline();
	}

	setEntityMetadata() {
		if (this.revisionPreview) return;
		const pageTitle = document.querySelector(
			"[data-nav='view'] [data-role='title']",
		);
		const pageDescription = document.querySelector("[data-role='description']");

		const name =
			this.target.querySelector("[name='name']")?.value ||
			this.target.dataset.name ||
			"";
		const description =
			this.target.querySelector("[name='description']")?.value ||
			this.target.dataset.description ||
			"";

		if (pageTitle && pageTitle.textContent !== name)
			pageTitle.textContent = name;
		if (pageDescription && pageDescription.textContent !== description)
			pageDescription.textContent = description;
	}

	created() {
		this._created = true;
	}

	success() {
		this._success = true;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_032_task_settings_lifecycle.py::test_form_response_metadata_stays_with_renderer_widget
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_adding_form_from_task_settings_preserves_widget_identity
	 * @pairs forms:schema-ownership forms:sibling-widgets
	 * @pairs tasks:attach-form tasks:widget-identity tasks:merged-submission
	 */
	updated(response) {
		const updatedTarget = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		const ownsRendererState =
			!updatedTarget ||
			[updatedTarget, this.target, this.initialTarget].some(
				(target) =>
					target?.hasAttribute?.("data-schema") ||
					target?.hasAttribute?.("data-submission"),
			);
		if (updatedTarget) {
			this.initialTarget = updatedTarget;
			this._deferredOperation = updatedTarget.dataset.operation || null;
			this._updated = true;
		}
		if (ownsRendererState && Object.hasOwn(response, "schema")) {
			this.schema = response.schema;
		}
		if (ownsRendererState && Object.hasOwn(response, "submission")) {
			this.submission = response.submission;
		}
	}

	async postreconcile() {
		const updated = this._updated;
		if (!this._created && !updated) return;

		this._created = false;
		this._updated = false;

		if (updated) {
			await this.reset();
			if (this.visible) this.target.dataset.visible = "true";
		}

		if (this._success) {
			this.form?.success();
			this._success = false;
		}
	}

	destroy() {
		this.form?.destroy();
		this.destroyables.forEach((destroyable) => {
			if (destroyable.destroy) destroyable.destroy();
		});
		this.destroyables = [];
		this.form = null;
	}

	showError(error) {
		this.form?.showError(error);
	}
}

export { FormElement as F };
