import type { ElementSchema } from "../elements/base/baseElement.ts";
import { getFormElement } from "../elements/loader.ts";
import { captureError } from "../shared/errors.ts";
import { withTransition } from "../shared/transitions.ts";
import { generateElementId } from "../shared/utilities.ts";
import type {
	FieldCondition,
	FormSchema,
	FormSubmission,
} from "../types/forms.d.ts";

export interface FormRendererHost {
	target: HTMLElement;
	schema: FormSchema;
	submission?: FormSubmission | null;
	key?: string | null;
	kind?: string | null;
	readonly?: boolean;
	showEmptyFields?: boolean;
	historyFillEnabled?: boolean;
	htmlFields?: Record<string, string> | null;
}

export interface RenderedFormElement {
	id: string;
	schema: ElementSchema;
	elt: HTMLElement | null;
	value?: unknown;
	active?(value: unknown): boolean;
	addHistoryFill?(value: unknown): boolean;
	clear?(): void;
	destroy?(): void;
}

interface RenderedStatusElement extends RenderedFormElement {
	update(): void;
}

interface TriggerCondition extends FieldCondition {
	id: string;
}

export class FormRenderer {
	declare id: string;
	declare form: FormRendererHost;
	declare kind: string;
	declare elements: Map<string, RenderedFormElement>;
	declare visibilityTriggers: Map<
		RenderedFormElement,
		Set<RenderedFormElement>
	>;
	declare visibilityConditions: Map<RenderedFormElement, TriggerCondition[]>;
	declare statusTriggers: Set<RenderedFormElement>;
	declare status: RenderedStatusElement | null | undefined;

	constructor(form: FormRendererHost) {
		this.id = generateElementId("renderer");
		this.form = form;
		this.kind = form.kind || form.target.dataset.kind || "form";
		this.elements = new Map();
		this.visibilityTriggers = new Map();
		this.visibilityConditions = new Map();
		this.statusTriggers = new Set();
		this.status = null;

		this._onChange = this._onChange.bind(this);
	}

	get target() {
		return this.form.target;
	}

	get readonly() {
		return this.form.readonly;
	}

	get showEmptyFields() {
		return this.form.showEmptyFields;
	}

	get historyFillEnabled() {
		return this.form.historyFillEnabled;
	}

	async render() {
		await this._createElements();

		const html = Array.from(this.elements.values())
			.map((element) => element.elt)
			.filter((element): element is HTMLElement => Boolean(element));
		this.form.target.replaceChildren(...html);

		this._initStatusTriggers();

		this._initVisibilityTriggers();
		if (!this.readonly) {
			this.target.addEventListener("change", this._onChange);
		}

		this._updateDerivedState();
		this.target.setAttribute("rendered", "");
	}

	destroy() {
		this.elements.forEach((element) => {
			if (element.destroy) element.destroy();
		});
		this.target.removeAttribute("rendered");
		this.target.removeEventListener("change", this._onChange);
		this.visibilityTriggers.clear();
		this.visibilityConditions.clear();
		this.statusTriggers.clear();
	}

	_packageSubmission(): FormSubmission {
		const result = Object.fromEntries(
			Array.from(this.elements.values()).map((element) => [
				element.schema.id,
				element.value,
			]),
		);

		return result;
	}

	_onChange(event: Event) {
		const target = event.target;
		if (
			!target ||
			!("closest" in target) ||
			typeof target.closest !== "function"
		)
			return;
		const trigger: Element | null = target.closest(".form-element");
		if (!trigger) return;

		const element = this.elements.get(trigger.id);
		if (!element) return;

		if (this.statusTriggers.has(element)) {
			this.status?.update();
		}
		if (this.visibilityTriggers.has(element)) {
			this._updateVisibility(element);
		}
	}

	addHistoryFillButtons(submission: FormSubmission | null | undefined) {
		if (!this.historyFillEnabled || !submission) return;

		for (const [fieldId, value] of Object.entries(submission)) {
			const element = this.elements.get(`${fieldId}-${this.id}`);
			element?.addHistoryFill?.(value);
		}
	}

	async _initStatusTriggers() {
		this.statusTriggers.clear();
		this.status = Array.from(this.elements.values()).find(
			(element): element is RenderedStatusElement =>
				element.schema.type === "status",
		);
		if (!this.status) return;

		const messages = Array.isArray(this.status.schema.status)
			? this.status.schema.status
			: [];
		for (const message of messages) {
			if (!message?.id) continue;

			const trigger = this.elements.get(`${message.id}-${this.id}`);
			if (!trigger) continue;

			this.statusTriggers.add(trigger);
		}
	}

	async _initVisibilityTriggers() {
		this.visibilityTriggers = new Map();
		this.visibilityConditions.clear();

		for (const target of this.elements.values()) {
			if (!target.schema.visibility || !target.elt) continue;
			const conditions = target.schema.visibility.filter(
				(trigger): trigger is TriggerCondition => Boolean(trigger?.id),
			);
			if (conditions.length === 0) continue;
			this.visibilityConditions.set(target, conditions);

			for (const trigger of conditions) {
				const element = this.elements.get(`${trigger.id}-${this.id}`);
				if (!element?.elt) continue;

				const values = this.visibilityTriggers.get(element) || new Set();
				values.add(target);
				this.visibilityTriggers.set(element, values);
			}
		}
	}

	_updateDerivedState() {
		this.status?.update();
		this.visibilityConditions.forEach((_conditions, target) => {
			this._updateVisibilityTarget(target);
		});
	}

	_updateVisibility(trigger: RenderedFormElement) {
		const targets = this.visibilityTriggers.get(trigger);
		if (!targets) return;

		const changes = Array.from(targets, (target) => ({
			target,
			visible: this._visibilityConditionsMatch(target),
		})).filter(
			({ target, visible }) =>
				target.elt?.dataset.visible !== (visible ? "true" : "false"),
		);
		if (!changes.length) return;

		void withTransition(
			() => {
				changes.forEach(({ target, visible }) => {
					const { elt } = target;
					if (elt) elt.dataset.visible = visible ? "true" : "false";
				});
			},
			{ label: "form:conditional-visibility" },
		);
	}

	_updateVisibilityTarget(target: RenderedFormElement) {
		const visible = this._visibilityConditionsMatch(target);
		const { elt } = target;
		if (elt) elt.dataset.visible = visible ? "true" : "false";
	}

	_visibilityConditionsMatch(target: RenderedFormElement) {
		const conditions = (this.visibilityConditions.get(target) || []).filter(
			(condition) => condition?.id,
		);
		if (conditions.length === 0) return true;

		const groups = new Map<string, TriggerCondition[]>();

		for (const condition of conditions) {
			const group = groups.get(condition.id) || [];
			group.push(condition);
			groups.set(condition.id, group);
		}

		return Array.from(groups.entries()).every(([triggerId, group]) => {
			const element = this.elements.get(`${triggerId}-${this.id}`);
			if (!element) return false;
			// Canonical conditions only reference checkbox, radio, or select fields.
			const { active } = element;
			if (!active)
				throw new TypeError(
					`Condition trigger ${triggerId} cannot match a value`,
				);
			return group.some((condition) => active.call(element, condition.value));
		});
	}

	async _createElements() {
		for (const eltSchema of this.form.schema) {
			const eltSubmission = this.form.submission?.[eltSchema.id];
			try {
				const element: RenderedFormElement = await getFormElement(
					this,
					eltSchema,
					eltSubmission,
				);
				this.elements.set(element.id, element);
			} catch (error) {
				captureError(error, this.target, {
					schema: eltSchema,
					submission: eltSubmission,
				});
			}
		}
	}
}
