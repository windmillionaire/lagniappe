import { SearchBox } from "../../elements/combobox/search.ts";
import type { IndependentDocument } from "../../elements/editor/independent.ts";
import { EntityMenu } from "../../elements/entityMenu.ts";
import { directUpload } from "../../shared/directUpload.ts";
import {
	captureError,
	connectivity,
	DeleteModal,
	generateElementId,
	HelpModal,
	OfflineModal,
	request,
} from "../../shared/index.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { FormFieldSchema, FormSchema } from "../../types/forms.d.ts";
import { FormChangeStatus } from "./changeStatus.ts";
import type { Condition } from "./conditions/base.ts";
import { loadCondition } from "./conditions/loader.ts";
import type { ConditionName } from "./config.ts";
import { BuilderDraft } from "./draft.ts";
import { fieldKind, needsMigration, repairConditions } from "./migrations.ts";
import { ComponentsPanel } from "./panels/components.ts";
import { ConditionPanel } from "./panels/condition.ts";
import { ElementSettings } from "./panels/elementSettings.ts";
import { FormSettings } from "./panels/formSettings.ts";
import { Header } from "./panels/header.ts";
import { ModelElement, ModelPanel } from "./panels/model.ts";

import type {
	ConversionCatalog,
	DraftAttempt,
	DraftBootstrap,
	DraftCopyResponse,
	DraftState,
	PendingChange,
} from "./types.ts";

interface DraftImageUpload {
	token: string;
	input_name: string;
	filename: string;
	content_type: string;
	size: number;
	generation?: string | number;
	path?: string;
}

interface DraftImage {
	file: File;
	fieldId: string;
	url: string;
	uploads: Map<string, DraftImageUpload>;
}

export interface BuilderElement {
	item: HTMLElement;
	schema: FormFieldSchema;
	settings: HTMLElement[];
	conditions?: Partial<Record<ConditionName, Condition>>;
	destroy?(): void;
}

interface BuilderSyncOptions {
	hidden?: boolean;
	blurred?: boolean;
	blurredAt?: number | null;
}

class FormBuilder {
	declare elt: HTMLElement & { _lp_view?: FormBuilder };
	declare _destroyed: boolean;
	declare elements: Map<string, BuilderElement>;
	declare _independentDocuments: Set<IndependentDocument>;
	declare images: Map<string, DraftImage>;
	declare _restoringDraft: boolean;
	declare bootstrap: DraftBootstrap | null;
	declare htmlFields: Record<string, string>;
	declare conversionInstructions: Record<string, string>;
	declare conversionCatalog: ConversionCatalog | null;
	declare draft: BuilderDraft | null;
	declare selectedElement: BuilderElement | null | undefined;
	declare schemaElt: HTMLInputElement;
	declare key: string;
	declare offlineIndicator: HTMLElement | null;
	declare online: boolean;
	declare hidden: boolean;
	declare blurred: boolean;
	declare blurredAt: number | null;
	declare EntityMenu: EntityMenu;
	declare SearchBox: SearchBox | null;
	declare offlineModal: OfflineModal | null;
	declare _searchPromise: Promise<SearchBox | null> | null;
	declare changeStatus?: FormChangeStatus;
	declare pendingChange?: PendingChange | null;
	declare _copyAttempt?: DraftAttempt | null;
	declare components: ComponentsPanel;
	declare model: ModelPanel;
	declare settings: ElementSettings;
	declare conditions: ConditionPanel;
	declare header: Header;
	declare formSettings: FormSettings;
	declare click: (event: MouseEvent) => void;
	declare keydown: (event: KeyboardEvent) => void;
	declare beforeUnload: (event: BeforeUnloadEvent) => void;

