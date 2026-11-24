import type { ComboboxOption } from "../elements/combobox/combobox.ts";
import { InputElement } from "../elements/input.ts";
import { sections } from "../elements/sections.ts";
import { SectionToggle } from "../elements/sectionToggle.ts";
import { TextareaElement } from "../elements/textarea.ts";
import { captureError, request } from "../shared/index.ts";
import { withTransition } from "../shared/transitions.ts";
import type { FormRevisionFields } from "../types/forms";
import type ViewComponent from "../views/base/component.ts";
import type Core from "../views/base/core.ts";
import type Page from "../views/page.ts";
import {
	type FormResetOptions,
	FormWidget,
	type FormWidgetSettings,
} from "./base/formWidget.ts";

type OfflineContext = Parameters<NonNullable<FormWidget["offline"]>>[0];
type QueueContext = Parameters<
	NonNullable<FormWidget["handleOfflineQueue"]>
>[0];
type FormSelection = CustomEvent<{
	name?: string;
	options?: Record<string, ComboboxOption>;
}>;

export class PageForm extends FormWidget {
	declare formSelect: ReturnType<typeof SectionToggle.facet> | null;
	declare view?: FormWidget["view"] & Partial<Pick<Page, "_syncPhotoControls">>;

	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.formSelect = null;
	}

	get submitGroup() {
		return this.target.querySelector<HTMLElement>("[data-role='submit-group']");
	}

	get nameElement() {
		if (this.schema?.find((elt) => elt.id === "name")) return null;

		return new InputElement(
			{ kind: "page", readonly: this.readonly },
			{
				input: "text",
				id: "name",
				title: "Name",
				placeholder: "name this page...",
			},
			this.target.dataset.name || "",
		).elt;
	}

	get descriptionElement() {
		if (this.schema?.find((elt) => elt.id === "description")) return null;

		return new TextareaElement(
			{ kind: "page", readonly: this.readonly },
			{
				input: "textarea",
				id: "description",
				title: "Description",
				placeholder: "describe this page...",
			},
			this.target.dataset.description || "",
		).elt;
	}

	get formSelectElement() {
		return this._facetElement('[data-action="select-form"]');
	}

	get relatedFormsElement() {
		const section = this.target.querySelector('[data-role="related-forms"]');
		if (!section || this.readonly) return section;

		const controller = new AbortController();
		const signal = controller.signal;

		const setSelected = (formId: string | null = null) => {
			section
				.querySelectorAll<HTMLElement>("[data-role='related-form']")
				.forEach((badge) => {
					badge.dataset.selected = Boolean(
						formId && badge.dataset.formId === formId,
					).toString();
				});
		};

		section
			.querySelectorAll<HTMLElement>("[data-role='related-form']")
			.forEach((badge) => {
				badge.addEventListener(
					"click",
					(e) => {
						e.preventDefault();
						e.stopPropagation();

						const details = this._relatedFormDetails(badge);
						if (!details?.id || !this.formSelect) return;

						this.formSelect.select?.values?.clear();
						this.formSelect.addOption(details);
						setSelected(details.id);
					},
					{ signal },
				);
			});

		this.target.addEventListener(
			"updated",
			(e) => {
				const detail = (e as FormSelection).detail;
				if (detail?.name !== "form") return;

				const details = Object.values(detail.options || {})[0];
				setSelected(details?.id || null);
			},
			{ signal },
		);
		this.target.addEventListener(
			"change",
			(e) => {
				const target = e.target as HTMLInputElement | null;
				if (target?.name !== "form") return;

				setSelected(target.value || null);
			},
			{ signal },
		);

		setSelected(this.formSelect?.details?.id || null);

		this.destroyables.push({
			destroy: () => controller.abort(),
		});

		return section;
	}

	get categoriesElement() {
		return this._facetElement('[data-role="categories"]');
	}

	get autofillElement() {
		return sections.autofill(this);
	}

	get prepend() {
		let imageControls = this.target.querySelector<HTMLElement>(
			"[data-role='photo-prompt']",
		);
		if (this.revisionPreview) {
			imageControls?.remove();
			imageControls = null;
		} else if (imageControls) {
			this.view?._syncPhotoControls?.(undefined, imageControls);
		}
		return [imageControls, this.nameElement, this.descriptionElement];
	}

	get append() {
		return [
			this.formSelectElement,
			this.categoriesElement,
			this.autofillElement,
		];
	}

	_facetElement(selector: string) {
		const target = this.target.querySelector<HTMLElement>(selector);
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		if (target.matches('[data-action="select-form"]')) {
			this.formSelect = control;
		}
		return control.elt;
	}

	_relatedFormDetails(badge: HTMLElement): ComboboxOption {
		try {
			return JSON.parse(badge.dataset.details || "{}");
		} catch {
			return {};
		}
	}
}

