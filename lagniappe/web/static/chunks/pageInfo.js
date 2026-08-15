/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b5d60d88';
import { InputElement } from './input.js?v=b5d60d88';
import { RadioElement } from './radio.js?v=b5d60d88';
import { s as sections } from './sections.js?v=b5d60d88';
import { S as SectionToggle } from './sectionToggle.js?v=b5d60d88';
import { TextareaElement } from './textarea.js?v=b5d60d88';
import { r as request, c as captureError, w as withTransition } from './foundation.js?v=b5d60d88';
import './connectivity.js?v=b5d60d88';
import { PagePermissions } from './pagePermissions.js?v=b5d60d88';
import './baseForm.js?v=b5d60d88';
import './icons.js?v=b5d60d88';
import './primitives.js?v=b5d60d88';
import './styles.js?v=b5d60d88';
import './loader.js?v=b5d60d88';
import './baseElement.js?v=b5d60d88';
import './formatting.js?v=b5d60d88';
import './baseUpload.js?v=b5d60d88';
import './buttons.js?v=b5d60d88';
import './dropdown.js?v=b5d60d88';
import './combobox.js?v=b5d60d88';
import './facets.js?v=b5d60d88';
import './results.js?v=b5d60d88';
import './submitter.js?v=b5d60d88';

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

	get attributesElement() {
		return sections.attributes(this);
	}

	get photoPromptElement() {
		return sections.photoPrompt(this);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_category_to_page
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_remove_category_from_page
	 * @features pages
	 * @dimensions category-add category-remove
	 */
	get categoriesElement() {
		return this._facetElement('[data-role="categories"]');
	}

	get autofillElement() {
		return sections.autofill(this);
	}

	get prepend() {
		return [this.photoPromptElement, this.nameElement, this.descriptionElement];
	}

	get append() {
		return [
			this.formSelectElement,
			this.attributesElement,
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
 * @pairs pages:readonly pages:permission-gates pages:lp-offline
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
	 * @features pages
	 * @dimensions form-switch form-clear info-form
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
 * @features pages
 * @dimensions create category-index related-forms mobile-tools tool-switch
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

	get html() {
		return [
			this.nameElement,
			this.descriptionElement,
			this.formSelectElement,
			this.relatedFormsElement,
			this.attributesElement,
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

/**
 * @testable infrastructure
 */
class UserSettings extends PagePermissions {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update User Settings",
			submitting: "Updating User Settings",
			submitted: "User Settings Updated",
		};
		this._groupSelect = null;
	}

	async reset() {
		this.destroy();
		await this.init();
	}

	updated(response) {
		const updatedTarget = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		if (updatedTarget) {
			this.initialTarget = updatedTarget;
			this._updated = true;
		}
	}

	async init() {
		await super.init();
		this._initGroups();
		this._initPageSelect();
		this._initRemovePage();
		this.commitRevisionBaseline();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
	 * @features user-settings
	 * @dimensions owner-other-page group-selector edit-groups
	 */
	_initGroups() {
		const groupInput = this.target.querySelector(
			"[data-role='user-groups'] [name='group']",
		);
		if (!groupInput || !this.canEditGroups) return;

		this._groupSelect = SectionToggle.facet(
			this,
			groupInput.closest("[lp-select]"),
		);
		this._groupSelect.init();
		this.destroyables.push(this._groupSelect);
	}

	_initPageSelect() {
		const pageInput = this.target.querySelector(
			"[data-role='page-select'] [name='reassign-page']",
		);
		if (!pageInput) return;

		this._pageSelect = SectionToggle.facet(
			this,
			pageInput.closest("[lp-select]"),
		);
		this._pageSelect.init();
		this.destroyables.push(this._pageSelect);
	}

	_initRemovePage() {
		const removePageInput = this.target.querySelector(
			"[data-role='remove-page'] input[name='remove-user']",
		);
		if (!removePageInput) return;
		removePageInput.addEventListener("change", (e) => {
			if (e.target.checked && this._pageSelect) {
				this._pageSelect.select.clear();
			}
		});
	}

	get canEditGroups() {
		return this.target.dataset.canEditGroups === "true";
	}

	get canEditAi() {
		return this.target.dataset.canEditAi === "true";
	}

	get canEditName() {
		return this.target.dataset.canEditName === "true";
	}

	get nameElement() {
		const name = this.target.dataset.name || "";
		const canEdit = !this.readonly && this.canEditName;
		const field = new InputElement(
			{ kind: "user", readonly: !canEdit, mode: canEdit ? "edit" : null },
			{
				input: "text",
				id: "name",
				title: "Name",
				placeholder: "name this user...",
			},
			name,
		).elt;
		if (!field) return null;
		const input = field.matches("input") ? field : field.querySelector("input");
		if (input) input.value = name;
		return field;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
	 * @features user-settings
	 * @dimensions personal-page owner-own-page owner-other-page readonly-email editable-email
	 */
	get userEmailElement() {
		return this.target.querySelector("[data-role='user-email']");
	}

	get userAiAccessElement() {
		if (!this.canEditAi) return null;
		return new RadioElement(
			this,
			{
				name: "ai_access",
				label: "AI Access",
				required: true,
				layout: "row",
				options: [
					{ label: "None", value: "NONE" },
					{ label: "Ask", value: "ASK" },
					{ label: "Create", value: "CREATE" },
				],
			},
			this.target.dataset.aiAccess || "NONE",
		).edit;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @features user-settings
	 * @dimensions personal-page owner-own-page sign-out
	 */
	get userActionsElement() {
		return this.target.querySelector("[data-role='user-actions']");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @features user-settings
	 * @dimensions personal-page owner-own-page group-selector-hidden
	 */
	get userGroupsElement() {
		return this.target.querySelector("[data-role='user-groups']");
	}

	get ownerInboundElement() {
		return this.target.querySelector("[data-role='owner-inbound']");
	}

	get userCardElement() {
		return this.target.querySelector("[data-role='user-card']");
	}

	get pageSelectElement() {
		return this.target.querySelector("[data-role='page-select']");
	}

	get removePageElement() {
		return this.target.querySelector("[data-role='remove-page']");
	}

	get html() {
		const card = this.userCardElement;
		const fields = card?.querySelector("[data-role='user-fields']");
		fields?.replaceChildren(
			...[
				this.nameElement,
				this.userEmailElement,
				this.userAiAccessElement,
				this.userGroupsElement,
				this.ownerInboundElement,
				this.removePageElement,
				this.pageSelectElement,
			].filter(Boolean),
		);

		return [this.visibleTo, this.restrictAccess, card].filter(Boolean);
	}

	get formData() {
		const data = new FormData();
		const card = this.userCardElement;
		const name = card?.querySelector("[name='name']");
		const email = card?.querySelector("[name='email']");

		if (name?.value || this.target.dataset.name) {
			data.set("name", name?.value || this.target.dataset.name);
		}
		if (email && !email.disabled) {
			data.set("email", email.value);
		}
		const aiAccess = card?.querySelector("[name='ai_access']:checked");
		if (this.canEditAi && aiAccess) {
			data.set("ai_access", aiAccess.value);
		}
		if (this._groupSelect) {
			Array.from(this._groupSelect.select.values).forEach((value) => {
				data.append("group", value);
			});
		}
		if (this._pageSelect) {
			Array.from(this._pageSelect.select.values).forEach((value) => {
				data.append("reassign-page", value);
			});
		}
		if (this.target.dataset.canEditOwnerInbound === "true") {
			for (const name of [
				"allow_messages_and_mentions",
				"allow_task_assignments",
			]) {
				const toggle = card?.querySelector(`[name='${name}']`);
				if (toggle) data.set(name, toggle.checked ? "true" : "false");
			}
		}
		card?.querySelector("[name='remove-user']")?.checked &&
			data.set("remove-user", "true");
		data.set("role", "user-settings");
		return data;
	}

	postreconcile() {
		const updated = this._updated;
		if (!updated) return;

		this._updated = false;
		this.commitReset();
		this.target.dataset.visible = "true";
		this.setEntityMetadata();
		if (this._success) {
			this.form?.success();
			this._success = false;
		}
	}
}

export { CreatePage, PageForm, PageInfo, UserSettings };
