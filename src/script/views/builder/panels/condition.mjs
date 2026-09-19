import { withTransition } from "../../../shared/transitions.mjs";

/**
 * @testable infrastructure
 */
export class ConditionPanel {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("condition-panel");
		this.loading = false;
		this.condition = null;
		this._click = this._click.bind(this);
		this._draftInput = this._draftInput.bind(this);
		this.init();
	}

	init() {
		this.panel.addEventListener("click", this._click);
		for (const event of ["input", "change", "updated"])
			this.panel.addEventListener(event, this._draftInput);
	}

	_draftInput() {
		if (this.builder._restoringDraft || !this.condition?.key) return;
		// Dialog buffers are applied with Add/Update, but already count as newer
		// user work when deciding whether an asynchronous proposal can replace UI.
		this.builder.draft.revision += 1;
		this.builder.draft.group = null;
	}

	_click(e) {
		const button = e.target.closest("button");
		if (button?.dataset.role === "save") {
			const validated = this.condition.validate();
			if (!validated) return;

			const index = this.condition.index;
			const schema = this.condition.element.schema;
			const conditions = schema[this.condition.key] ?? [];

			if (index === -1) {
				conditions.push(this.condition.setting);
			} else {
				conditions[index] = this.condition.setting;
			}

			schema[this.condition.key] = conditions;
			this.condition.element.settings = this.builder.settings.create(schema);
			this.builder.updateSchema();

			withTransition(() => {
				this.condition.index = -1;
				this.condition.init();
				this.condition.showSuccess();
				this.condition.focus();
				this.builder.settings.updateItem();
				this.builder.model.updateItem();
			});
		} else if (button?.dataset.role === "close") {
			this.close();
		}
	}

	destroy() {
		this.panel?.removeEventListener("click", this._click);
		for (const event of ["input", "change", "updated"])
			this.panel?.removeEventListener(event, this._draftInput);
		this.loading = false;
		this.condition = null;
	}

	open(condition) {
		this.builder.model.sortable.option("disabled", true);
		this.builder.components.sortable.option("disabled", true);
		this.builder.model.focusItem();

		if (condition.expand) {
			this.builder.elt.dataset.expanded = "true";
		}

		this.panel.replaceChildren(condition.target);
		this.panel.dataset.visible = "true";
		this.condition = condition;
		this.loading = false;
	}

	hide() {
		this.builder.model.sortable.option("disabled", false);
		this.builder.components.sortable.option("disabled", false);
		this.builder.model.blurItem();
		this.panel.dataset.visible = "false";
		this.condition = null;
	}

	close() {
		withTransition(() => {
			this.hide();
			this.builder.elt.dataset.expanded = "false";
		});
	}
}
