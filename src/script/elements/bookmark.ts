import { STYLES } from "../generated/styles.mjs";
import { areEqual } from "../shared/utilities.ts";
import { BaseElement } from "./base/baseElement.ts";
import { formatting } from "./formatting.ts";
import { primitives } from "./primitives.ts";

export class BookmarkElement extends BaseElement {
	get bookmark() {
		const value = this.submission;
		const url =
			value &&
			typeof value === "object" &&
			"url" in value &&
			typeof value.url === "string"
				? value.url
				: undefined;
		const title =
			value &&
			typeof value === "object" &&
			"title" in value &&
			typeof value.title === "string"
				? value.title
				: undefined;
		return { url, title };
	}

	get value() {
		const inputs = this.elt?.querySelectorAll("input");
		const result: Record<string, string | boolean> = {};
		inputs?.forEach((input) => {
			const key = input.name.slice(input.name.indexOf(":") + 1);
			result[key] = input.type === "checkbox" ? input.checked : input.value;
		});
		return result;
	}

	changed(value: unknown) {
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
		const { url, title } = this.bookmark;
		link.href = url ?? "";
		link.textContent = title || url || "";
		this._read.appendChild(
			formatting.iconLabel({
				icon: "out",
				kind: "page",
				content: link,
				classes: STYLES.form.linkLabel,
				iconClasses: "text-base-default",
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
		const { url, title } = this.bookmark;
		inputs.append(
			primitives.input({
				name: `${this.schema.id}:url`,
				type: "url",
				placeholder: "url",
				value: url,
			}),
			primitives.input({
				name: `${this.schema.id}:title`,
				type: "text",
				placeholder: "name (optional)",
				value: title,
			}),
		);

		const choices = inputs.appendChild(document.createElement("div"));
		choices.className = "flex flex-col gap-2 mt-2";
		choices.dataset.element = "choices";

		choices.appendChild(
			primitives.checkbox({
				label: "Replace page photo with link image",
				name: `${this.schema.id}:replace-image`,
				checked: Boolean(url),
			}),
		);
		choices.appendChild(
			primitives.checkbox({
				label: "Replace page description with link description",
				name: `${this.schema.id}:replace-description`,
				checked: Boolean(url),
			}),
		);
		choices.appendChild(
			primitives.checkbox({
				label: "Replace page name with link title",
				name: `${this.schema.id}:replace-name`,
				checked: Boolean(url),
			}),
		);

		inputs.classList.add("group-data-[mode=read]/element:hidden");
		edit.appendChild(choices);

		this._edit = edit;
		return this._edit;
	}
}
