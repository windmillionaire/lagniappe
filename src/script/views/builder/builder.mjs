import { SearchBox } from "../../elements/combobox/search";
import { EntityMenu } from "../../elements/entityMenu";
import { uploadElement } from "../../elements/upload";
import {
	captureError,
	connectivity,
	DeleteModal,
	generateElementId,
	HelpModal,
	OfflineModal,
	request,
	withTransition,
} from "../../shared";
import { loadCondition } from "./conditions/loader";
import { BuilderDraft } from "./draft";
import { ComponentsPanel } from "./panels/components";
import { ConditionPanel } from "./panels/condition";
import { ElementSettings } from "./panels/elementSettings";
import { FormSettings } from "./panels/formSettings";
import { Header } from "./panels/header";
import { ModelElement, ModelPanel } from "./panels/model";

/**
 * @testable true
 * @tests tests_js/test_046_async_query_lifecycle.py::test_builder_destroys_owned_search_modal_and_panels_during_startup
 * @matrix forms : builder-lifecycle late-publication listener-teardown
 */
class FormBuilder {
	constructor(node) {
		this._destroyed = false;
		this.elt = node;
		this.elements = new Map();
		this._independentDocuments = new Set();
		this.images = new Map();
		this._restoringDraft = false;
		this.bootstrap = JSON.parse(
			document.getElementById("builder-draft")?.textContent || "null",
		);
		this.htmlFields = structuredClone(this.bootstrap?.html_fields || {});
		this.draft = this.bootstrap
			? new BuilderDraft(this.bootstrap, this.bootstrap.baseline)
			: null;
		if (this.draft) {
			delete this.draft.state.baseline;
			delete this.draft.saved.baseline;
		}
		this.selectedElement = null;
		this.schemaElt = document.querySelector('input[name="schema"]');
		this.key = node.dataset.key;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.EntityMenu = new EntityMenu(this);
		this.SearchBox = null;
		this.offlineModal = null;
		this._searchPromise = null;

		this.components = new ComponentsPanel(this);
		this.model = new ModelPanel(this);
		this.settings = new ElementSettings(this);
		this.conditions = new ConditionPanel(this);
		this.header = new Header(this);
		this.formSettings = new FormSettings(this);

		this.click = this._click.bind(this);
		this.keydown = this._keydown.bind(this);
		this.beforeUnload = (event) => {
			if (this.draft?.dirty) {
				event.preventDefault();
				event.returnValue = "";
			}
		};
	}

	async init() {
		if (this._destroyed) return this;
		this.createFormElements();
		this.draft ??= new BuilderDraft(this.captureDraft());

		this.model.init();
		this.settings.init();
		this.formSettings.init();

		this.offlineModal = new OfflineModal(this, this.offlineIndicator);
		this.offlineModal.enable();
		this.offline(!this.online);

		document.addEventListener("click", this.click);
		document.addEventListener("keydown", this.keydown);
		window.addEventListener("beforeunload", this.beforeUnload);
		this.refreshDraftControls();
		this.elt._lp_view = this;

		this._searchPromise = this._initSearch().catch((error) => {
			captureError(error, this.elt, { context: "builder-search-startup" });
			return null;
		});
		this.elt.setAttribute("initialized", "");
		return this;
	}

