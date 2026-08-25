/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bdc368f0';
import { f as areEqual } from './foundation.js?v=bdc368f0';
import './connectivity.js?v=bdc368f0';
import { p as primitives } from './primitives.js?v=bdc368f0';
import { F as FacetsBox } from './facets.js?v=bdc368f0';
import { f as formatting } from './formatting.js?v=bdc368f0';
import { B as BaseElement } from './baseElement.js?v=bdc368f0';
import './icons.js?v=bdc368f0';
import './remote.js?v=bdc368f0';
import './queryLifecycle.js?v=bdc368f0';
import './combobox.js?v=bdc368f0';
import './results.js?v=bdc368f0';
import './storage.js?v=bdc368f0';
import './submitter.js?v=bdc368f0';

/**
 * @testable infrastructure
 */
class LinkElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.combobox = null;
	}

	get value() {
		if (this.combobox) {
			const id =
				this.combobox?.values.size > 0
					? Array.from(this.combobox.values)[0]
					: null;
			if (this.submission?.id === id) return this.submission;
			const selected = this.combobox.selectedOptions;
			return selected.length > 0 ? selected[0] : null;
		} else {
			const inputs = this.elt?.querySelectorAll("input");
			if (!inputs?.length) {
				if (this.submission?.url) {
					return {
						url: this.submission.url,
						title: this.submission.title ?? "",
					};
				}
				return null;
			}
			const result = {};
			inputs.forEach((input) => {
				const key = input.name.slice(input.name.indexOf(":") + 1);
				result[key] = input.value;
			});
			return result.url ? result : null;
		}
	}

	changed(value) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_link_submission
	 * @features form-link
	 * @dimensions read-layout
	 */
	get read() {
		if (this._read) return this._read;
		if (!this.submission) return null;

		this._read = document.createElement("div");
		this._read.className = `${STYLES.form.submission.default} group-data-[mode=edit]/element:hidden`;

		if (this.submission?.id) {
			if (!this.submission.name) return null;
			const name = formatting.name({ ...this.submission, link: true });
			this._read.appendChild(
				formatting.iconLabel({
					icon: "in",
					kind: this.submission.kind,
					content: name,
					classes: STYLES.form.linkLabel,
					iconClasses: "text-kind-default",
				}),
			);
		} else if (this.submission?.url) {
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

		let edit;
		if (this.schema.location === "in") {
			edit = primitives.input({
				name: this.schema.id,
				label: this.label,
				kind: this.renderer.kind,
				data: {
					index: "internal",
					placeholder: "search...",
					preload: this.submission ? JSON.stringify(this.submission) : null,
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
					value: this.submission?.url,
				}),
				primitives.input({
					name: `${this.schema.id}:title`,
					type: "text",
					placeholder: "name (optional)",
					value: this.submission?.title,
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

export { LinkElement };
