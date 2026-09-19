/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=bdc1ce7d';
import { RadioElement } from './radio.js?v=bdc1ce7d';
import { S as SectionToggle } from './sectionToggle.js?v=bdc1ce7d';
import { r as request, c as captureError } from './foundation.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import { Modal } from './modal.js?v=bdc1ce7d';
import { F as FormWidget } from './formWidget.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './baseElement.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './formatting.js?v=bdc1ce7d';
import './facets.js?v=bdc1ce7d';
import './remote.js?v=bdc1ce7d';
import './queryLifecycle.js?v=bdc1ce7d';
import './combobox.js?v=bdc1ce7d';
import './results.js?v=bdc1ce7d';
import './storage.js?v=bdc1ce7d';
import './submitter.js?v=bdc1ce7d';
import './buttons.js?v=bdc1ce7d';
import './baseUpload.js?v=bdc1ce7d';
import './controller.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';
import './directUpload.js?v=bdc1ce7d';
import './dropdown.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './representation.js?v=bdc1ce7d';

/**
 * @testable infrastructure
 */
class UserSettings extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update User Settings",
			submitting: "Updating User Settings",
			submitted: "User Settings Updated",
		};
		this._groupSelect = null;
	}

	async _initForm(options) {
		await super._initForm(options);
		this._groupSelect = null;
		this._pageSelect = null;
		this._initGroups();
		this._initPageSelect();
		this._initRemovePage();
		this._initApiKey();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_044_agent_api_settings.py::test_agent_api_key_controls_keep_secret_ephemeral
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @matrix agent-api : copy-control expiry revoke rotate shown-once status
	 */
	_initApiKey() {
		if (this.revisionPreview) return;
		const section = this.target.querySelector("[data-role='api-key-settings']");
		const route = this.target.dataset.apiKeyRoute;
		if (!section || !route) return;

		const controller = new AbortController();
		const signal = controller.signal;
		section
			.querySelector("[data-action='issue-api-key']")
			?.addEventListener(
				"click",
				() => void this._issueApiKey(section, route),
				{ signal },
			);
		section
			.querySelector("[data-action='revoke-api-key']")
			?.addEventListener(
				"click",
				() => void this._revokeApiKey(section, route),
				{ signal },
			);
		this.destroyables.push({
			destroy: () => controller.abort(),
		});
		void request
			.get(route, null, { signal, replaceErrorPage: false })
			.then((response) => {
				if (signal.aborted) return;
				if (response.ok) this._renderApiKey(section, response.credential);
				else this._apiKeyError(section, response.error);
			});
	}

	_renderApiKey(section, credential = {}, token = null) {
		const active = credential?.active === true;
		const status = section.querySelector("[data-role='api-key-status']");
		const issue = section.querySelector("[data-action='issue-api-key']");
		const revoke = section.querySelector("[data-action='revoke-api-key']");
		const secret = section.querySelector("[data-role='api-key-secret']");
		const value = section.querySelector("[data-role='api-key-value']");
		if (status) {
			const expires = credential?.expires_at
				? new Date(credential.expires_at).toLocaleString()
				: null;
			status.textContent = active
				? `${credential.display_prefix || "API key"} — expires ${expires}`
				: "No active API key.";
		}
		if (issue)
			issue.textContent = active ? "Regenerate API key" : "Generate API key";
		if (revoke) revoke.dataset.visible = active.toString();
		if (secret) secret.dataset.visible = Boolean(token).toString();
		if (value) value.textContent = token || "";
		this._apiKeyError(section, null);
	}

	_apiKeyError(section, message) {
		const target = section.querySelector("[data-role='api-key-message']");
		if (!target) return;
		target.textContent = message || "";
		target.dataset.visible = Boolean(message).toString();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_without_provider_access_can_manage_external_agent_api_key
	 * @tests tests_js/test_044_agent_api_settings.py::test_agent_api_key_confirmation_uses_app_modal
	 * @matrix agent-api user-settings : confirmation-modal revoke rotate
	 */
	async _confirmApiKeyAction(section, trigger, options) {
		const template = section.querySelector(
			"template[data-role='api-key-confirmation-template']",
		);
		const modalElement = template?.content
			?.querySelector("#modal")
			?.cloneNode(true);
		if (!modalElement) {
			captureError(
				new Error("API key confirmation template is missing."),
				trigger,
				this.view?.dataset,
			);
			return false;
		}

		modalElement.querySelector("[data-role='confirmation-title']").textContent =
			options.title;
		modalElement.querySelector(
			"[data-role='confirmation-description']",
		).textContent = options.description;
		const confirm = modalElement.querySelector(
			"[data-role='confirmation-confirm']",
		);
		confirm.querySelector("[data-role='text']").textContent = options.label;

		const modal = new Modal(this.view, trigger);
		let settled = false;
		let settle;
		const confirmation = new Promise((resolve) => {
			settle = (value) => {
				if (settled) return;
				settled = true;
				resolve(value);
			};
		});
		const remove = modal.remove.bind(modal);
		modal.remove = async () => {
			const result = await remove();
			settle(false);
			return result;
		};
		confirm.addEventListener(
			"click",
			async () => {
				confirm.disabled = true;
				await remove();
				settle(true);
			},
			{ once: true },
		);

		const attached = await modal.attach(modalElement);
		if (!attached) settle(false);
		else confirm.focus();
		return confirmation;
	}

	async _issueApiKey(section, route) {
		const issue = section.querySelector("[data-action='issue-api-key']");
		const isRotation = issue?.textContent?.includes("Regenerate");
		if (
			isRotation &&
			!(await this._confirmApiKeyAction(section, issue, {
				title: "Regenerate API key",
				description:
					"The current key will stop working immediately. Any client using it must be updated with the new key.",
				label: "Regenerate API key",
			}))
		) {
			return;
		}
		if (issue) issue.disabled = true;
		const response = await request.post(route, {});
		if (issue) issue.disabled = false;
		if (!response.ok) return this._apiKeyError(section, response.error);
		this._renderApiKey(section, response.credential, response.token);
	}

	async _revokeApiKey(section, route) {
		const revoke = section.querySelector("[data-action='revoke-api-key']");
		if (
			!(await this._confirmApiKeyAction(section, revoke, {
				title: "Revoke API key",
				description:
					"This key will stop working immediately. Any client using it will lose access until a new key is generated.",
				label: "Revoke API key",
			}))
		) {
			return;
		}
		if (revoke) revoke.disabled = true;
		const response = await request.delete(route);
		if (revoke) revoke.disabled = false;
		if (!response.ok) return this._apiKeyError(section, response.error);
		this._renderApiKey(section, response.credential);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
	 * @matrix user-settings : edit-groups group-selector owner-other-page
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
	 * @matrix user-settings : editable-email owner-other-page owner-own-page personal-page readonly-email
	 */
	get userEmailElement() {
		return this.target.querySelector("[data-role='user-email']");
	}

	get userAiAccessElement() {
		if (!this.canEditAi) return null;
		const field = new RadioElement(
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
		field.dataset.role = "ai-access";
		return field;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
	 * @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_own_page_hides_photo_and_file_surfaces
	 * @matrix notification-email : default-daily public-user user-only user-setting
	 */
	get notificationEmailElement() {
		if (this.target.dataset.canEditNotificationEmail !== "true") return null;
		const field = new RadioElement(
			this,
			{
				name: "notification_email_mode",
				label: "Email Notifications",
				required: true,
				layout: "column",
				options: [
					{ label: "No email", value: "NONE" },
					{ label: "Email after five minutes", value: "IMMEDIATE" },
					{ label: "Daily digest at 8:00 AM local time", value: "DAILY" },
				],
			},
			this.target.dataset.notificationEmailMode || "DAILY",
		).edit;
		field.dataset.role = "notification-email";
		field.className = "space-y-0 rounded-md border border-user-default p-3";
		field.querySelector("legend")?.classList.add("px-1");
		return field;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @matrix user-settings : owner-own-page personal-page sign-out
	 */
	get userActionsElement() {
		return this.target.querySelector("[data-role='user-actions']");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @matrix user-settings : group-selector-hidden owner-own-page personal-page
	 */
	get userGroupsElement() {
		return this.target.querySelector("[data-role='user-groups']");
	}

	get apiKeyElement() {
		return this.target.querySelector("[data-role='api-key-settings']");
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

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_settings_hides_group_selector_on_own_page
	 * @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_own_page_hides_photo_and_file_surfaces
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
	 * @pair user-settings:field-order
	 */
	get html() {
		const card = this.userCardElement;
		const fields = card?.querySelector("[data-role='user-fields']");
		const publicEmailConsent = this.target.querySelector(
			"[data-role='public-email-consent']",
		);
		const userPage =
			this.removePageElement?.closest("[data-role='user-page']") ??
			this.pageSelectElement?.closest("[data-role='user-page']");
		fields?.replaceChildren(
			...[
				this.nameElement,
				this.userEmailElement,
				this.userGroupsElement,
				this.userAiAccessElement,
				this.notificationEmailElement,
				this.apiKeyElement,
				publicEmailConsent,
				this.ownerInboundElement,
				userPage,
			].filter(Boolean),
		);

		return [
			this.target.querySelector("[data-role='visible-to']"),
			this.target.querySelector("[data-role='restrict-access']"),
			card,
		].filter(Boolean);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_own_page_hides_photo_and_file_surfaces
	 * @pair public-users:email-consent
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_submit_preserves_attached_form_and_categories
	 * @pair user-settings:restrictions
	 */
	get formData() {
		const fields = super.formData;
		const data = new FormData();
		for (const key of ["restrictions", "admin", "group-key"]) {
			for (const value of fields.getAll(key)) data.append(key, value);
		}
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
		const notificationEmail = card?.querySelector(
			"[name='notification_email_mode']:checked",
		);
		if (
			this.target.dataset.canEditNotificationEmail === "true" &&
			notificationEmail
		) {
			data.set("notification_email_mode", notificationEmail.value);
		}
		if (this.target.dataset.canEditPublicEmail === "true") {
			const allowSiteEmail = card?.querySelector("[name='allow_site_email']");
			if (allowSiteEmail) {
				data.set("allow_site_email", allowSiteEmail.checked ? "true" : "false");
			}
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

	/**
	 * @testable true
	 * @tests tests_js/test_044_agent_api_settings.py::test_agent_api_key_controls_keep_secret_ephemeral
	 * @matrix agent-api user-settings : poll-reconcile status
	 */
	postreconcile() {
		const updated = this._updated;
		super.postreconcile();
		if (!updated || this._updated) return;
		this.setEntityMetadata();
	}
}

export { UserSettings };
