import { STYLES } from "../generated/styles.mjs";
import { areEqual } from "../shared/utilities.ts";
import {
	BaseElement,
	type ElementRenderer,
	type ElementSchema,
} from "./base/baseElement.ts";
import { FacetsBox } from "./combobox/index.ts";
import { type EntityLabel, formatting } from "./formatting.ts";
import { primitives } from "./primitives.ts";

interface LinkSubmission extends Omit<EntityLabel, "link"> {
	url?: string | null;
	title?: string | null;
}

function isLinkSubmission(value: unknown): value is LinkSubmission {
	if (!value || typeof value !== "object" || Array.isArray(value)) return false;
	const data: Record<string, unknown> = { ...value };
	return (
		["id", "name", "kind", "index", "type"].every(
			(key) => data[key] === undefined || typeof data[key] === "string",
		) &&
		["url", "title"].every(
			(key) => data[key] == null || typeof data[key] === "string",
		)
	);
}

export class LinkElement extends BaseElement {
	declare combobox: FacetsBox | null;
	declare _cell?: HTMLDivElement;

	constructor(
		renderer: ElementRenderer,
		schema: ElementSchema,
		submission?: unknown,
	) {
		super(renderer, schema, submission);
		this.combobox = null;
	}

	get value() {
		const submission = this.linkSubmission;
		if (this.combobox) {
			const id =
				this.combobox?.values.size > 0
					? Array.from(this.combobox.values)[0]
					: null;
			if (submission?.id === id) return submission;
			const selected = this.combobox.selectedOptions;
			return selected.length > 0 ? selected[0] : null;
		} else {
			const inputs = this.elt?.querySelectorAll("input");
			if (!inputs?.length) {
				if (submission?.url) {
					return {
						url: submission.url,
						title: submission.title ?? "",
					};
				}
				return null;
			}
			const result: Record<string, string> = {};
			inputs.forEach((input) => {
				const key = input.name.slice(input.name.indexOf(":") + 1);
				result[key] = input.value;
			});
			return result.url ? result : null;
		}
	}

	changed(value: unknown) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	get linkSubmission() {
		return isLinkSubmission(this.submission) ? this.submission : null;
	}

	get hasSubmission() {
		const submission = this.linkSubmission;
		if (!submission) return false;
		return Boolean(submission.id ? submission.name : submission.url);
	}

	get read() {
		if (this._read) return this._read;
		const submission = this.linkSubmission;
		if (!submission) return null;

		this._read = document.createElement("div");
		this._read.className = `${STYLES.form.submission.default} group-data-[mode=edit]/element:hidden`;

		if (submission.id) {
			if (!submission.name) return null;
			const name = formatting.name({ ...submission, link: true });
			this._read.appendChild(
				formatting.iconLabel({
					icon: "in",
					kind: submission.kind,
					content: name,
					classes: STYLES.form.linkLabel,
					iconClasses: "text-kind-default",
				}),
			);
		} else if (submission.url) {
			const link = document.createElement("a");
			link.dataset.kind = "page";
			link.className = STYLES.link.default;
			link.target = "_blank";
			link.href = submission.url;
			link.textContent = submission.title || submission.url;
			this._read.appendChild(
				formatting.iconLabel({
					icon: "out",
					kind: "page",
					content: link,
					classes: STYLES.form.linkLabel,
					iconClasses: "text-base-default",
				}),
			);
		}

		return this._read;
	}

	get cell() {
		if (this._cell) return this._cell;
		const read = this.read;
		if (!read) return "";
		this._cell = document.createElement("div");
		this._cell.classList.add("flex", "flex-row", "items-baseline");
		this._cell.innerHTML = read.innerHTML;
		return this._cell.outerHTML;
	}

	get edit() {
		if (this._edit) return this._edit;

		const submission = this.linkSubmission;
		let edit: HTMLElement;
		if (this.schema.location === "in") {
			edit = primitives.input({
				name: this.schema.id,
				label: this.label,
				kind: this.renderer.kind,
				data: {
					index: "internal",
					placeholder: "search...",
					preload: submission ? JSON.stringify(submission) : null,
				},
			});
			this.combobox = new FacetsBox(edit);
			this.combobox.init();
			this.destroyables.push(this.combobox);
			this.combobox.element.classList.add(
				"group-data-[mode=read]/element:hidden",
			);
		} else {
			edit = document.createElement("div");
			edit.classList.add("flex", "flex-col", "gap-1");
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
					value: submission?.url,
				}),
				primitives.input({
					name: `${this.schema.id}:title`,
					type: "text",
					placeholder: "name (optional)",
					value: submission?.title,
				}),
			);
			inputs.classList.add("group-data-[mode=read]/element:hidden");
		}

		this._edit = edit;

		return this._edit;
	}

	clear() {
		if (this.combobox) {
			this.combobox.clear();
		}
		this.submission = null;
		this.edit.querySelectorAll("input").forEach((input) => {
			input.value = "";
		});
	}
}
