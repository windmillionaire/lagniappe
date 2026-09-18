/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b9107833';
import { f as fieldKind, C as CONFIG } from './builder.js?v=b9107833';
import { w as withTransition } from './foundation.js?v=b9107833';
import './connectivity.js?v=b9107833';
import { p as primitives } from './primitives.js?v=b9107833';
import { S as SelectBox } from './select2.js?v=b9107833';
import { C as Condition } from './base2.js?v=b9107833';
import './search.js?v=b9107833';
import './remote.js?v=b9107833';
import './queryLifecycle.js?v=b9107833';
import './combobox.js?v=b9107833';
import './results.js?v=b9107833';
import './icons.js?v=b9107833';
import './storage.js?v=b9107833';
import './formatting.js?v=b9107833';
import './upstreamUnavailable.js?v=b9107833';
import './entityMenu.js?v=b9107833';
import './dropdown.js?v=b9107833';
import './upload.js?v=b9107833';
import './buttons.js?v=b9107833';
import './modal.js?v=b9107833';
import './polling.js?v=b9107833';
import './baseForm.js?v=b9107833';
import './loader.js?v=b9107833';
import './facets.js?v=b9107833';
import './submitter.js?v=b9107833';

const MESSAGES = {
	checkbox: {
		text: "Values will be converted to 'True' or 'False'.",
		radio:
			"Component will be converted to a Radio with 'True' and 'False' values.",
	},
	out: {
		text: "Values will be converted to a plain-text url",
		bookmark: "Values will not change",
	},
	location: { text: "Values will be converted to plain-text addresses" },
	textarea: { text: "Values will be converted to text; newlines will be lost" },
	radio: {
		text: "Values will be converted to the plain-text label of the option selected",
		select:
			"Component will be converted into a Select component with the same options",
	},
	select: {
		text: "Values will be converted to the plain-text label of the option selected",
		radio:
			"Component will be converted into a Radio component with the same options",
	},
	table: {
		textarea: "Values will be converted to a table with Markdown formatting",
	},
	todo: {
		textarea:
			"Values will be converted to a todo list with Markdown formatting",
	},
};

/**
 * @testable true
 * @tests tests_js/test_036c_form_migrations.py::test_delete_element_commits_panel_and_model_changes_in_one_transition
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_saved_conversion_runs_after_save_and_preserves_originals
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_checkbox_replacement_explains_and_preserves_boolean_choices
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_replacement_choices_and_explanations_match_component_types
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_saved_inputs_use_replacement_panel_after_first_save
 * @matrix form-migration : modify-panel no-submission-read draft-undo
 */
class Modify extends Condition {
	init() {
		this.destroy();
		this.setTitle("Replace or Delete");
		const help = this.header.querySelector("[data-role='help']");
		help.setAttribute("lp-control", "help");
		help.setAttribute("lp-help", "form_element_changes");
		help.setAttribute(
			"aria-label",
			"Help with converting or deleting form elements",
		);
		this.target.replaceChildren(this.header);
		const deletion = this.target.appendChild(document.createElement("p"));
		deletion.className = "text-sm text-base-medium";
		deletion.textContent =
			"If an element is deleted, any values entered using that element in current submissions will be cleared, with the exception of tasks that have already been completed. Already completed tasks will retain the form that accompanied their original submitted values.";
		const source =
			this.builder.savedField(this.element.schema.id) || this.element.schema;
		const sourceKind = fieldKind(source);
		const kind = fieldKind(this.element.schema);
		const choices = (this.builder.conversionCatalog?.types || []).filter(
			(item) => {
				const rule =
					this.builder.conversionCatalog.rules[sourceKind]?.[item.value];
				return (
					rule &&
					item.value !== (kind === "multiple" ? "select" : kind) &&
					item.value !== "multiple" &&
					!(
						this.builder.elt.dataset.formType === "page" &&
						item.value === "todo"
					)
				);
			},
		);
		const actions = document.createElement("div");
		actions.className = choices.length
			? "grid grid-cols-2 gap-3"
			: "grid grid-cols-1 gap-3";
		if (choices.length) {
			const explanation = this.target.appendChild(document.createElement("p"));
			explanation.className = "text-sm text-base-medium";
			explanation.textContent =
				"If you replace the element instead, those values will be converted in order to match the new component type. Values that cannot be converted will be cleared.";
			this.addReplacement(choices, source, actions);
		} else {
			const unavailable = this.target.appendChild(document.createElement("p"));
			unavailable.dataset.role = "conversion-unavailable";
			unavailable.dataset.kind = "error";
			unavailable.className = "text-sm text-kind-default";
			unavailable.textContent = "This component type cannot be converted";
		}
		this.target.append(actions);
		const remove = actions.appendChild(document.createElement("button"));
		remove.type = "button";
		remove.dataset.kind = "delete";
		remove.className = STYLES.button.submit;
		remove.textContent = "Delete";
		remove.addEventListener("click", () => {
			void withTransition(
				() => {
					if (
						this.builder._destroyed ||
						this.builder.selectedElement !== this.element
					)
						return;
					this.builder.conditions.close();
					this.builder.removeElement();
					this.builder.settings.deselectItem();
					this.builder.formSettings.visible = true;
				},
				{ label: "builder:delete-element" },
			);
		});
	}

