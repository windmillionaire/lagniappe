/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=be396a6a';
import { InputElement } from './input.js?v=be396a6a';
import { s as sections } from './sections.js?v=be396a6a';
import { S as SectionToggle } from './sectionToggle.js?v=be396a6a';
import { TextareaElement } from './textarea.js?v=be396a6a';
import './foundation.js?v=be396a6a';
import './upstreamUnavailable.js?v=be396a6a';
import './connectivity.js?v=be396a6a';
import './baseForm.js?v=be396a6a';
import './icons.js?v=be396a6a';
import './primitives.js?v=be396a6a';
import './styles.js?v=be396a6a';
import './loader.js?v=be396a6a';
import './baseElement.js?v=be396a6a';
import './formatting.js?v=be396a6a';
import './baseUpload.js?v=be396a6a';
import './buttons.js?v=be396a6a';
import './dropdown.js?v=be396a6a';
import './combobox.js?v=be396a6a';
import './facets.js?v=be396a6a';
import './remote.js?v=be396a6a';
import './queryLifecycle.js?v=be396a6a';
import './results.js?v=be396a6a';
import './storage.js?v=be396a6a';
import './submitter.js?v=be396a6a';

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
