import { getFormElement } from "../elements/loader";
import { captureError, generateElementId } from "../shared";

/**
 * @testable infrastructure
 */
export class Renderer {
	constructor(form) {
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
			.filter(Boolean);
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

	_packageSubmission() {
		const result = Object.fromEntries(
			Array.from(this.elements.values()).map((element) => [
				element.schema.id,
				element.value,
			]),
		);

		return result;
	}

	_onChange(event) {
		const trigger = event.target.closest(".form-element");
		if (!trigger) return;

		const element = this.elements.get(trigger.id);
		if (!element) return;

		if (this.statusTriggers.has(element)) {
			this.status.update();
		}
		if (this.visibilityTriggers.has(element)) {
			this._updateVisibility(element);
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @features tasks
	 * @dimensions history-fill latest-submission
	 */
	addHistoryFillButtons(submission, onFill = null) {
		if (!this.historyFillEnabled || !submission) return;

		for (const [fieldId, value] of Object.entries(submission)) {
			const element = this.elements.get(`${fieldId}-${this.id}`);
			element?.addHistoryFill?.(value, onFill);
		}
	}

	async _initStatusTriggers() {
		this.statusTriggers.clear();
		this.status = Array.from(this.elements.values()).find(
			(element) => element.schema.type === "status",
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

	/**
	 * @testable true
	 * @tests tests_js/test_019_form_sync_frontend.py::test_renderer_visibility_requires_canonical_condition_lists
	 * @features forms form-schema
	 * @dimensions visibility canonical-list legacy-object-rejected
	 */
	async _initVisibilityTriggers() {
		this.visibilityTriggers = new Map();
		this.visibilityConditions.clear();

		const targets = Array.from(this.elements.values()).filter(
			(element) => element.schema.visibility && element.elt,
		);

		for (const target of targets) {
			const conditions = target.schema.visibility.filter(
				(trigger) => trigger?.id,
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

	_updateVisibility(trigger) {
		const targets = this.visibilityTriggers.get(trigger);
		if (!targets) return;

		targets.forEach((target) => {
			this._updateVisibilityTarget(target);
		});
	}

	_updateVisibilityTarget(target) {
		const visible = this._visibilityConditionsMatch(target);
		target.elt.dataset.visible = visible ? "true" : "false";
	}

	_visibilityConditionsMatch(target) {
		const conditions = (this.visibilityConditions.get(target) || []).filter(
			(condition) => condition?.id,
		);
		if (conditions.length === 0) return true;

		const groups = new Map();

		for (const condition of conditions) {
			const group = groups.get(condition.id) || [];
			group.push(condition);
			groups.set(condition.id, group);
		}

		return Array.from(groups.entries()).every(([triggerId, group]) => {
			const element = this.elements.get(`${triggerId}-${this.id}`);
			if (!element) return false;
			return group.some((condition) => element.active(condition.value));
		});
	}

	async _createElements() {
		for (const eltSchema of this.form.schema) {
			const eltSubmission = this.form.submission?.[eltSchema.id];
			try {
				const element = await getFormElement(this, eltSchema, eltSubmission);
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
