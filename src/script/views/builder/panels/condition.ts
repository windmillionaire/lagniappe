import { withTransition } from "../../../shared/transitions.ts";
import type {
	FieldCondition,
	FieldOption,
	FormFieldSchema,
} from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import type { Condition } from "../conditions/base.ts";
import { builderControl } from "../controls.ts";

export class ConditionPanel {
	declare builder: FormBuilder;
	declare panel: HTMLElement;
	declare loading: boolean;
	declare condition: Condition | null;

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.panel = builderControl("condition-panel");
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
		const draft = this.builder.draft;
		if (!draft) return;
		draft.revision += 1;
		draft.group = null;
	}

	_click(e: MouseEvent) {
		const button = (e.target as Element | null)?.closest("button");
		if (button?.dataset.role === "save") {
			const condition = this.condition;
			if (!condition?.key || !condition.validate?.()) return;

			const schema = condition.element.schema;
			const index = condition.index;
			const update = <T>(items: T[], setting: T): T[] => {
				if (index === -1) items.push(setting);
				else items[index] = setting;
				return items;
			};
			// Each condition validates the fields its schema list requires.
			switch (condition.key) {
				case "columns":
					schema.columns = update(
						schema.columns ?? [],
						condition.setting as FormFieldSchema,
					);
					break;
				case "options":
					schema.options = update(
						schema.options ?? [],
						condition.setting as FieldOption,
					);
					break;
				case "visibility":
				case "status":
					schema[condition.key] = update(
						schema[condition.key] ?? [],
						condition.setting as FieldCondition,
					);
					break;
			}
			condition.element.settings = this.builder.settings.create(schema);
			this.builder.updateSchema();

			withTransition(() => {
				if (!this.condition) return;
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

	open(condition: Condition) {
		this.builder.model.sortable?.option("disabled", true);
		this.builder.components.sortable?.option("disabled", true);
		this.builder.model.focusItem();

		if (condition.expand) {
			this.builder.elt.dataset.expanded = "true";
		}

		this.panel.replaceChildren(condition.target);
		this.panel.dataset.visible = "true";
		this.condition = condition;
		this.loading = false;
		requestAnimationFrame(() => {
			if (
				this.condition !== condition ||
				this.panel.dataset.visible !== "true"
			) {
				return;
			}
			const focusableSelector =
				"input:not([type='hidden']):not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])";
			condition.focus();
			if (!this.panel.contains(document.activeElement)) {
				this.panel.querySelector<HTMLElement>(focusableSelector)?.focus();
			}
		});
	}

	hide() {
		this.builder.model.sortable?.option("disabled", false);
		this.builder.components.sortable?.option("disabled", false);
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
