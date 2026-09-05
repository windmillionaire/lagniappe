/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=ba683140';
import { InputElement } from './input.js?v=ba683140';
import { s as sections } from './sections.js?v=ba683140';
import { S as SectionToggle } from './sectionToggle.js?v=ba683140';
import { TextareaElement } from './textarea.js?v=ba683140';
import './foundation.js?v=ba683140';
import './upstreamUnavailable.js?v=ba683140';
import './connectivity.js?v=ba683140';
import './baseForm.js?v=ba683140';
import './icons.js?v=ba683140';
import './primitives.js?v=ba683140';
import './styles.js?v=ba683140';
import './loader.js?v=ba683140';
import './baseElement.js?v=ba683140';
import './formatting.js?v=ba683140';
import './baseUpload.js?v=ba683140';
import './buttons.js?v=ba683140';
import './dropdown.js?v=ba683140';
import './combobox.js?v=ba683140';
import './facets.js?v=ba683140';
import './remote.js?v=ba683140';
import './queryLifecycle.js?v=ba683140';
import './results.js?v=ba683140';
import './storage.js?v=ba683140';
import './submitter.js?v=ba683140';

/**
 * @testable infrastructure
 */
class CategoryForm extends FormElement {
	get nameElement() {
		return new InputElement(
			{ kind: "category", readonly: this.readonly },
			{
				id: "name",
				title: "Category Name",
				placeholder: "name this category...",
				input: "text",
			},
			this.target.dataset.name || "",
		).elt;
	}

	get descriptionElement() {
		return new TextareaElement(
			{
				kind: "category",
				readonly: this.readonly,
			},
			{
				id: "description",
				label: "Category Description",
				input: "textarea",
				placeholder: "describe this category...",
			},
			this.target.dataset.description || "",
		).elt;
	}

	get formSelectElement() {
		const target = this.target.querySelector('[data-action="select-form"]');
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}
}

/**
 * @testable true
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_update_category_info_from_tools
 * @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_category_viewer_opens_readonly_settings
 * @matrix categories : info-form labels readonly update
 */
class CategoryInfo extends CategoryForm {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Category",
			submitting: "Updating Category",
			submitted: "Category Updated",
			queued: "Queued Sync",
		};
	}

	offline({ data, method, route }) {
		return {
			id: `update:category:${this.key}`,
			action: "update",
			kind: "category",
			method,
			route,
			target_key: this.key,
			data,
		};
	}

	handleOfflineQueue({ phase, record }) {
		if (record?.kind !== "category" || record.target_key !== this.key) return;
		if (phase === "queued") {
			this.form?.queued();
			this.setEntityMetadata();
		}
		if (phase === "replayed") {
			this.form?.success();
			this.setEntityMetadata();
		}
	}

	get html() {
		return [this.nameElement, this.descriptionElement, this.formSelectElement];
	}

	postreconcile() {
		super.postreconcile();
		this.setEntityMetadata();
	}
}

/**
 * @testable false
 * @covered-by src/script/widgets/category.mjs::CreateCategory.html
 * @covered-by lagniappe/web/routes/categories/main.py::create
 * @reason category create behavior is split between rendered controls and submit route handling
 */
class CreateCategory extends CategoryForm {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Category",
			submitting: "Creating Category",
			submitted: "Category Created",
		};
	}

	async init() {
		this.target.dataset.mode = "manual";
		this.target.dataset.role = "generate";

		await super.init();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_form
	 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_category_form_explain_button
	 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_category_form_generate_toggle
	 * @matrix categories : ai-form attach-form explain-button manual-form
	 */
	get html() {
		const name = this.nameElement;
		const description = this.descriptionElement;
		name.dataset.role = "manual";
		description.dataset.role = "manual";

		return [
			sections.generateEntityForm(this),
			name,
			description,
			this.formSelectElement,
		];
	}
}

export { CategoryInfo, CreateCategory };
