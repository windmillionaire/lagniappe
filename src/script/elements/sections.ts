import { withTransition } from "../shared/transitions.ts";
import { type AutofillParent, AutofillUpload } from "./autofill.ts";
import { buttons } from "./buttons.ts";
import { primitives } from "./primitives.ts";

const autofill = (
	form: AutofillParent & { destroyables: { destroy?(): void }[] },
) => {
	const section = form.target.querySelector<HTMLElement>(
		'[data-role="autofill"]',
	);
	if (!section) return null;

	const autofill = new AutofillUpload({
		target: section,
		parent: form,
	});
	autofill.init();
	form.destroyables.push(autofill);
	return section;
};

const generateEntityForm = (form: { target: HTMLElement }) => {
	const section = form.target.querySelector<HTMLElement>(
		'div[data-role="generate"]',
	);
	if (!section) return null;

	const manualButton = section.querySelector<HTMLButtonElement>(
		'button[data-role="manual"]',
	);
	const aiButton = section.querySelector<HTMLButtonElement>(
		'button[data-role="ai"]',
	);
	const generate = section.querySelector<HTMLInputElement>('[name="generate"]');
	const description = section.querySelector<HTMLElement>(
		'[name="user_description"]',
	);
	const aiFields = section.querySelectorAll<HTMLElement>(
		'[data-role="ai"]:not(button)',
	);
	if (!manualButton || !aiButton || !generate || !description) return section;

	const setMode = (mode: string) => {
		form.target.dataset.mode = mode;
		aiFields.forEach((element) => {
			element.dataset.visible = mode === "ai" ? "true" : "false";
		});
		form.target
			.querySelectorAll<HTMLElement>('[data-role="manual"]')
			.forEach((element) => {
				if (!section.contains(element)) {
					element.dataset.visible = mode === "manual" ? "true" : "false";
				}
			});
	};

	setMode(form.target.dataset.mode || "manual");

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
		});
	});

	return section;
};

const generateImageForm = () => {
	const container = document.createElement("div");
	container.dataset.role = "generate-image";
	container.className = "flex flex-col gap-4";
	container.dataset.visible = "false";

	const usePageInfo: HTMLElement & { checked?: boolean } = primitives.checkbox({
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
