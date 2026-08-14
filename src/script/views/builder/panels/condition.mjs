import { withTransition } from "../../../shared";

/**
 * @testable infrastructure
 */
export class ConditionPanel {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("condition-panel");
		this.loading = false;
		this.condition = null;
		this.init();
	}

	init() {
		this.panel.addEventListener("click", (e) => {
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
		});
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
