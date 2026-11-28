import type { FormController } from "../forms/controller.ts";
import { withTransition } from "../shared/transitions.ts";
import { BaseUpload } from "./base/baseUpload.ts";
import { UploadMenu, uploadElement } from "./upload.ts";

const AUTOFILL_DROPZONE_TEXT = "Click or drop to add a related image or PDF";

export interface AutofillParent {
	target: HTMLElement;
	form?: Pick<FormController, "toggleSubForm"> | null;
}

export class AutofillUpload extends BaseUpload {
	declare parent: AutofillParent;
	declare name: "autofill";
	declare icon: string;
	declare deferred: boolean;
	declare messages: Record<string, string>;
	declare context: ReturnType<typeof uploadElement.contextUpload>;
	declare menuOptions: string[];
	declare _initialized: boolean;

	constructor(attributes: { target: HTMLElement; parent: AutofillParent }) {
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
			descriptionPlaceholder: "Describe what to extract or fill in…",
		});
		this.inputName = "autofill-file";
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this._initialized = false;
		this._click = this._click.bind(this);
	}

	async init() {
		this.parent.target.addEventListener("click", this._click);
	}

	get submitGroup() {
		return this.target.querySelector<HTMLElement>(
			"[data-role='autofill-submit-group']",
		);
	}

	get submitButton() {
		return (
			this.submitGroup?.querySelector<HTMLButtonElement>(
				"button[type='submit']",
			) ?? null
		);
	}

	_canFallbackToMultipart() {
		return false;
	}

	async _click(e: MouseEvent) {
		const role =
			e.target instanceof Element
				? e.target.closest("button")?.dataset.role
				: undefined;
		if (role !== "cancel-autofill" && role !== "show-autofill") return;

		e.preventDefault();
		e.stopPropagation();

		if (!this._initialized) {
			await super.init();
			if (this.submitGroup) this.target.append(this.submitGroup);
			this._initialized = true;
		}

		await withTransition(
			() => {
				if (role === "show-autofill") {
					this.target.dataset.visible = "true";
					this.parent.form?.toggleSubForm(this);
					this.target.querySelector("textarea")?.focus();
				} else if (role === "cancel-autofill") {
					this.target.dataset.visible = "false";
					this.parent.form?.toggleSubForm();
					this.reset();
					const textarea = this.target.querySelector("textarea");
					if (textarea) textarea.value = "";
				}
			},
			{ label: `autofill:${role}` },
		);
	}

	get html() {
		return [this.context.element];
	}
}