export class PageInfo extends PageForm {
	declare view: PageForm["view"] & Pick<Core, "successfulResponse">;
	declare component?: ViewComponent | null;

	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: `Update Page`,
			submitting: `Updating Page`,
			submitted: `Page Updated`,
			queued: "Queued Sync",
		};
		this._changeForm = this._changeForm.bind(this);
	}

	async init() {
		await super.init();
		this.target.addEventListener("updated", this._changeForm);
	}

	async prepareReset(options: FormResetOptions<this> = {}) {
		const afterInit = options.afterInit;
		await super.prepareReset({
			...options,
			afterInit: async (widget) => {
				await afterInit?.(widget);
				widget.target.addEventListener("updated", widget._changeForm);
			},
		});
	}

	async reset() {
		await this.prepareReset();
		this.commitReset();
	}

	offline({ data, method, route }: OfflineContext) {
		return {
			id: `update:page:${this.key}`,
			action: "update",
			kind: "page",
			method,
			route,
			target_key: this.key,
			data,
		};
	}

	handleOfflineQueue({ phase, record }: QueueContext) {
		if (record?.kind !== "page" || record.target_key !== this.key) return;
		if (phase === "queued") {
			this.form?.queued();
			this.setEntityMetadata();
		} else if (phase === "conflict") {
			this._offlineConflict = {
				record,
				response: record.conflictResponse,
			};
			return this.stageOfflineConflict();
		} else if (phase === "replayed") {
			this.form?.success();
			this.setEntityMetadata();
		}
	}

	async _changeForm(e: Event) {
		const target = e.target;
		if (
			!(target instanceof Element) ||
			!target.closest("[data-role='form-select']")
		)
			return;

		e.stopPropagation();

		const initialTarget = this.initialTarget;
		if (!initialTarget) return;
		const formSelect = initialTarget.querySelector<HTMLElement>(
			"[data-action='select-form']",
		);
		const preloadedForm: ComboboxOption = JSON.parse(
			formSelect?.dataset.preload || "{}",
		);

		const selectedForm = Object.values(
			(e as FormSelection).detail?.options || {},
		)[0];

		if (!selectedForm?.id) return;
		if (selectedForm.id === preloadedForm?.id) return;

		const route = this.target.dataset.route;
		if (!route) return;
		this.target.classList.add("opacity-50", "pointer-events-none");
		const params = new URLSearchParams();
		params.set("form", selectedForm.id);

		const response = await request.get<FormRevisionFields>(route, params);
		if (
			!this.view.successfulResponse(response, this.component ?? null) ||
			!response
		) {
			this.target.classList.remove("opacity-50", "pointer-events-none");
			captureError(new Error("Failed to replace form"), this.target, {
				requestedForm: selectedForm,
			});
			return;
		}
		this.schema = response.schema ?? null;
		this.submission = response.submission ?? null;
		initialTarget.dataset.formGeneration = String(response.generation || 0);

		const nextFormSelect = initialTarget.querySelector<HTMLElement>(
			'[data-action="select-form"]',
		);
		if (nextFormSelect)
			nextFormSelect.dataset.preload = JSON.stringify(selectedForm);
		await this.prepareReset();
		await withTransition(
			() => {
				this.commitReset();
				this.target.dataset.visible = "true";
			},
			{ label: "page-info:change-form" },
		);
	}

	postreconcile() {
		super.postreconcile();
		this.setEntityMetadata();
	}
}

export class CreatePage extends PageForm {
	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Create Page",
			submitting: "Creating Page",
			submitted: "Page Created",
		};
	}

	async init() {
		await super.init();
		const name =
			this.target.querySelector<HTMLInputElement>("input[name='name']");
		if (name) name.required = true;
	}

	get html() {
		return [
			this.nameElement,
			this.descriptionElement,
			this.formSelectElement,
			this.relatedFormsElement,
			this.categoriesElement,
			this.autofillElement,
		];
	}

	get prepend() {
		return [];
	}

	get append() {
		return [];
	}

	async prereconcile() {
		await super.prereconcile();
		if (this._created) await this.prepareReset();
	}

	postreconcile() {
		const created = this._created;
		if (created) this.commitReset();
		super.postreconcile();

		if (created) {
			this.form?.resetSubmitButton();
		}
		const nameElement =
			this.target.querySelector<HTMLInputElement>("input[name='name']");
		if (this.visible && nameElement) nameElement.focus();
	}
}
