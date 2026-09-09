import { withTransition } from "../shared";
import { AutofillUpload } from "./autofill";
import { buttons } from "./buttons";
import { primitives } from "./primitives";

/**
 * @testable infrastructure
 */
const autofill = (form) => {
	const section = form.target.querySelector('[data-role="autofill"]');
	if (!section) return null;

	const autofill = new AutofillUpload({
		target: section,
		parent: form,
	});
	autofill.init();
	form.destroyables.push(autofill);
	return section;
};

/**
 * @testable infrastructure
 */
const generateEntityForm = (form) => {
	const section = form.target.querySelector('div[data-role="generate"]');
	if (!section) return null;

	const manualButton = section.querySelector('button[data-role="manual"]');
	const aiButton = section.querySelector('button[data-role="ai"]');
	const generate = section.querySelector('[name="generate"]');
	const explain = form.target.querySelector('[data-role="explain"]');
	const description = section.querySelector('[name="user_description"]');
	const aiFields = section.querySelectorAll('[data-role="ai"]:not(button)');

	/**
	 * @testable false
	 * @covered-by src/script/elements/sections.mjs::generateEntityForm
	 * @reason mode toggling is private generate-form UI plumbing
	 */
	const setMode = (mode) => {
		form.target.dataset.mode = mode;
		aiFields.forEach((element) => {
			element.dataset.visible = mode === "ai" ? "true" : "false";
		});
		form.target.querySelectorAll('[data-role="manual"]').forEach((element) => {
			if (!section.contains(element)) {
				element.dataset.visible = mode === "manual" ? "true" : "false";
			}
		});
	};

	setMode(form.target.dataset.mode || "manual");

	if (explain && description) {
		description.addEventListener("input", () => {
			explain.dataset.visible = "true";
		});
	}

	aiButton.addEventListener("click", () => {
		withTransition(() => {
			const changed = !generate.checked;
			setMode("ai");
			manualButton.dataset.active = "false";
			aiButton.dataset.active = "true";
			generate.checked = true;
			if (changed)
				generate.dispatchEvent(new Event("change", { bubbles: true }));
			description.focus();
			if (explain && description?.value) {
				explain.dataset.visible = "true";
			}
		});
	});

	manualButton.addEventListener("click", () => {
		withTransition(() => {
			const changed = generate.checked;
			setMode("manual");
			manualButton.dataset.active = "true";
			aiButton.dataset.active = "false";
			generate.checked = false;
			if (changed)
				generate.dispatchEvent(new Event("change", { bubbles: true }));
			if (explain) {
				explain.dataset.visible = "false";
			}
		});
	});

	return section;
};

/**
 * @testable infrastructure
 */
const generateImageForm = () => {
	const container = document.createElement("div");
	container.dataset.role = "generate-image";
	container.className = "flex flex-col gap-4";
	container.dataset.visible = "false";

	const usePageInfo = primitives.checkbox({
		label: "Use page info",
		name: "info",
		checked: true,
		kind: "page",
	});

	const prompt = primitives.textarea({
		name: "prompt",
		placeholder: "or describe the image you wish to create",
		rows: 3,
		kind: "page",
	});

	const submitGroup = document.createElement("div");
	submitGroup.dataset.role = "submit-group";
	submitGroup.className = "flex flex-wrap gap-2 w-full";

	submitGroup.appendChild(
		buttons.default({
			role: "cancel",
			text: "Cancel",
			kind: "default",
			type: "button",
		}),
	);

	submitGroup.appendChild(
		buttons.default({
			role: "generate",
			text: "Generate",
			kind: "page",
			type: "submit",
			icon: "generate",
		}),
	);

	container.append(usePageInfo, prompt, submitGroup);

	return {
		element: container,
		submitGroup: submitGroup,
		reset: () => {
			usePageInfo.checked = false;
			prompt.value = "";
		},
		visible: () => {
			return container.dataset.visible === "true";
		},
		hide: () => {
			container.dataset.visible = "false";
		},
		show: () => {
			container.dataset.visible = "true";
			prompt.focus();
		},
	};
};

export const sections = {
	generateEntityForm,
	generateImageForm,
	autofill,
};