	constructor(node: HTMLElement) {
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
		this.conversionInstructions = structuredClone(
			this.bootstrap?.conversion_instructions || {},
		);
		this.conversionCatalog = JSON.parse(
			document.getElementById("builder-conversions")?.textContent || "null",
		);
		if (this.bootstrap) {
			const { baseline, pending_change: _pending, ...state } = this.bootstrap;
			this.draft = new BuilderDraft(state, baseline);
		} else this.draft = null;
		this.selectedElement = null;
		const schemaElt = document.querySelector<HTMLInputElement>(
			'input[name="schema"]',
		);
		if (!schemaElt) throw new Error("Missing builder schema input");
		this.schemaElt = schemaElt;
		const key = node.dataset.key;
		if (!key) throw new Error("Missing builder form key");
		this.key = key;
		this.offlineIndicator = document.querySelector<HTMLElement>(
			'[data-role="offline"]',
		);
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.blurred = false;
		this.blurredAt = null;
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
		await this.formSettings.init();
		if (this._destroyed) return this;
		if (this.bootstrap?.pending_change)
			this.setPendingChange(this.bootstrap.pending_change);

		this.offlineModal = new OfflineModal(this, this.offlineIndicator);
		this.offlineModal.enable();
		this.offline(!this.online);

		document.addEventListener("click", this.click);
		document.addEventListener("keydown", this.keydown);
		window.addEventListener("beforeunload", this.beforeUnload);
		this.refreshDraftControls();
		void this.header.syncMobilePreview?.();
		this.elt._lp_view = this;

		this._searchPromise = this._initSearch().catch((error) => {
			captureError(error, this.elt, { context: "builder-search-startup" });
			return null;
		});
		this.elt.setAttribute("initialized", "");
		return this;
	}

