import type { FormSubmitOptions } from "../forms/controller.ts";
import type { FormRevisionResponse } from "../types/forms";
import { FormWidget, type FormWidgetSettings } from "./base/formWidget.ts";

export class PublicPermissions extends FormWidget {
	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Update Public Permissions",
			submitting: "Updating Public Permissions",
			submitted: "Public Permissions Updated",
		};
	}
}

export class GroupPermissions extends FormWidget {
	declare _submittedName: FormDataEntryValue | null;

	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Update User Group",
			submitting: "Updating User Group",
			submitted: "User Group Updated",
		};
		this._submittedName = null;
	}

	async prepareSubmit(options?: FormSubmitOptions) {
		if (!(await super.prepareSubmit(options))) return false;
		this._submittedName = this.formData.get("name");
		return true;
	}

	async reset() {
		this._submittedName = null;
		await super.reset();
	}

	async prepareRevision(response: FormRevisionResponse) {
		this._submittedName = null;
		return super.prepareRevision(response);
	}

	postreconcile() {
		const updated = this._updated;
		const localName =
			this.target.querySelector<HTMLInputElement>("[name='name']")?.value;
		const newerDraft =
			updated &&
			this._submittedName !== null &&
			localName !== this._submittedName;
		super.postreconcile();
		if (!updated || this._updated) return;
		this._submittedName = null;
		if (!this.revisionPreview) {
			const selector = Array.from(
				this.component?.elt?.querySelectorAll<HTMLButtonElement>(
					"[data-role='group-selectors'] button[data-key]",
				) ?? [],
			).find((button) => button.dataset.key === this.key);
			const label = selector?.querySelector("[data-role='group-name']");
			if (label) label.textContent = this.target.dataset.name ?? "";
		}
		if (newerDraft && localName !== undefined) {
			const input =
				this.target.querySelector<HTMLInputElement>("[name='name']");
			if (input) input.value = localName;
			this.markUnsavedState();
		}
	}
}