	addReplacement(choices, source, actions) {
		const sourceKind = fieldKind(source);
		const selectElt = primitives.select({
			label: "Replace With",
			kind: "form",
			data: { kind: "form" },
			name: "conversion-type",
			placeholder: "Choose a new component...",
			selectIcon: "dropdown",
			options: [],
		});
		this.target.append(selectElt);
		const select = selectElt.querySelector("select");
		const catalog = this.builder.conversionCatalog;
		const canUseAI = this.builder.elt.dataset.aiConversion === "true";
		for (const [title, ai] of [
			["Deterministic conversions", false],
			["AI conversions", true],
		]) {
			const group = document.createElement("optgroup");
			group.label = title;
			for (const item of choices) {
				const rule = catalog.rules[sourceKind]?.[item.value];
				if ((rule === "ai") !== ai) continue;
				const label =
					CONFIG.TABLE_COLUMNS.find(({ type }) => type === item.value)?.name ||
					item.label;
				const name = ai
					? `${label} (requires AI${canUseAI ? "" : " access"})`
					: label;
				const option = new Option(name, item.value);
				option.dataset.details = JSON.stringify({
					kind: "form",
					icon: item.value === "todo" ? "checklist" : item.value,
					name,
				});
				option.disabled = ai && !canUseAI;
				group.append(option);
			}
			if (group.childElementCount) select.append(group);
		}
		const selectBox = new SelectBox(selectElt);
		selectBox.init();
		this.destroyables.push(selectBox);
		this.focusTarget = selectElt;
		const description = this.target.appendChild(document.createElement("p"));
		description.dataset.role = "conversion-description";
		description.dataset.kind = "success";
		description.className = "text-sm text-kind-default";
		description.setAttribute("aria-live", "polite");
		description.hidden = true;
		const instructionLabel = this.target.appendChild(
			document.createElement("label"),
		);
		instructionLabel.className = "flex flex-col gap-2 text-sm";
		instructionLabel.textContent = "Conversion instructions (optional)";
		const instructions = instructionLabel.appendChild(
			document.createElement("textarea"),
		);
		instructions.name = "conversion-instructions";
		instructions.className = STYLES.textarea;
		instructions.rows = 3;
		instructions.maxLength = 4000;
		instructions.placeholder =
			"For example: one row per item; preserve completed checkboxes.";
		instructions.value = this.builder.conversionInstructions?.[source.id] || "";
		const alreadyAI =
			catalog.rules[sourceKind]?.[fieldKind(this.element.schema)] === "ai";
		instructionLabel.hidden = !alreadyAI;
		instructions.addEventListener("input", () => {
			if (!alreadyAI) return;
			this.builder.conversionInstructions ??= {};
			this.builder.conversionInstructions[source.id] = instructions.value;
			this.builder.updateSchema(false, `conversion-instructions:${source.id}`);
		});
		const convert = actions.appendChild(document.createElement("button"));
		convert.type = "button";
		convert.dataset.kind = "form";
		convert.className = STYLES.button.submit;
		convert.textContent = "Convert";
		convert.disabled = true;
		selectElt.addEventListener("updated", () => {
			const ai = catalog.rules[sourceKind]?.[select.value] === "ai";
			instructionLabel.hidden = !ai && !alreadyAI;
			convert.disabled = !select.value;
			description.hidden = !select.value;
			description.textContent = ai
				? "AI will convert saved values after Save. Review the destination columns and any conversion instructions first. Unresolvable values will be cleared; originals remain available in View changes."
				: MESSAGES[sourceKind === "multiple" ? "select" : sourceKind]?.[
						select.value
					] ||
					"Values will be converted to match the new component type. Values that cannot be converted will be cleared.";
		});
		convert.addEventListener("click", () => {
			const type = catalog.types.find(({ value }) => value === select.value);
			if (!type) return;
			const previous = this.element.schema;
			const next = { id: previous.id, title: previous.title, ...type.schema };
			for (const key of ["required", "placeholder", "visibility"])
				if (previous[key] !== undefined) next[key] = previous[key];
			if (["radio", "select"].includes(next.type)) {
				const options = previous.options ?? source.options;
				next.options = options
					? structuredClone(options)
					: sourceKind === "checkbox"
						? [
								{ value: "true", label: "True" },
								{ value: "false", label: "False" },
							]
						: [];
			}
			if (next.type === "table") next.columns = previous.columns || [];
			this.element.schema = next;
			this.builder.conversionInstructions ??= {};
			if (catalog.rules[sourceKind]?.[select.value] === "ai")
				this.builder.conversionInstructions[source.id] = instructions.value;
			else delete this.builder.conversionInstructions[source.id];
			this.builder.updateSchema();
			this.builder.restoreDraft();
			this.builder.header.message(
				"Conversion staged. Save will update submissions; values that cannot be converted will be cleared.",
				{ persistent: true },
			);
		});
	}
}

export { Modify as default };