	async _initSearch() {
		const search = document.querySelector<HTMLElement>("[lp-search]");
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

	async sync({
		hidden = document.hidden,
		blurred = false,
		blurredAt = null,
	}: BuilderSyncOptions = {}) {
		const wasOnline = this.online;
		const wasInactive = this.hidden || !wasOnline;
		const visibleBlur = Boolean(hidden && blurred);
		if (visibleBlur && !this.blurred) this.blurredAt = blurredAt ?? Date.now();
		else if (!visibleBlur) this.blurredAt = null;
		this.hidden = hidden;
		this.blurred = visibleBlur;
		this.online = connectivity.online;
		this.offline(!this.online);
		const polling = this.changeStatus?.polling;
		if (hidden || !this.online) {
			if (visibleBlur && this.online)
				polling?.blur(this.blurredAt ?? undefined);
			else polling?.pause();
		}
		// A request started before leaving may still report the job as pending.
		else if (wasInactive) await polling?.trigger(null, { fresh: true });
		else await polling?.resume();
		if (this.online && (hidden || !wasOnline)) {
			await this.flushIndependentDocuments({ keepalive: hidden });
		}
	}

	registerIndependentDocument<T extends IndependentDocument>(document: T) {
		this._independentDocuments.add(document);
		return document;
	}

	unregisterIndependentDocument(document: IndependentDocument) {
		this._independentDocuments.delete(document);
	}

	async flushIndependentDocuments(options: { keepalive?: boolean } = {}) {
		const results = await Promise.allSettled(
			[...this._independentDocuments].map((document) =>
				Promise.resolve().then(() => document.flush(options)),
			),
		);
		return results.every(
			(result) => result.status === "fulfilled" && result.value === true,
		);
	}

	offline(offline: boolean) {
		const search = document.querySelector<HTMLElement>("[lp-search]");
		if (this.offlineIndicator) {
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
			this.offlineIndicator.setAttribute(
				"aria-hidden",
				offline ? "false" : "true",
			);
		}
		if (search) search.dataset.visible = offline ? "false" : "true";
		const saveButton = this.header.saveButton;
		if (saveButton) {
			// Keep the control in the tab order through health transitions.
			const saving = saveButton.getAttribute("aria-busy") === "true";
			saveButton.dataset.visible = "true";
			saveButton.setAttribute(
				"aria-disabled",
				String(
					Boolean(
						offline ||
							saving ||
							this.pendingChange ||
							saveButton.dataset.saved === "true",
					),
				),
			);
		}
	}

	updateSchema(silent = false, group: string | null = null) {
		const schemas = Array.from(this.elements.values()).map(
			(element) => element.schema,
		);
		if (!silent && repairConditions(schemas))
			this.header.message(
				"Conditions that depended on removed or incompatible choices were removed from this draft.",
				{ persistent: true },
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

	get schema(): FormSchema {
		return Array.from(this.elements.values(), (element) =>
			structuredClone(element.schema),
		);
	}

	setPendingChange(change: PendingChange | null) {
		if (change) this.changeStatus ??= new FormChangeStatus(this);
		this.changeStatus?.show(change);
	}

	captureDraft(): DraftState {
		const instructions = Object.fromEntries(
			Object.entries(this.conversionInstructions || {}).filter(
				([id, value]) => {
					const source = this.savedField(id);
					const target = this.schema.find((field) => field.id === id);
					return (
						value &&
						source &&
						target &&
						this.conversionCatalog?.rules[fieldKind(source)]?.[
							fieldKind(target)
						] === "ai"
					);
				},
			),
		);
		return {
			name: this.header.nameHidden.value,
			schema: this.schema,
			form_type: this.elt.dataset.formType,
			html_fields: structuredClone(this.htmlFields),
			selected_id: this.selectedElement?.schema.id || null,
			...(Object.keys(instructions).length
				? { conversion_instructions: instructions }
				: {}),
		};
	}

	setHtml(fieldId: string, html: string) {
		this.htmlFields[fieldId] = this.canonicalHtml(html);
		if (this.draft?.updateHtml(fieldId, this.htmlFields[fieldId]))
			this.refreshDraftControls();
	}

	canonicalHtml(html: string) {
		for (const [id, image] of this.images)
			html = html.replaceAll(image.url, `draft-image:${id}`);
		return html;
	}

	previewHtml(html: string) {
		for (const [id, image] of this.images)
			html = html.replaceAll(`draft-image:${id}`, image.url);
		return html;
	}

	addDraftImage(fieldId: string, file: File) {
		const id = crypto.randomUUID();
		const url = URL.createObjectURL(file);
		this.images.set(id, { file, fieldId, url, uploads: new Map() });
		return url;
	}

	pruneImages() {
		const draft = this.draft;
		if (!draft) return;
		const states = [
			draft.state,
			...draft.past,
			...draft.future,
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

	async draftPayload(state: DraftState, route: string, saveId: string) {
		const draft = this.draft;
		if (!draft) throw new Error("The builder draft is unavailable");
		const data = new FormData();
		data.set("name", state.name);
		data.set("schema", JSON.stringify(state.schema));
		if (needsMigration(draft.saved.schema, state.schema))
			data.set(
				"migration",
				JSON.stringify({
					version: this.conversionCatalog?.version || 1,
					clear_invalid: true,
					instructions: state.conversion_instructions || {},
				}),
			);
		data.set("html_fields", JSON.stringify(state.html_fields));
		data.set("baseline", draft.baseline || "");
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
					const session = await directUpload.createSession({
						route,
						file: image.file,
						inputName,
						replaceErrorPage: false,
					});
					const metadata = await directUpload.upload({
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
		const undo = this.elt.querySelector<HTMLButtonElement>(
			"[data-role='undo-draft']",
		);
		const redo = this.elt.querySelector<HTMLButtonElement>(
			"[data-role='redo-draft']",
		);
		if (undo) undo.disabled = !this.draft.past.length;
		if (redo) redo.disabled = !this.draft.future.length;
	}

	restoreDraft({ preserveFocus = false } = {}) {
		const state = this.draft?.state;
		if (!state) return;
		const active = document.activeElement as
			| HTMLInputElement
			| HTMLTextAreaElement
			| null;
		const condition = this.conditions.condition;
		const dialog =
			preserveFocus && condition?.key
				? {
						key: condition.key,
						index: condition.index,
						fieldId: condition.element.schema.id,
						setting: structuredClone(condition.setting ?? null),
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
			active?.name
				? {
						name: active.name,
						start: active.selectionStart,
						end: active.selectionEnd,
					}
				: null;
		this._restoringDraft = true;
		this.conditions.hide();
		this.header.closePreview();
		const retainedDocuments = new Map<string, Condition>();
		this.elements.forEach((element) => {
			const survives = state.schema.some(
				(field) => field.id === element.schema.id && field.type === "html",
			);
			for (const [name, condition] of Object.entries(
				element.conditions || {},
			)) {
				if (name === "html" && survives)
					retainedDocuments.set(element.schema.id, condition);
				else condition.destroy?.();
			}
		});
		this.pruneImages();
		this.elements.clear();
		this.model.panel.replaceChildren();
		this.model.defaultPanel.replaceChildren();
		this.selectedElement = null;
		this.htmlFields = structuredClone(state.html_fields);
		this.conversionInstructions = structuredClone(
			state.conversion_instructions || {},
		);
		this.header.nameHidden.value = state.name;
		this.header.nameInput.value = state.name;
		this.header.nameDisplay.textContent = state.name;
		for (const field of state.schema) {
			const item = this.createElement(structuredClone(field));
			const documentCondition = retainedDocuments.get(field.id);
			const element = this.elements.get(field.id);
			if (documentCondition && element) {
				documentCondition.element = element;
				element.conditions = { html: documentCondition };
				element.destroy = () =>
					Object.values(element.conditions ?? {}).forEach((condition) => {
						condition.destroy();
					});
				const draftDocument = documentCondition.document;
				const editor = draftDocument?.editor;
				const html = this.previewHtml(state.html_fields[field.id] || "");
				if (
					draftDocument &&
					editor &&
					this.canonicalHtml(editor.getHTML()) !== state.html_fields[field.id]
				) {
					editor.commands.setContent(html, { emitUpdate: false });
					draftDocument._lastFlushedContent = draftDocument._currentContent();
				}
			}
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
					panel.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
						"input, textarea",
					),
				).find((control) => control.name === inputFocus.name);
				input?.focus();
				if (input?.setSelectionRange && inputFocus.start !== null)
					input.setSelectionRange(inputFocus.start, inputFocus.end);
			});
		if (dialog && this.elements.has(dialog.fieldId)) {
			this.selectElement(dialog.fieldId);
			return this.showCondition(
				dialog.key,
				dialog.index ?? undefined,
				dialog.setting,
			).then(restoreInput);
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

	async prepareGeneratedDocuments(htmlFields?: Record<string, string>) {
		const { default: HtmlEditor } = await import("./conditions/html.ts");
		for (const [id, html] of Object.entries(htmlFields || {})) {
			const element = this.elements.get(id);
			if (
				this._destroyed ||
				element?.schema.type !== "html" ||
				this.htmlFields[id] === html
			)
				continue;
			element.conditions ??= {};
			if (!element.conditions.html) {
				const selected = this.selectedElement;
				this.selectedElement = element;
				element.conditions.html = new HtmlEditor(this);
				this.selectedElement = selected;
				element.destroy = () =>
					Object.values(element.conditions ?? {}).forEach((condition) => {
						condition.destroy();
					});
			}
			await element.conditions.html.init();
		}
	}

	undoDraft(redo = false) {
		const draft = this.draft;
		if (this.pendingChange || !draft) return;
		this.updateSchema();
		if (redo ? draft.redo() : draft.undo()) {
			this.restoreDraft();
		}
	}

	_keydown(event: KeyboardEvent) {
		if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
		if (
			(event.target as Element | null)?.closest(
				"input, textarea, select, [contenteditable='true']",
			)
		)
			return;
		if (event.key.toLowerCase() === "z" || event.key.toLowerCase() === "y") {
			event.preventDefault();
			this.undoDraft(event.shiftKey || event.key.toLowerCase() === "y");
		}
	}

	savedField(id: string) {
		return this.draft?.saved.schema.find((field) => field.id === id);
	}

	async createFormElements() {
		const recentSchema = this.schemaElt.value;
		const schemaJSON = this.bootstrap
			? JSON.stringify(this.bootstrap.schema)
			: recentSchema
				? recentSchema
				: this.elt.dataset.schema;
		const schema: FormSchema = schemaJSON ? JSON.parse(schemaJSON) : [];

		for (const elt of schema) {
			this.createElement(elt);
		}

		this.updateSchema(true);
	}

	_click(event: MouseEvent) {
		const target = event.target as Element | null;
		if (!target) return;
		const menuTrigger = target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest<HTMLElement>("[lp-menu]");
		if (menu && this.elt.contains(menu)) {
			event.preventDefault();
			event.stopPropagation();
			this.EntityMenu.toggle(menu);
			return;
		}

		const button = target.closest("button");
		const element = target.closest(".form-element");
		const preview = target.closest("#preview-panel");

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
		} else if (
			button?.dataset.role === "undo-draft" ||
			button?.dataset.role === "redo-draft"
		) {
			this.undoDraft(button.dataset.role === "redo-draft");
		} else if (button?.dataset.action === "copy-form") {
			this.copyForm(button);
		} else if (button?.getAttribute("lp-control") === "delete") {
			this._showDeleteModal(button);
		} else if (target.id === "form-name-display") {
			this.header.editFormName();
		}
	}

	async copyForm(button: HTMLButtonElement) {
		const draft = this.draft;
		if (this._destroyed || !draft || !button.dataset.route || button.disabled)
			return;

		const hadFocus = document.activeElement === button;
		let terminal = false;
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
		button.setAttribute("aria-busy", "true");
		this.header.clearMessage();
		try {
			this.updateSchema();
			draft.group = null;
			const state = this.captureDraft();
			const revision = draft.revision;
			this._copyAttempt ??= { state, id: crypto.randomUUID() };
			if (!draft.equal(state, this._copyAttempt.state))
				this._copyAttempt = { state, id: crypto.randomUUID() };
			const data = await this.draftPayload(
				state,
				button.dataset.route,
				this._copyAttempt.id,
			);
			const response = await request.post<DraftCopyResponse>(
				button.dataset.route,
				data,
				{
					replaceErrorPage: false,
				},
			);
			if (this._destroyed) return;
			if (response?.ok === true && response.url) {
				this._copyAttempt = null;
				if (
					draft.revision !== revision ||
					!draft.equal(this.captureDraft(), state)
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

	async _showDeleteModal(button: HTMLButtonElement) {
		if (this._destroyed) return;
		const modal = new DeleteModal(this, button);
		await modal.init();
	}

	async _showHelpModal(button: HTMLButtonElement) {
		if (this._destroyed) return;
		const modal = new HelpModal(this, button);
		await modal.init();
	}

	selectElement(id: string) {
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
		if (this.draft) this.draft.state.selected_id = null;
	}

	createElement(definition: Omit<FormFieldSchema, "id"> & { id?: string }) {
		const schema: FormFieldSchema = Object.assign(definition, {
			id: definition.id ?? generateElementId(definition.type),
		});
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
				label: element.schema.title ?? "",
				value: element.schema.id,
				details: {
					icon: element.schema.type,
					kind: "form",
					name: element.schema.title,
				},
			}));
	}

	async showCondition(
		name: ConditionName,
		index = -1,
		draftSetting: object | null = null,
	) {
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
				Object.values(element.conditions ?? {}).forEach((condition) => {
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
		const sortedMap = new Map<string, BuilderElement>();

		Array.from(this.model.defaults).forEach((element) => {
			const entry = this.elements.get(element.id);
			if (entry) sortedMap.set(element.id, entry);
		});

		Array.from(this.model.elements).forEach((element) => {
			const entry = this.elements.get(element.id);
			if (entry) sortedMap.set(element.id, entry);
		});

		this.elements = sortedMap;

		this.updateSchema();
	}

	removeElement() {
		const element = this.selectedElement;
		if (!element) return;
		delete this.htmlFields[element.schema.id];
		element.destroy?.();
		element.item.remove();
		this.elements.delete(element.schema.id);

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
		this.changeStatus?.destroy();
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
