import { FormWidget, type FormWidgetSettings } from "./base/formWidget.ts";

export class CreateNote extends FormWidget {
	declare target: HTMLFormElement;
	declare photoUrl: string | null;

	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Add Note",
			submitting: "Adding Note",
			submitted: "Note Added",
		};
		this.photoUrl = null;
		this._click = this._click.bind(this);
		this._photoChanged = this._photoChanged.bind(this);
		this._reset = this._reset.bind(this);
	}

	get photoInput() {
		return this.target.querySelector<HTMLInputElement>("[name='note-file']");
	}

	get photoSelection() {
		return this.target.querySelector<HTMLElement>(
			"[data-role='photo-selection']",
		);
	}

	async init() {
		await super.init();
		this.target.addEventListener("click", this._click);
		this.target.addEventListener("reset", this._reset);
		this.photoInput?.addEventListener("change", this._photoChanged);
		this._showPhoto(this.photoInput?.files?.[0]);
	}

	_click(event: MouseEvent) {
		const target = event.target;
		if (!(target instanceof Element)) return;
		if (target.closest("[data-action='add-photo']")) {
			this.photoInput?.click();
		} else if (target.closest("[data-action='remove-photo']")) {
			this._clearPhoto();
		}
	}

	_photoChanged() {
		this._showPhoto(this.photoInput?.files?.[0]);
	}

	_reset() {
		queueMicrotask(() => this._clearPhoto());
	}

	_showPhoto(file?: File) {
		if (!file) {
			this._clearPhoto(false);
			return;
		}

		this._revokePhotoUrl();
		this.photoUrl = URL.createObjectURL(file);
		const preview = this.target.querySelector<HTMLImageElement>(
			"[data-role='photo-preview']",
		);
		const name = this.target.querySelector("[data-role='photo-name']");
		if (preview) preview.src = this.photoUrl;
		if (name) name.textContent = file.name;
		if (this.photoSelection) this.photoSelection.dataset.visible = "true";
	}

	_clearPhoto(clearInput = true) {
		this._revokePhotoUrl();
		if (clearInput && this.photoInput) this.photoInput.value = "";
		const preview = this.target.querySelector("[data-role='photo-preview']");
		const name = this.target.querySelector("[data-role='photo-name']");
		if (preview) preview.removeAttribute("src");
		if (name) name.textContent = "";
		if (this.photoSelection) this.photoSelection.dataset.visible = "false";
	}

	_revokePhotoUrl() {
		if (this.photoUrl) URL.revokeObjectURL(this.photoUrl);
		this.photoUrl = null;
	}

	created() {
		super.created();
		this.target.reset();
	}

	offline() {
		return {
			action: "create",
			kind: "note",
		};
	}

	destroy() {
		this.target.removeEventListener("click", this._click);
		this.target.removeEventListener("reset", this._reset);
		this.photoInput?.removeEventListener("change", this._photoChanged);
		this._revokePhotoUrl();
		super.destroy();
	}
}