	async _initSearch() {
		const search = document.querySelector("[lp-search]");
		if (!search || this._destroyed) return null;

		const searchBox = new SearchBox(search);
		this.SearchBox = searchBox;
		await searchBox.init();
		if (this._destroyed || this.SearchBox !== searchBox) {
			searchBox.destroy();
			return null;
		}
		return searchBox;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_sync_uses_shared_connectivity_without_orphaned_global_state
	 * @tests tests_js/test_045_browser_persistence.py::test_builder_owns_independent_editor_lifecycle_flushes
	 * @matrix editor html-field : teardown
	 * @matrix forms offline : builder-lifecycle
	 */
	async sync({ hidden = document.hidden } = {}) {
		const wasOnline = this.online;
		this.hidden = hidden;
		this.online = connectivity.online;
		this.offline(!this.online);
		if (this.online && (hidden || !wasOnline)) {
			await this.flushIndependentDocuments({ keepalive: hidden });
		}
	}

	registerIndependentDocument(document) {
		this._independentDocuments.add(document);
		return document;
	}

	unregisterIndependentDocument(document) {
		this._independentDocuments.delete(document);
	}

	async flushIndependentDocuments(options = {}) {
		const results = await Promise.allSettled(
			[...this._independentDocuments].map((document) =>
				Promise.resolve().then(() => document.flush(options)),
			),
		);
		return results.every(
			(result) => result.status === "fulfilled" && result.value === true,
		);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/builder/builder.mjs::FormBuilder.sync
	 * @reason builder connectivity controls are applied through the shared view lifecycle
	 */
	offline(offline) {
		const search = document.querySelector("[lp-search]");
		if (this.offlineIndicator) {
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
			this.offlineIndicator.setAttribute(
				"aria-hidden",
				offline ? "false" : "true",
			);
		}
		if (search) search.dataset.visible = offline ? "false" : "true";
		const saveButton = this.header.saveButton;
		if (saveButton) saveButton.dataset.visible = offline ? "false" : "true";
	}

	updateSchema(silent = false, group = null) {
		const schemas = Array.from(this.elements.values()).map(
			(element) => element.schema,
		);
		const schemaString = JSON.stringify(schemas);
		if (schemaString !== this.schemaElt.value) {
			this.schemaElt.value = schemaString;
			!silent && this.header.unsaved();
		}
		if (!silent && !this._restoringDraft && this.draft) {
			this.draft.record(this.captureDraft(), group);
			this.refreshDraftControls();
		}
	}

	get schema() {
		return Array.from(this.elements.values(), (element) =>
			structuredClone(element.schema),
		);
	}

	captureDraft() {
		return {
			name: this.header.nameHidden.value,
			schema: this.schema,
			form_type: this.elt.dataset.formType,
			html_fields: structuredClone(this.htmlFields),
			selected_id: this.selectedElement?.schema.id || null,
		};
	}

	setHtml(fieldId, html) {
		this.htmlFields[fieldId] = this.canonicalHtml(html);
		this.updateSchema(false, `html:${fieldId}`);
	}

	canonicalHtml(html) {
		for (const [id, image] of this.images)
			html = html.replaceAll(image.url, `draft-image:${id}`);
		return html;
	}

	previewHtml(html) {
		for (const [id, image] of this.images)
			html = html.replaceAll(`draft-image:${id}`, image.url);
		return html;
	}

	addDraftImage(fieldId, file) {
		const id = crypto.randomUUID();
		const url = URL.createObjectURL(file);
		this.images.set(id, { file, fieldId, url, uploads: new Map() });
		return url;
	}

	pruneImages() {
		const states = [
			this.draft.state,
			...this.draft.past,
			...this.draft.future,
			this.header._saveAttempt?.state,
			this._copyAttempt?.state,
		];
		const openEditors = new Set(
			Array.from(this.elements.values())
				.filter((element) => element.conditions?.html?.document?.editor)
				.map((element) => element.schema.id),
		);
		for (const [id, image] of this.images) {
			if (openEditors.has(image.fieldId)) continue;
			if (
				states.some((state) =>
					Object.values(state?.html_fields || {}).some((html) =>
						html.includes(`draft-image:${id}`),
					),
				)
			)
				continue;
			URL.revokeObjectURL(image.url);
			this.images.delete(id);
		}
	}

	async draftPayload(state, route, saveId) {
		const data = new FormData();
		data.set("name", state.name);
		data.set("schema", JSON.stringify(state.schema));
		data.set("html_fields", JSON.stringify(state.html_fields));
		data.set("baseline", this.draft.baseline || "");
		data.set("save_id", saveId);
		const manifest = [];
		const direct = [];
		for (const [id, image] of this.images) {
			if (
				!Object.values(state.html_fields).some((html) =>
					html.includes(`draft-image:${id}`),
				)
			)
				continue;
			const inputName = `draft-image-${id}`;
			manifest.push({ id, field_id: image.fieldId, input_name: inputName });
			if (image.file.size > 1024 * 1024) {
				let uploaded = image.uploads.get(route);
				if (!uploaded) {
					const session = await uploadElement.directUpload.createSession({
						route,
						file: image.file,
						inputName,
						replaceErrorPage: false,
					});
					const metadata = await uploadElement.directUpload.upload({
						file: image.file,
						sessionUrl: session.session_url,
						chunkSize: session.chunk_size,
					});
					uploaded = {
						token: session.token,
						input_name: inputName,
						filename: image.file.name,
						content_type: image.file.type,
						size: image.file.size,
						generation: metadata.generation,
						path: metadata.name,
					};
					image.uploads.set(route, uploaded);
				}
				direct.push(uploaded);
			} else data.append(inputName, image.file, image.file.name || "image.png");
		}
		data.set("image_manifest", JSON.stringify(manifest));
		if (direct.length) data.set("direct_uploads", JSON.stringify(direct));
		return data;
	}

	refreshDraftControls() {
		if (!this.draft) return;
		this.draft.dirty ? this.header.unsaved() : this.header.saved();
		const undo = this.elt.querySelector("[data-role='undo-draft']");
		const redo = this.elt.querySelector("[data-role='redo-draft']");
		if (undo) undo.disabled = !this.draft.past.length;
		if (redo) redo.disabled = !this.draft.future.length;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036b_builder_draft.py::test_builder_save_restores_unsubmitted_condition_buffer
	 * @matrix forms : draft-history stale-acknowledgement focus-recovery
	 */
	restoreDraft({ preserveFocus = false } = {}) {
		const active = document.activeElement;
		const condition = this.conditions.condition;
		const dialog =
			preserveFocus && condition?.key
				? {
						key: condition.key,
						index: condition.index,
						fieldId: condition.element.schema.id,
						setting: structuredClone(condition.setting),
					}
				: null;
		const editor = this.conditions.condition?.document?.editor;
		const htmlFocus =
			preserveFocus && editor?.view.dom.contains(active)
				? { from: editor.state.selection.from, to: editor.state.selection.to }
				: null;
		const inputFocus =
			preserveFocus &&
			(this.settings.panel.contains(active) ||
				this.conditions.panel.contains(active)) &&
			active.name
				? {
						name: active.name,
						start: active.selectionStart,
						end: active.selectionEnd,
					}
				: null;
		this._restoringDraft = true;
		this.conditions.hide();
		this.header.closePreview();
		this.elements.forEach((element) => {
			element.destroy?.();
		});
		this.elements.clear();
		this.pruneImages();
		this.model.panel.replaceChildren();
		this.model.defaultPanel.replaceChildren();
		this.selectedElement = null;
		const state = this.draft.state;
		this.htmlFields = structuredClone(state.html_fields);
		this.header.nameHidden.value = state.name;
		this.header.nameInput.value = state.name;
		this.header.nameDisplay.textContent = state.name;
		for (const field of state.schema) {
			const item = this.createElement(structuredClone(field));
			const isDefault = ["name", "description"].includes(field.id);
			if (isDefault)
				for (const input of item.querySelectorAll("input, textarea"))
					input.remove();
			const panel = isDefault ? this.model.defaultPanel : this.model.panel;
			panel.append(item);
		}
		this.updateSchema(true);
		this.model.show();
		if (state.selected_id && this.elements.has(state.selected_id))
			this.selectElement(state.selected_id);
		else {
			this.settings.deselectItem();
			this.formSettings.visible = true;
		}
		this.elt.dataset.expanded = "false";
		this._restoringDraft = false;
		this.refreshDraftControls();
		const restoreInput = () =>
			withTransition(() => {
				if (!inputFocus || this._destroyed) return;
				const panel = dialog ? this.conditions.panel : this.settings.panel;
				const input = Array.from(
					panel.querySelectorAll("input, textarea"),
				).find((control) => control.name === inputFocus.name);
				input?.focus();
				if (input?.setSelectionRange && inputFocus.start !== null)
					input.setSelectionRange(inputFocus.start, inputFocus.end);
			});
		if (dialog && this.elements.has(dialog.fieldId)) {
			this.selectElement(dialog.fieldId);
			return this.showCondition(dialog.key, dialog.index, dialog.setting).then(
				restoreInput,
			);
		}
		if (htmlFocus && this.selectedElement) {
			return this.showCondition("html").then(() => {
				const current = this.conditions.condition?.document?.editor;
				if (current && !this._destroyed)
					current.chain().focus().setTextSelection(htmlFocus).run();
			});
		}
		if (inputFocus) return restoreInput();
	}

	undoDraft(redo = false) {
		this.updateSchema();
		if (redo ? this.draft.redo() : this.draft.undo()) {
			this.restoreDraft();
			this.header.message(redo ? "Redid draft change." : "Undid draft change.");
		}
	}

	_keydown(event) {
		if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
		if (
			event.target.closest("input, textarea, select, [contenteditable='true']")
		)
			return;
		if (event.key.toLowerCase() === "z" || event.key.toLowerCase() === "y") {
			event.preventDefault();
			this.undoDraft(event.shiftKey || event.key.toLowerCase() === "y");
		}
	}

	savedField(id) {
		return this.draft?.saved.schema.find((field) => field.id === id);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
	 * @matrix forms : builder-defaults page-form task-form
	 */
	async createFormElements() {
		const recentSchema = this.schemaElt.value;
		const schemaJSON = this.bootstrap
			? JSON.stringify(this.bootstrap.schema)
			: recentSchema
				? recentSchema
				: this.elt.dataset.schema;
		const schema = schemaJSON ? JSON.parse(schemaJSON) : [];

		for (const elt of schema) {
			this.createElement(elt);
		}

		this.updateSchema(true);
	}

	_click(event) {
		const menuTrigger = event.target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest("[lp-menu]");
		if (menu && this.elt.contains(menu)) {
			event.preventDefault();
			event.stopPropagation();
			this.EntityMenu.toggle(menu);
			return;
		}

		const button = event.target.closest("button");
		const element = event.target.closest(".form-element");
		const preview = event.target.closest("#preview-panel");

		if (element && !preview) {
			this.selectElement(element.id);
		} else if (button?.hasAttribute("lp-help")) {
			this._showHelpModal(button);
		} else if (button?.dataset.role === "form-settings") {
			this.deselectElement();
			this.formSettings.visible = true;
		} else if (button?.id === "preview-toggle") {
			this.header.togglePreviewPanel();
		} else if (button?.dataset.role === "save-form") {
			this.header.saveForm();
		} else if (["undo-draft", "redo-draft"].includes(button?.dataset.role)) {
			this.undoDraft(button.dataset.role === "redo-draft");
		} else if (button?.dataset.action === "copy-form") {
			this.copyForm(button);
		} else if (button?.getAttribute("lp-control") === "delete") {
			this._showDeleteModal(button);
		} else if (event.target?.id === "form-name-display") {
			this.header.editFormName();
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
	 * @matrix forms : builder-copy navigation schema
	 * @pair entity-menu:builder-copy
	 */
	async copyForm(button) {
		if (this._destroyed || !button?.dataset.route || button.disabled) return;

		const hadFocus = document.activeElement === button;
		let terminal = false;
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
		button.setAttribute("aria-busy", "true");
		this.header.clearMessage();
		try {
			this.updateSchema();
			this.draft.group = null;
			const state = this.captureDraft();
			const revision = this.draft.revision;
			this._copyAttempt ??= { state, id: crypto.randomUUID() };
			if (!this.draft.equal(state, this._copyAttempt.state))
				this._copyAttempt = { state, id: crypto.randomUUID() };
			const data = await this.draftPayload(
				state,
				button.dataset.route,
				this._copyAttempt.id,
			);
			const response = await request.post(button.dataset.route, data, {
				replaceErrorPage: false,
			});
			if (this._destroyed) return;
			if (response?.ok === true && response.url) {
				this._copyAttempt = null;
				if (
					this.draft.revision !== revision ||
					!this.draft.equal(this.captureDraft(), state)
				) {
					this.header.message(
						"Copy created. Your later draft edits are still here. ",
						{ persistent: true },
					);
					const link = document.createElement("a");
					link.href = response.url;
					link.target = "_blank";
					link.rel = "noopener";
					link.textContent = "Open copy";
					link.className = "underline";
					this.header.notification.append(link);
					return;
				}
				window.removeEventListener("beforeunload", this.beforeUnload);
				window.location.assign(response.url);
				terminal = true;
				return;
			}
			if (!this.header.showConflict(response))
				this.header.message(response?.error || "Could not copy this form.", {
					persistent: true,
				});
		} catch (error) {
			captureError(error, button, { context: "builder-copy-form" });
			this.header.message("Could not copy this form. Try again.", {
				persistent: true,
			});
		} finally {
			if (!terminal && !this._destroyed && button.isConnected !== false) {
				button.disabled = false;
				button.setAttribute("aria-disabled", "false");
				button.removeAttribute("aria-busy");
				if (
					hadFocus &&
					(!document.activeElement ||
						document.activeElement === document.body ||
						document.activeElement === button)
				) {
					button.focus({ preventScroll: true });
				}
			}
		}
	}

	async _showDeleteModal(button) {
		if (this._destroyed) return;
		const modal = new DeleteModal(this, button);
		await modal.init();
	}

	async _showHelpModal(button) {
		if (this._destroyed) return;
		const modal = new HelpModal(this, button);
		await modal.init();
	}

	selectElement(id) {
		this.selectedElement = this.elements.get(id);
		if (this.draft) this.draft.state.selected_id = id;
		withTransition(() => {
			this.model.selectItem();
			this.settings.selectItem();
		});
	}

	deselectElement() {
		this.model.deselectItem();
		this.settings.deselectItem();
		this.selectedElement = null;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_table_creation_defaults_columns_for_unsaved_preview
	 * @matrix form-table forms : builder-defaults empty-columns unsaved-preview
	 */
	createElement(schema) {
		schema.id = schema.id ?? generateElementId(schema.type);
		if (schema.type === "html" && !Object.hasOwn(this.htmlFields, schema.id))
			this.htmlFields[schema.id] = "";
		if (schema.type === "table" && !Array.isArray(schema.columns)) {
			schema.columns = [];
		}
		const element = ModelElement[schema.type](schema);

		this.elements.set(schema.id, {
			item: element,
			schema: schema,
			settings: this.settings.create(schema),
		});

		return element;
	}

	getEligibleConditionTargets() {
		return Array.from(this.elements.values())
			.filter(
				(element) =>
					["checkbox", "radio", "select"].includes(element.schema.type) &&
					element !== this.selectedElement,
			)
			.map((element) => ({
				label: element.schema.title,
				value: element.schema.id,
				details: {
					icon: element.schema.type,
					kind: "form",
					name: element.schema.title,
				},
			}));
	}

	async showCondition(name, index = -1, draftSetting = null) {
		if (this._destroyed || this.conditions.loading) return;
		this.conditions.loading = true;
		const element = this.selectedElement;
		if (!element) {
			this.conditions.loading = false;
			return;
		}

		element.conditions ??= {};
		let condition = element.conditions[name] ?? null;
		let created = false;
		if (!condition) {
			condition = await loadCondition(this, name);
			created = true;
			if (this._destroyed || this.selectedElement !== element) {
				condition?.destroy?.();
				this.conditions.loading = false;
				return;
			}
			element.conditions[name] = condition;
		}

		if (!element.destroy) {
			element.destroy = () => {
				Object.values(element.conditions).forEach((condition) => {
					condition.destroy();
				});
			};
		}

		condition.index = index;
		condition.draftSetting = draftSetting;
		await condition.init();
		if (this._destroyed || this.selectedElement !== element) {
			if (created) {
				condition.destroy?.();
				delete element.conditions[name];
			}
			this.conditions.loading = false;
			return;
		}

		await withTransition(
			() => {
				if (this._destroyed || this.selectedElement !== element) return;
				this.conditions.open(condition);
			},
			{ label: "builder:show-condition" },
		);
	}

	updateSchemaOrder() {
		const sortedMap = new Map();

		Array.from(this.model.defaults).forEach((element) => {
			sortedMap.set(element.id, this.elements.get(element.id));
		});

		Array.from(this.model.elements).forEach((element) => {
			sortedMap.set(element.id, this.elements.get(element.id));
		});

		this.elements = sortedMap;

		this.updateSchema();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_delete_components
	 * @pair forms:builder-delete-components
	 */
	removeElement() {
		if (this.savedField(this.selectedElement.schema.id)) return;
		delete this.htmlFields[this.selectedElement.schema.id];
		if (this.selectedElement.destroy) this.selectedElement.destroy();
		this.selectedElement.item.remove();
		this.elements.delete(this.selectedElement.schema.id);

		this.selectedElement = null;
		this.updateSchema();
		this.pruneImages();
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.SearchBox?.destroy?.();
		this.SearchBox = null;
		this.offlineModal?.destroy?.();
		this.offlineModal = null;
		this.components.destroy();
		this.model.destroy();
		this.settings.destroy();
		this.conditions.destroy();
		this.header.destroy();
		this.formSettings.destroy();
		this.EntityMenu.destroy();

		this.elements.forEach((element) => {
			if (element.destroy) element.destroy();
		});
		this.elements.clear();
		this._independentDocuments.clear();
		for (const image of this.images.values()) URL.revokeObjectURL(image.url);
		this.images.clear();

		document.removeEventListener("click", this.click);
		document.removeEventListener("keydown", this.keydown);
		window.removeEventListener("beforeunload", this.beforeUnload);
		if (this.elt._lp_view === this) delete this.elt._lp_view;
	}
}

export default FormBuilder;
