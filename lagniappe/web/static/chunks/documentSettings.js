/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd5baecd';
import { F as FormElement } from './form2.js?v=bd5baecd';
import { p as primitives } from './primitives.js?v=bd5baecd';
import './foundation.js?v=bd5baecd';
import './connectivity.js?v=bd5baecd';
import './baseForm.js?v=bd5baecd';
import './icons.js?v=bd5baecd';
import './loader.js?v=bd5baecd';

const VISIBILITY = {
	public: "This document is currently public. It can be viewed at this URL: ",
	private: "This document is currently private.",
};

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_document_visibility_can_toggle_public_private
 * @features pages
 * @dimensions document-visibility public private
 */
class DocumentSettings extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Document Settings",
			submitting: "Updating",
			submitted: "Updated",
		};
	}

	get url() {
		return this.target?.dataset.url || null;
	}

	set url(value) {
		if (!this.target) return;
		if (value) {
			this.target.dataset.url = value;
		} else {
			delete this.target.dataset.url;
		}
	}

	get statusElement() {
		const status = document.createElement("p");
		status.className = "font-base font-semibold text-base-dark";
		if (this.url) {
			const a = document.createElement("a");
			a.dataset.kind = this.kind;
			a.className = STYLES.link.default;
			a.href = this.url;
			a.textContent = this.url;
			status.append(`${VISIBILITY.public}`, a, ".");
		} else {
			status.textContent = VISIBILITY.private;
		}
		return status;
	}

	get visibilityGroupElement() {
		const visibilityGroup = document.createElement("fieldset");
		visibilityGroup.className = "flex flex-row gap-4";

		const options = [
			{ label: "Public", value: "public", checked: !!this.url },
			{ label: "Private", value: "private", checked: !this.url },
		];

		options.forEach((option) => {
			visibilityGroup.appendChild(
				primitives.radio({
					label: option.label,
					name: "visibility",
					value: option.value,
					checked: option.checked,
					required: true,
					kind: this.kind,
				}),
			);
		});
		return visibilityGroup;
	}

	get html() {
		return [this.statusElement, this.visibilityGroupElement];
	}

	updated(response) {
		super.updated(response);
		const updatedTarget = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		if (updatedTarget) {
			this.url = updatedTarget.dataset.url || null;
		}
	}
}

export { DocumentSettings };
