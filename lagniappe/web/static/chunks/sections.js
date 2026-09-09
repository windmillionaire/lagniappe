/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from './foundation.js?v=b6795d9d';
import './connectivity.js?v=b6795d9d';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b6795d9d';
import { b as buttons } from './buttons.js?v=b6795d9d';
import { p as primitives } from './primitives.js?v=b6795d9d';

const AUTOFILL_DROPZONE_TEXT = "Click or drop to add a related image or a pdf";

/**
 * @testable infrastructure
 */
class AutofillUpload extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.parent = attributes.parent;
		this.target = attributes.target;
		this.name = "autofill";
		this.icon = "generate";
		this.uploadType = "file";
		this.deferred = true;

		this.messages = {
			submit: "Autofill Form",
			submitting: "Starting...",
			submitted: "Autofill queued",
		};

		this.context = uploadElement.contextUpload({
			text: AUTOFILL_DROPZONE_TEXT,
		});
		this.inputName = "autofill-file";
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this._initialized = false;
		this._click = this._click.bind(this);
	}

	init() {
		this.parent.target.addEventListener("click", this._click);
	}

	get submitGroup() {
		return this.target.querySelector("[data-role='autofill-submit-group']");
	}

	get submitButton() {
		return this.submitGroup?.querySelector("button[type='submit']") ?? null;
	}

	_canFallbackToMultipart() {
		return false;
	}

	async _click(e) {
		const role = e.target.closest("button")?.dataset?.role;
		if (!["cancel-autofill", "show-autofill"].includes(role)) return;

		e.preventDefault();
		e.stopPropagation();

		if (!this._initialized) {
			await super.init();
			this.target.append(this.submitGroup);
			this._initialized = true;
		}

		await withTransition(
			() => {
				if (role === "show-autofill") {
					this.target.dataset.visible = "true";
					this.parent.form.toggleSubForm(this);
					this.target.querySelector("textarea").focus();
				} else if (role === "cancel-autofill") {
					this.target.dataset.visible = "false";
					this.parent.form.toggleSubForm();
					this.reset();
					this.target.querySelector("textarea").value = "";
				}
			},
			{ label: `autofill:${role}` },
		);
	}

	get html() {
		return [this.context.element];
	}
}

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

const sections = {
	generateEntityForm,
	generateImageForm,
	autofill,
};

export { sections as s };
