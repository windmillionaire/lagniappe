/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b66dffd0';
import { j as areEqual } from './foundation.js?v=b66dffd0';
import { B as BaseElement } from './baseElement.js?v=b66dffd0';
import { f as formatting } from './formatting.js?v=b66dffd0';
import { p as primitives } from './primitives.js?v=b66dffd0';
import './connectivity.js?v=b66dffd0';
import './icons.js?v=b66dffd0';

/**
 * @testable infrastructure
 */
class BookmarkElement extends BaseElement {
	get value() {
		const inputs = this.elt.querySelectorAll("input");
		const result = {};
		inputs.forEach((input) => {
			const key = input.name.slice(input.name.indexOf(":") + 1);
			result[key] = input.type === "checkbox" ? input.checked : input.value;
		});
		return result;
	}

	changed(value) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		this._read.className = STYLES.form.submission.default;

		const link = document.createElement("a");
		link.dataset.kind = "page";
		link.className = STYLES.link.default;
		link.target = "_blank";
		link.href = this.submission.url;
		link.textContent = this.submission.title
			? this.submission.title
			: this.submission.url;
		this._read.appendChild(
			formatting.iconLabel({
				icon: "out",
				kind: "page",
				content: link,
				iconClasses: "text-default",
			}),
		);

		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		const edit = document.createElement("div");
		edit.classList.add("flex", "flex-col", "gap-2");
		if (this.label) {
			const label = primitives.label({
				label: this.label,
				tag: "h3",
			});
			edit.appendChild(label);
		}

		const inputs = edit.appendChild(document.createElement("div"));
		inputs.classList.add("flex", "flex-col", "gap-2");
		inputs.append(
			primitives.input({
				name: `${this.schema.id}:url`,
				type: "url",
				placeholder: "url",
				value: this.submission?.url,
			}),
			primitives.input({
				name: `${this.schema.id}:title`,
				type: "text",
				placeholder: "name (optional)",
				value: this.submission?.title,
			}),
		);

		const choices = inputs.appendChild(document.createElement("div"));
		choices.className = "flex flex-col gap-2 mt-2";
		choices.dataset.element = "choices";

		choices.appendChild(
			primitives.checkbox({
				label: "Replace page photo with link image",
				name: `${this.schema.id}:replace-image`,
				checked: !!this.submission?.url,
			}),
		);
		choices.appendChild(
			primitives.checkbox({
				label: "Replace page description with link description",
				name: `${this.schema.id}:replace-description`,
				checked: !!this.submission?.url,
			}),
		);
		choices.appendChild(
			primitives.checkbox({
				label: "Replace page name with link title",
				name: `${this.schema.id}:replace-name`,
				checked: !!this.submission?.url,
			}),
		);

		inputs.classList.add("group-data-[mode=read]/element:hidden");
		edit.appendChild(choices);

		this._edit = edit;
		return this._edit;
	}
}

export { BookmarkElement };
