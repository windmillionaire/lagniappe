/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b9107833';
import { InputElement } from './input.js?v=b9107833';
import { s as sections } from './sections.js?v=b9107833';
import { S as SectionToggle } from './sectionToggle.js?v=b9107833';
import { TextareaElement } from './textarea.js?v=b9107833';
import { r as request, c as captureError, w as withTransition } from './foundation.js?v=b9107833';
import './connectivity.js?v=b9107833';
import './formRepresentation.js?v=b9107833';
import './styles.js?v=b9107833';
import './modal.js?v=b9107833';
import './upstreamUnavailable.js?v=b9107833';
import './baseForm.js?v=b9107833';
import './icons.js?v=b9107833';
import './primitives.js?v=b9107833';
import './loader.js?v=b9107833';
import './baseElement.js?v=b9107833';
import './formatting.js?v=b9107833';
import './baseUpload.js?v=b9107833';
import './upload.js?v=b9107833';
import './buttons.js?v=b9107833';
import './dropdown.js?v=b9107833';
import './combobox.js?v=b9107833';
import './facets.js?v=b9107833';
import './remote.js?v=b9107833';
import './queryLifecycle.js?v=b9107833';
import './results.js?v=b9107833';
import './storage.js?v=b9107833';
import './submitter.js?v=b9107833';

/**
 * @testable infrastructure
 */
class PageForm extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.formSelect = null;
	}

	get submitGroup() {
		return this.target.querySelector("[data-role='submit-group']");
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

		const setSelected = (formId = null) => {
			section
				.querySelectorAll("[data-role='related-form']")
				.forEach((badge) => {
					badge.dataset.selected = Boolean(
						formId && badge.dataset.formId === formId,
					).toString();
				});
		};

		section.querySelectorAll("[data-role='related-form']").forEach((badge) => {
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
				if (e.detail?.name !== "form") return;

				const details = Object.values(e.detail.options || {})[0];
				setSelected(details?.id || null);
			},
			{ signal },
		);
		this.target.addEventListener(
			"change",
			(e) => {
				if (e.target?.name !== "form") return;

				setSelected(e.target.value || null);
			},
			{ signal },
		);

		setSelected(this.formSelect?.details?.id || null);

		this.destroyables.push({
			destroy: () => controller.abort(),
		});

		return section;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_category_to_page
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_remove_category_from_page
	 * @matrix pages : category-add category-remove
	 */
	get categoriesElement() {
		return this._facetElement('[data-role="categories"]');
	}

	get autofillElement() {
		return sections.autofill(this);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_photo_controls_toggle_and_remember_desktop_visibility
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_readonly_viewer_can_toggle_image_without_editing
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_image_changes_preserve_page_info_dom_and_draft
	 * @matrix pages : photo-prompt photo-visibility readonly desktop-tabs unsaved-preservation
	 */
	get prepend() {
		let imageControls = this.target.querySelector("[data-role='photo-prompt']");
		if (this.revisionPreview) {
			imageControls?.remove();
			imageControls = null;
		} else if (imageControls) {
			this.view._syncPhotoControls(undefined, imageControls);
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

	_facetElement(selector) {
		const target = this.target.querySelector(selector);
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		if (target.matches('[data-action="select-form"]')) {
			this.formSelect = control;
		}
		return control.elt;
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pageInfo.mjs::CreatePage
	 * @reason related-form badge parsing is private CreatePage UI plumbing
	 */
	_relatedFormDetails(badge) {
		try {
			return JSON.parse(badge.dataset.details || "{}");
		} catch {
			return {};
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_reads_page_without_page_editing_affordances
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_replay_reconciles_after_reload
 * @matrix pages : lp-offline permission-gates readonly
 */
class PageInfo extends PageForm {
	constructor(attributes) {
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

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pageInfo.mjs::PageInfo
	 * @reason detached page-info resets retain the form-selection listener
	 */
	async prepareReset(options = {}) {
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

	offline({ data, method, route }) {
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

	handleOfflineQueue({ phase, record }) {
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

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_switch_page_form
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_clear_page_info_form_selector_keeps_widget_stable
	 * @matrix pages : form-clear form-switch info-form
	 */
	async _changeForm(e) {
		if (!e.target.closest("[data-role='form-select']")) return;

		e.stopPropagation();

		const formSelect = this.initialTarget.querySelector(
			"[data-action='select-form']",
		);
		const preloadedForm = JSON.parse(formSelect?.dataset.preload || "{}");

		const selectedForm = Object.values(e.detail?.options || {})[0];

		if (!selectedForm?.id) return;
		if (selectedForm.id === preloadedForm?.id) return;

		this.target.classList.add("opacity-50", "pointer-events-none");
		const route = this.target.dataset.route;
		const params = new URLSearchParams();
		params.set("form", selectedForm.id);

		const response = await request.get(route, params);
		if (!this.view.successfulResponse(response, this.component)) {
			this.target.classList.remove("opacity-50", "pointer-events-none");
			captureError(new Error("Failed to replace form"), this.target, {
				requestedForm: selectedForm,
			});
			return;
		}
		this.schema = response.schema;
		this.submission = response.submission;
		this.initialTarget.dataset.formGeneration = String(
			response.generation || 0,
		);

		const nextFormSelect = this.initialTarget.querySelector(
			'[data-action="select-form"]',
		);
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

/**
 * @testable true
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_from_category_index
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_related_form_badge_selects_form
 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filters_hide_create_page_tool
 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_tools_dropdown_opens_new_page_form
 * @matrix pages : category-index create mobile-tools related-forms tool-switch
 * @matrix pages : required-name
 * @pair deferred-jobs:hosted-e2e
 */
class CreatePage extends PageForm {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Page",
			submitting: "Creating Page",
			submitted: "Page Created",
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pageInfo.mjs::CreatePage
	 * @reason page creation requires a name even when its fields come from an attached form
	 */
	async init() {
		await super.init();
		const name = this.target.querySelector("input[name='name']");
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
		const nameElement = this.target.querySelector("input[name='name']");
		if (this.visible && nameElement) nameElement.focus();
	}
}

export { CreatePage, PageForm, PageInfo };
