/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=bdc1ce7d';
import './controller.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './foundation.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';
import './modal.js?v=bdc1ce7d';
import './representation.js?v=bdc1ce7d';

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_public_permissions
 * @matrix permissions public-groups : active permission-update public
 */
class PublicPermissions extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Public Permissions",
			submitting: "Updating Public Permissions",
			submitted: "Public Permissions Updated",
		};
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_rename_group
 * @tests tests_js/test_044_user_widget_frontend.py::test_group_permissions_tracks_rename_draft_after_target_rebuild
 * @matrix user-groups : entity-permissions general-permissions permission-update rename reset-rebinding
 */
class GroupPermissions extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update User Group",
			submitting: "Updating User Group",
			submitted: "User Group Updated",
		};
		this._submittedName = null;
	}

	async prepareSubmit(options) {
		if (!(await super.prepareSubmit(options))) return false;
		this._submittedName = this.formData.get("name");
		return true;
	}

	async reset() {
		this._submittedName = null;
		await super.reset();
	}

	async prepareRevision(response) {
		this._submittedName = null;
		return super.prepareRevision(response);
	}

	postreconcile() {
		const updated = this._updated;
		const localName = this.target.querySelector("[name='name']")?.value;
		const newerDraft =
			updated &&
			this._submittedName !== null &&
			localName !== this._submittedName;
		super.postreconcile();
		if (!updated || this._updated) return;
		this._submittedName = null;
		if (!this.revisionPreview) {
			const selector = Array.from(
				this.component.elt.querySelectorAll(
					"[data-role='group-selectors'] button[data-key]",
				),
			).find((button) => button.dataset.key === this.key);
			const label = selector?.querySelector("[data-role='group-name']");
			if (label) label.textContent = this.target.dataset.name;
		}
		if (newerDraft) {
			this.target.querySelector("[name='name']").value = localName;
			this.markUnsavedState();
		}
	}
}

export { GroupPermissions, PublicPermissions };
