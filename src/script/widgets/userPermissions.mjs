import { FormWidget } from "./base/formWidget.mjs";

export class PublicPermissions extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Public Permissions",
			submitting: "Updating Public Permissions",
			submitted: "Public Permissions Updated",
		};
	}
}

export class GroupPermissions extends FormWidget {
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
