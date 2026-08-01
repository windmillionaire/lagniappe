/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b01d709d';
import { InputElement } from './input.js?v=b01d709d';
import { p as primitives } from './primitives.js?v=b01d709d';
import { s as sections } from './sections.js?v=b01d709d';
import { S as SectionToggle } from './sectionToggle.js?v=b01d709d';
import { TextareaElement } from './textarea.js?v=b01d709d';
import './baseForm.js?v=b01d709d';
import './request.js?v=b01d709d';
import './errors.js?v=b01d709d';
import './connectivity.js?v=b01d709d';
import './icons.js?v=b01d709d';
import './styles.js?v=b01d709d';
import './utilities.js?v=b01d709d';
import './loader.js?v=b01d709d';
import './baseElement.js?v=b01d709d';
import './formatting.js?v=b01d709d';
import './baseUpload.js?v=b01d709d';
import './buttons.js?v=b01d709d';
import './dropdown.js?v=b01d709d';
import './combobox.js?v=b01d709d';
import './facets.js?v=b01d709d';
import './endpoints.js?v=b01d709d';
import './results.js?v=b01d709d';
import './submitter.js?v=b01d709d';

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
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_info_readonly_fields_keep_labels
 * @features categories
 * @dimensions info-form update readonly labels
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
		return [
			this.nameElement,
			this.descriptionElement,
			this.formSelectElement,
			sections.attributes(this),
		];
	}

	async postreconcile() {
		await super.postreconcile();
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
	 * @features categories
	 * @dimensions manual-form attach-form ai-form explain-button
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
			sections.attributes(this),
		];
	}
}

/**
 * @testable true
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_explain_prompt_from_category_tools
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_submit_marks_form_successful
 * @features pages
 * @dimensions generate ai-form explain-button deferred-submit success-state
 */
class GeneratePages extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Generate Pages",
			submitting: "Generating Pages",
			submitted: "Pages Queued",
		};
		this.icon = "generate";
		this.formSelect = null;
		this.textarea = null;
	}

	get explainElement() {
		return this.target.querySelector("[data-explain]");
	}

	async init() {
		await super.init();
		this.textarea = this.target.querySelector('[name="user_description"]');

		this.textarea.addEventListener(
			"input",
			() => {
				this.explainElement.dataset.visible = "true";
			},
			{ once: true },
		);
	}

	get formSelectElement() {
		const target = this.target.querySelector('[data-action="select-form"]');
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}

	get html() {
		const userDescription = primitives.textarea({
			name: "user_description",
			rows: 6,
			label: "Details",
			placeholder: "Add details about the pages you'd like to generate",
			kind: "page",
		});

		const numberOfPages = primitives.input({
			name: "num_pages",
			type: "number",
			kind: "page",
			label: "Number of Pages",
		});

		return [userDescription, numberOfPages, this.formSelectElement];
	}

	success() {
		this.form?.success();
		this._success = false;
	}

	async postreconcile() {
		const created = this._created;
		await super.postreconcile();

		if (created) {
			this.success();
			this.target.querySelector("[name='num_pages']").value = 0;
			this.target.querySelector("[name='user_description']").value = "";
		}

		this.textarea.focus();
	}
}

export { CategoryInfo, CreateCategory, GeneratePages };
