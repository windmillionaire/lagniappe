import { SearchBox } from "../../elements/combobox/search";
import { EntityMenu } from "../../elements/entityMenu";
import {
	connectivity,
	DeleteModal,
	generateElementId,
	HelpModal,
	OfflineModal,
	request,
	withTransition,
} from "../../shared";
import { loadCondition } from "./conditions/loader";
import { ComponentsPanel } from "./panels/components";
import { ConditionPanel } from "./panels/condition";
import { ElementSettings } from "./panels/elementSettings";
import { FormSettings } from "./panels/formSettings";
import { Header } from "./panels/header";
import { ModelElement, ModelPanel } from "./panels/model";

/**
 * @testable false
 * @covered-by src/script/views/builder/builder.mjs::FormBuilder.createFormElements
 * @covered-by src/script/views/builder/panels/components.mjs::ComponentsPanel.init
 * @covered-by src/script/views/builder/panels/components.mjs::ComponentsPanel._click
 * @covered-by src/script/views/builder/panels/header.mjs::Header.saveForm
 * @reason builder behavior is owned by concrete initialization and panel action methods
 */
class FormBuilder {
	constructor(node) {
		this.elt = node;
		this.elements = new Map();
		this.selectedElement = null;
		this.schemaElt = document.querySelector('input[name="schema"]');
		this.key = node.dataset.key;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.EntityMenu = new EntityMenu(this);

		this.components = new ComponentsPanel(this);
		this.model = new ModelPanel(this);
		this.settings = new ElementSettings(this);
		this.conditions = new ConditionPanel(this);
		this.header = new Header(this);
		this.formSettings = new FormSettings(this);

		this.click = this._click.bind(this);
	}

	async init() {
		this.createFormElements();

		this.model.init();
		this.settings.init();
		this.formSettings.init();

		const offlineModal = new OfflineModal(this, this.offlineIndicator);
		offlineModal.enable();
		this.offline(!this.online);

		document.addEventListener("click", this.click);
		this.elt._lp_view = this;

		this._initSearch();
		this.elt.setAttribute("initialized", "");
		return this;
	}

	async _initSearch() {
		const search = document.querySelector("[lp-search]");
		if (search) {
			const searchBox = new SearchBox(search);
			await searchBox.init();
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_sync_uses_shared_connectivity_without_orphaned_global_state
	 * @pairs forms:builder-lifecycle offline:builder-lifecycle
	 */
	async sync({ hidden = document.hidden } = {}) {
		this.hidden = hidden;
		this.online = connectivity.online;
		this.offline(!this.online);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/builder/builder.mjs::FormBuilder.sync
	 * @reason builder connectivity controls are applied through the shared view lifecycle
	 */
	offline(offline) {
		const search = document.querySelector("[lp-search]");
		if (this.offlineIndicator)
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
		if (search) search.dataset.visible = offline ? "false" : "true";
		const saveButton = this.header.saveButton;
		if (saveButton) saveButton.dataset.visible = offline ? "false" : "true";
	}

	updateSchema(silent = false) {
		const schemas = Array.from(this.elements.values()).map(
			(element) => element.schema,
		);
		const schemaString = JSON.stringify(schemas);
		if (schemaString !== this.schemaElt.value) {
			this.schemaElt.value = schemaString;
			!silent && this.header.unsaved();
		}
	}

	get schema() {
		return JSON.parse(this.schemaElt.value);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
	 * @features forms
	 * @dimensions page-form task-form builder-defaults
	 */
	async createFormElements() {
		const recentSchema = this.schemaElt.value;
		const schemaJSON = recentSchema ? recentSchema : this.elt.dataset.schema;
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
	 * @pairs forms:builder-copy forms:schema forms:navigation
	 * @pairs entity-menu:builder-copy
	 */
	async copyForm(button) {
		if (!button?.dataset.route || button.disabled) return;

		button.disabled = true;
		const response = await request.post(button.dataset.route, {
			name: this.header.nameDisplay.textContent.trim(),
			schema: this.schema,
		});
		if (response?.ok && response.url) {
			window.location.assign(response.url);
			return;
		}

		button.disabled = false;
		this.header.message(response?.error || "Could not copy this form.");
	}

	async _showDeleteModal(button) {
		const modal = new DeleteModal(this, button);
		await modal.init();
	}

	async _showHelpModal(button) {
		const modal = new HelpModal(this, button);
		await modal.init();
	}

	selectElement(id) {
		this.selectedElement = this.elements.get(id);
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
	 * @features forms form-table
	 * @dimensions builder-defaults unsaved-preview empty-columns
	 */
	createElement(schema) {
		schema.id = schema.id ?? generateElementId(schema.type);
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

	async showCondition(name, index = -1) {
		if (this.conditions.loading) return;
		this.conditions.loading = true;
		const element = this.selectedElement;

		element.conditions ??= {};
		let condition = element.conditions[name] ?? null;
		if (!condition) {
			condition = await loadCondition(this, name);
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
		await condition.init();

		withTransition(async () => {
			await this.conditions.open(condition);
		});
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
	 * @features forms
	 * @dimensions builder-delete-components
	 */
	removeElement() {
		if (this.selectedElement.destroy) this.selectedElement.destroy();
		this.selectedElement.item.remove();
		this.elements.delete(this.selectedElement.schema.id);

		this.selectedElement = null;
		this.updateSchema();
	}

	destroy() {
		this.components.destroy();
		this.model.destroy();
		this.header.destroy();
		this.formSettings.destroy();
		this.EntityMenu.destroy();

		this.elements.forEach((element) => {
			if (element.destroy) element.destroy();
		});
		this.elements.clear();

		document.removeEventListener("click", this.click);
	}
}

export default FormBuilder;
