/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b41d0cfc';
import { InputElement } from './input.js?v=b41d0cfc';
import { s as sections } from './sections.js?v=b41d0cfc';
import { S as SectionToggle } from './sectionToggle.js?v=b41d0cfc';
import { TextareaElement } from './textarea.js?v=b41d0cfc';
import './foundation.js?v=b41d0cfc';
import './upstreamUnavailable.js?v=b41d0cfc';
import './connectivity.js?v=b41d0cfc';
import './baseForm.js?v=b41d0cfc';
import './icons.js?v=b41d0cfc';
import './primitives.js?v=b41d0cfc';
import './styles.js?v=b41d0cfc';
import './loader.js?v=b41d0cfc';
import './baseElement.js?v=b41d0cfc';
import './formatting.js?v=b41d0cfc';
import './baseUpload.js?v=b41d0cfc';
import './buttons.js?v=b41d0cfc';
import './dropdown.js?v=b41d0cfc';
import './combobox.js?v=b41d0cfc';
import './facets.js?v=b41d0cfc';
import './remote.js?v=b41d0cfc';
import './queryLifecycle.js?v=b41d0cfc';
import './results.js?v=b41d0cfc';
import './storage.js?v=b41d0cfc';
import './submitter.js?v=b41d0cfc';

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
