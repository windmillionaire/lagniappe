import { FormController } from "../../forms/controller.mjs";
import { installMigrationNotice } from "../../forms/migrationNotice.mjs";
import {
	currentReviewOperation,
	installReviewBar,
	renderReviewBar,
} from "../../forms/reviewBar.mjs";
import { compatibleField } from "../../forms/representation.mjs";
import { withTransition } from "../../shared/transitions.mjs";

/**
 * @testable true
 * @tests tests_js/test_024_edit_watcher.mjs::test_form_revision_snapshot_is_canonical_and_memory_only
 * @matrix edited-entity-notice forms : canonicalization formdata repeated-values revision-only-state
 * @tests tests_js/test_048_form_controls.mjs::test_form_shell_waits_for_html_and_visibility_does_not_rebuild
 * @tests tests_js/test_048_form_controls.mjs::test_form_replacements_serialize_and_adopt_only_latest_controls
 * @tests tests_js/test_048_form_controls.mjs::test_form_discard_and_failure_leave_live_controls_intact
 * @tests tests_js/test_048_form_controls.mjs::test_explicit_revision_reset_can_replace_dirty_form
 * @matrix forms user-groups : initialization conditional-response single-reconciliation rebuild-serialization
 * @matrix forms : teardown reset unsaved-preservation
 * @matrix user-groups : background-update unsaved-preservation reset
 * @tests tests_js/test_048_form_controls.mjs::test_queued_commit_waits_for_newer_replacement
 */
