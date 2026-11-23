import { BaseList } from "../elements/base/baseList.mjs";
import { InputElement } from "../elements/input.mjs";
import { SectionToggle } from "../elements/sectionToggle.mjs";
import { request } from "../shared/index.mjs";
import { withTransition } from "../shared/transitions.mjs";
import { FormWidget } from "./base/formWidget.mjs";

class ModelTask extends FormWidget {
	get formSelectElement() {
		const target = this.target.querySelector('[data-action="select-form"]');
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}

	get html() {
		this.nameElement = new InputElement(
			{
				kind: "task",
				readonly: this.readonly,
			},
			{
				id: "name",
				name: "name",
				title: "Name",
				input: "text",
				required: true,
				label: "Name",
			},
			this.target.dataset.name || "",
		);
		return [this.nameElement.elt, this.formSelectElement];
	}
}

export class CreateModelTask extends ModelTask {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Model Task",
			submitting: "Creating Model Task",
			submitted: "Model Task Created",
		};
	}

	postreconcile() {
		const created = this._created;
		super.postreconcile();

		if (created) {
			this.nameElement.clear();
			if (this.visible) this.form?.success();
			this.form?.resetSubmitButton();
		}
		if (this.visible) this.nameElement.focus();
	}
}

export class ModelTaskInfo extends ModelTask {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Model Task",
			submitting: "Updating Model Task",
			submitted: "Model Task Updated",
		};
	}

	postreconcile() {
		super.postreconcile();
		const name =
			this.nameElement?.value ||
			this.target.dataset.name ||
			this.component.elt.dataset.title ||
			"";
		if (!name) return;

		this.component.elt.dataset.title = name;
		const title = this.component.elt.querySelector("span[data-role='title']");
		if (title && name !== title.textContent) {
			title.textContent = name;
		}
	}
}

export class ModelTaskList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._click = this._click.bind(this);
		this._moving = false;
	}

	init() {
		this.component.elt.addEventListener("click", this._click);
		this._observer = new MutationObserver(() => this._updateMoveButtons());
		this._observeRows();
	}

	get rows() {
		return Array.from(this.target.querySelectorAll(":scope > li[lp-entity]"));
	}

	_observeRows() {
		this._observer?.disconnect();
		this._observer?.observe(this.target, { childList: true });
		this._updateMoveButtons();
	}

	_updateMoveButtons() {
		const rows = this.rows;
		rows.forEach((row, index) => {
			for (const button of row.querySelectorAll("[data-role='move-model']")) {
				const atEnd =
					button.dataset.direction === "up"
						? index === 0
						: index === rows.length - 1;
				button.disabled =
					this._moving || this.readonly || this.view.online === false || atEnd;
			}
		});
	}

	sync() {
		this._updateMoveButtons();
	}

	async _click(event) {
		const button = event.target.closest("[data-role='move-model']");
		if (!button || !this.target.contains(button)) return;
		event.preventDefault();
		event.stopPropagation();
		if (
			button.disabled ||
			this._moving ||
			this.readonly ||
			this.view.online === false
		)
			return;
		const rows = this.rows;
		const index = rows.indexOf(button.closest("li[lp-entity]"));
		const next = index + (button.dataset.direction === "up" ? -1 : 1);
		if (index < 0 || next < 0 || next >= rows.length) return;
		[rows[index], rows[next]] = [rows[next], rows[index]];
		const error = this.component.elt.querySelector(
			"[data-role='model-order-error']",
		);
		if (error) error.dataset.visible = "false";
		this._moving = true;
		this.target.setAttribute("aria-busy", "true");
		this._updateMoveButtons();
		try {
			const response = await request.put(
				this.target.dataset.reorderRoute,
				{
					model_tasks: rows.map((row) => row.dataset.key),
				},
				{ replaceErrorPage: false },
			);
			if (!response.ok) {
				if (error) {
					error.textContent =
						response.error || "Could not save the model task order. Try again.";
					error.dataset.visible = "true";
				}
				return;
			}
			const current = new Map(this.rows.map((row) => [row.dataset.key, row]));
			await withTransition(
				() => {
					response.model_tasks.forEach((key, order) => {
						const row = current.get(key);
						if (!row) return;
						row.dataset.order = order + 1;
						this.target.append(row);
					});
				},
				{ label: "model-tasks:reorder" },
			);
		} finally {
			this._moving = false;
			this.target.setAttribute("aria-busy", "false");
			this._updateMoveButtons();
			if (button.isConnected && !button.disabled)
				button.focus({ preventScroll: true });
		}
	}

	postreconcile() {
		super.postreconcile();
		const rows = this.rows;
		const ordered = [...rows].sort(
			(a, b) => Number(a.dataset.order) - Number(b.dataset.order),
		);
		if (ordered.some((row, index) => row !== rows[index]))
			this.target.append(...ordered);
		this._observeRows();
		this.target.setAttribute("loaded", "");
	}

	destroy() {
		this.component.elt.removeEventListener("click", this._click);
		this._observer?.disconnect();
	}
}