export class FormWidget {
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
		this._preparedReset = null;
		this._preparingReset = null;
		this._preparingState = null;
		this._resetEpoch = 0;
		this._replacementVersion = 0;
		this._replacementPromise = null;
		this._replacementInert = null;
		this._migrationNotice = null;
		this._reviewBar = null;

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
			target.dataset.operationRevision = String(descriptor.revision ?? 0);
			target.dataset.operationScope = descriptor.scope || "";
			if (descriptor.blocks_edit === true || descriptor.scope === "form-change")
				target.dataset.deferredLock = "form";
			else delete target.dataset.deferredLock;
			if (descriptor.status && typeof descriptor.status === "object") {
				target.dataset.operationBootstrap = JSON.stringify(descriptor.status);
				if (target.dataset.formState) {
					const state = JSON.parse(target.dataset.formState);
					state.operation = descriptor.status;
					if (
						descriptor.status.type === "autofill" &&
						!descriptor.status.terminal
					)
						state.stale_autofill = false;
					target.dataset.formState = JSON.stringify(state);
				}
			}
		}
		if (descriptor.status && typeof descriptor.status === "object") {
			this.reviewState = { ...this.reviewState, operation: descriptor.status };
			if (descriptor.status.type === "autofill" && !descriptor.status.terminal)
				this.reviewState.stale_autofill = false;
			renderReviewBar(this, descriptor.status);
		}
		return true;
	}

	get showEmptyFields() {
		return this.readonly && this.component?.showEmptyFields === true;
	}
	get formData() {
		const data =
			this.target instanceof HTMLFormElement
				? new FormData(this.target)
				: new FormData();
		const state =
			this.reviewState ?? JSON.parse(this.target?.dataset?.formState || "{}");
		if (state.revision) data.set("form-revision", state.revision);
		for (const operation of this._reviewedOperations ?? [])
			data.append("reviewed-operation", operation);
		for (const operation of this._usedAutofillOperations ?? [])
			data.append("used-autofill-operation", operation);
		if (this._autofillRetry) data.set("autofill-retry", this._autofillRetry);
		return this.form?._subForm?.applyDirectUploads?.(data) ?? data;
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
			if (
				[
					"form-revision",
					"reviewed-operation",
					"used-autofill-operation",
					"autofill-retry",
				].includes(name)
			)
				continue;
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
		this._baselineSubmission = structuredClone(
			this.form?.renderer?._packageSubmission?.() ?? this.submission ?? {},
		);
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
			renderer_schema: structuredClone(this.schema),
			renderer_submission: this.form?.renderer?._packageSubmission?.() ?? null,
		};
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.mjs::test_local_revision_uses_latest_schema_and_merges_submission_values
	 * @matrix edited-entity-notice form-schema forms : latest-schema local-values no-schema-version-choice remote-added-values
	 */
	buildLocalRevision(response, state = this.captureFormState()) {
		const latestSchema = response.schema ?? [];
		const localSchema = state.renderer_schema ?? this.schema ?? [];
		const latestIds = new Set(
			latestSchema.map((field) => field?.id).filter(Boolean),
		);
		const localIds = new Set(
			localSchema.map((field) => field?.id).filter(Boolean),
		);
		const remoteSubmission = response.submission ?? {};
		const mergedSubmission = structuredClone(remoteSubmission);
		const localSubmission = state.renderer_submission ?? {};
		for (const id of localIds) {
			if (
				!latestIds.has(id) ||
				!Object.hasOwn(localSubmission, id) ||
				!compatibleField(
					localSchema.find((field) => field.id === id),
					latestSchema.find((field) => field.id === id),
				)
			)
				continue;
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

	async prepareRevision(response) {
		await this.updated(response);
		this._success = false;
		await this.prereconcile();
		return () => {
			this.postreconcile();
			this.commitRevisionBaseline({ clearUnsaved: true });
		};
	}

	async applyRevision(response) {
		const commit = await this.prepareRevision(response);
		commit();
	}

	/**
	 * @testable true
	 * @pair forms:autofill-review
	 */
	async prepareLocalRevision(
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
		await this.updated(local.response);
		this._success = false;
		await this.prereconcile();

		return () => {
			this._skipQueuedRestore = true;
			try {
				this.postreconcile();
				this._restoreQueuedFiles(local.state);
			} finally {
				this._skipQueuedRestore = false;
			}

			if (remoteSnapshot !== null) this._revisionBaseline = remoteSnapshot;
			this._baselineSubmission = structuredClone(response.submission ?? {});
			if (wasQueued) {
				this.form?.queued();
			} else if (wasUnsaved || markUnsaved) {
				this.markUnsavedState();
			} else {
				this.commitRevisionBaseline({ clearUnsaved: true });
			}
			return local;
		};
	}

	async applyLocalRevision(response, options = {}) {
		const commit = await this.prepareLocalRevision(response, options);
		return commit();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.mjs::test_form_submit_is_blocked_by_schema_migration_but_not_autofill
	 * @matrix deferred-jobs forms submission : deliberate-submit form-lock no-live-sync
	 */
	async prepareSubmit(options) {
		if (this.deferredLocked) return false;
		return (await this.form?._subForm?.prepareSubmit?.(options)) ?? true;
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
	 * @tests tests_js/test_029_core_startup.mjs::test_offline_queue_does_not_block_initial_form_render
	 * @pair forms:queue-independent-initial-render
	 */
	async init() {
		if (
			this.target?.hasAttribute("lp-load") &&
			!this.target.hasAttribute("loaded")
		)
			return;
		await this._initForm();
		this.commitRevisionBaseline();
		this.initialized = true;
		this.target.setAttribute("initialized", "");
		const queue = this.view?.offlineQueue;
		if (
			typeof queue?.presentFor === "function" &&
			typeof this.handleOfflineQueue === "function"
		) {
			void queue.presentFor(this).catch((error) => {
				this.view?.reportStartupError?.(
					error,
					this.target,
					"offline-conflict-restore",
				);
			});
		}
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
			if (
				["form-generation", "form-revision", "reviewed-operation"].includes(
					control.name,
				)
			)
				continue;
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

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.mjs::test_active_deferred_form_waits_for_root_operation_scan
	 * @matrix deferred-jobs : form-lock reload
	 */
	async _initForm({ replace = true } = {}) {
		if (replace && this.initialTarget) {
			const visible = this.target?.dataset.visible;
			if (visible !== undefined) {
				this.initialTarget.dataset.visible = visible;
			}
			this.target.replaceWith(this.initialTarget);
			this.target = this.initialTarget;
			this.initialTarget = this.target.cloneNode(true);
		} else if (!this.initialTarget) {
			this.initialTarget = this.target.cloneNode(true);
		}
		this.target._lp_widget = this;
		this.form = new FormController(this);
		await this.form.init();
		if (this.target.dataset.formState) installReviewBar(this);
		if (
			this.target.dataset.migrationNotice &&
			this.target.dataset.migrationNotice !== "[]"
		)
			installMigrationNotice(this);
		if (this.target.dataset.formGeneration !== undefined) {
			const generation = document.createElement("input");
			generation.type = "hidden";
			generation.name = "form-generation";
			generation.value = this.target.dataset.formGeneration;
			this.target.append(generation);
		}
		this.target.addEventListener("click", this._click);
		const hasDeferredOperation =
			this.target.matches?.("[data-operation]") ||
			this.target.querySelector?.("[data-operation]");
		if (hasDeferredOperation) {
			const manager = await this.view?.ensureDeferredOperations?.();
			manager?.scan(this.target);
		}
		this.initialized = true;
		this.loaded = this.target.hasAttribute("loaded");
		this.target.setAttribute("initialized", "");
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.mjs::test_direct_form_controls_clear_inputs_and_textareas
	 * @matrix forms : clear direct-fields
	 */
	_click(e) {
		if (this.readonly) return;

		const element = e.target.closest(".form-element");
		const role = e.target.closest("[data-role]")?.dataset.role;
		if (role !== "edit" && role !== "clear") return;

		e.preventDefault();
		e.stopPropagation();

		if (role === "edit") {
			void withTransition(
				() => {
					element.dataset.mode = "edit";
				},
				{ label: "form:edit-field" },
			);
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

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.mjs::test_migration_notice_survives_form_replacement_and_discard
	 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_saved_conversion_runs_after_save_and_preserves_originals
	 * @matrix form-migration : informational-notice
	 */
	async prepareReset(options = {}) {
		if (this._preparingReset) return this._preparingReset;
		if (this._preparedReset) return;
		const pending = this._prepareReset(options);
		this._preparingReset = pending;
		try {
			await pending;
		} finally {
			if (this._preparingReset === pending) this._preparingReset = null;
		}
	}

	async _prepareReset({
		nextTarget = (this.initialTarget || this.target).cloneNode(true),
		staged = {},
		beforeInit = null,
		afterInit = null,
	} = {}) {
		if (this._preparedReset) return;
		const epoch = this._resetEpoch;

		const visible = this.target?.dataset.visible;
		if (visible !== undefined) nextTarget.dataset.visible = visible;

		const stagedState = {
			target: nextTarget,
			initialTarget: null,
			form: null,
			initialized: false,
			loaded: this.loaded,
			destroyables: [],
			_migrationNotice: null,
			_reviewBar: null,
			...staged,
		};
		let adopted = false;
		const stagedWidget = new Proxy(this, {
			get(target, property, receiver) {
				if (!adopted && Object.hasOwn(stagedState, property)) {
					return stagedState[property];
				}
				return Reflect.get(target, property, receiver);
			},
			set(target, property, value) {
				if (!adopted) {
					stagedState[property] = value;
					return true;
				}
				return Reflect.set(target, property, value);
			},
		});
		this._preparingState = stagedState;
		try {
			await beforeInit?.(stagedWidget);
			if (epoch !== this._resetEpoch) return;
			await stagedWidget._initForm({ replace: false });
			if (epoch !== this._resetEpoch) return;
			await afterInit?.(stagedWidget);
			if (epoch !== this._resetEpoch) return;
			this._preparedReset = {
				adopt: Object.keys(stagedState),
				state: stagedState,
				revisionBaseline: stagedWidget.revisionSnapshot(),
				baselineSubmission: structuredClone(
					stagedWidget.form?.renderer?._packageSubmission?.() ??
						stagedWidget.submission ??
						{},
				),
				activate: () => {
					adopted = true;
				},
			};
		} finally {
			if (this._preparedReset?.state !== stagedState)
				this._destroyFormState(stagedState);
			if (this._preparingState === stagedState) this._preparingState = null;
		}
	}

	commitReset() {
		if (!this._preparedReset) return false;
		const { adopt, state, revisionBaseline, baselineSubmission, activate } =
			this._preparedReset;
		this._preparedReset = null;
		const previousTarget = this.target;
		const previousInert = this._replacementInert;
		const visible = previousTarget?.dataset.visible;
		if (visible !== undefined) state.target.dataset.visible = visible;

		this.clearUnsavedState();
		this.destroy();
		if (previousTarget !== state.target)
			previousTarget.replaceWith(state.target);
		for (const property of adopt) this[property] = state[property];
		if (previousInert != null) this.target.inert = previousInert;
		activate?.();
		this.target._lp_widget = this;
		this._revisionBaseline = revisionBaseline;
		this._baselineSubmission = baselineSubmission;
		return true;
	}

	discardPreparedReset() {
		this._resetEpoch = (this._resetEpoch || 0) + 1;
		if (this._preparingState) this._destroyFormState(this._preparingState);
		if (this._preparedReset) this._destroyFormState(this._preparedReset.state);
		this._preparedReset = null;
	}

	_destroyFormState(state) {
		state._reviewBar?.destroy();
		state._reviewBar = null;
		state._migrationNotice?.destroy();
		state._migrationNotice = null;
		state.form?.destroy?.();
		state.destroyables?.forEach((destroyable) => {
			destroyable.destroy?.();
		});
		state.destroyables = [];
	}

	async reset() {
		await this.prepareReset();
		this.commitReset();
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
	 * @tests tests_js/test_032_task_settings_lifecycle.mjs::test_form_response_metadata_stays_with_renderer_widget
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_adding_form_from_task_settings_preserves_widget_identity
	 * @matrix forms : schema-ownership sibling-widgets
	 * @matrix tasks : attach-form merged-submission widget-identity
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
			this._replacementVersion = (this._replacementVersion || 0) + 1;
		}
		if (ownsRendererState && Object.hasOwn(response, "schema")) {
			this.schema = response.schema;
		}
		if (ownsRendererState && Object.hasOwn(response, "submission")) {
			this.submission = response.submission;
		}
		if (
			ownsRendererState &&
			Object.hasOwn(response, "form_state") &&
			this.initialTarget
		) {
			const operation = currentReviewOperation(
				this,
				response.form_state.operation,
			);
			this.initialTarget.dataset.formState = JSON.stringify({
				...response.form_state,
				operation,
			});
			if (operation?.key)
				this.lockDeferredOperation({
					operation: operation.key,
					revision: operation.revision,
					scope: operation.scope,
					blocks_edit: operation.blocks_edit,
					status: operation,
				});
		}
		if (
			ownsRendererState &&
			Object.hasOwn(response, "generation") &&
			this.initialTarget
		)
			this.initialTarget.dataset.formGeneration = String(response.generation);
		if (
			ownsRendererState &&
			Object.hasOwn(response, "migration_notice") &&
			this.initialTarget
		)
			this.initialTarget.dataset.migrationNotice = JSON.stringify(
				response.migration_notice,
			);
	}

	async prereconcile() {
		if (this._replacementPromise) return this._replacementPromise;
		if (!this._updated) return;
		if (this._preparedReset?.version === this._replacementVersion) return;
		this._replacementInert ??= Boolean(this.target.inert);
		this.target.inert = true;
		const pending = (async () => {
			let preparedVersion;
			do {
				preparedVersion = this._replacementVersion;
				this.discardPreparedReset();
				await this.prepareReset();
				if (this._preparedReset) this._preparedReset.version = preparedVersion;
			} while (preparedVersion !== this._replacementVersion);
		})();
		this._replacementPromise = pending;
		try {
			await pending;
		} catch (error) {
			this._restoreInteractivity();
			throw error;
		} finally {
			if (this._replacementPromise === pending) this._replacementPromise = null;
		}
	}

	_restoreInteractivity() {
		if (this._replacementInert == null) return;
		this.target.inert = this._replacementInert;
		this._replacementInert = null;
	}

	postreconcile() {
		const updated = this._updated;
		if (!this._created && !updated) return;
		if (
			updated &&
			(this._replacementPromise ||
				(this._preparedReset?.version !== undefined &&
					this._preparedReset.version !== this._replacementVersion))
		) {
			this.modified = true;
			return;
		}

		this._created = false;
		this._updated = false;

		if (updated) {
			this.commitReset();
			this._restoreInteractivity();
			if (this.visible) this.target.dataset.visible = "true";
		}

		if (this._success) {
			this.form?.success();
			this._success = false;
		}
	}

	destroy() {
		this.discardPreparedReset();
		this._restoreInteractivity();
		this._reviewBar?.destroy();
		this._reviewBar = null;
		this._migrationNotice?.destroy();
		this._migrationNotice = null;
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
