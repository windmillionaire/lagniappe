/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b687b680';
import './foundation.js?v=b687b680';
import './connectivity.js?v=b687b680';
import './baseForm.js?v=b687b680';
import './icons.js?v=b687b680';
import './primitives.js?v=b687b680';
import './styles.js?v=b687b680';
import './loader.js?v=b687b680';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_create_note_composer_keeps_text_and_photo_from_home
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_create_note_body_and_photo_from_home
 * @tests tests_e2e/005_pages/test_005j_page_notes.py::test_page_note_text_photo_and_delete_modal
 * @matrix notes : body-create combined-input photo-picker preview remove
 * @pair notes:photo
 */
class CreateNote extends FormElement {
	constructor(attributes) {
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
		return this.target.querySelector("[name='note-file']");
	}

	get photoSelection() {
		return this.target.querySelector("[data-role='photo-selection']");
	}

	async init() {
		await super.init();
		this.target.addEventListener("click", this._click);
		this.target.addEventListener("reset", this._reset);
		this.photoInput?.addEventListener("change", this._photoChanged);
		this._showPhoto(this.photoInput?.files?.[0]);
	}

	_click(event) {
		if (event.target.closest("[data-action='add-photo']")) {
			this.photoInput?.click();
		} else if (event.target.closest("[data-action='remove-photo']")) {
			this._clearPhoto();
		}
	}

	_photoChanged() {
		this._showPhoto(this.photoInput?.files?.[0]);
	}

	_reset() {
		queueMicrotask(() => this._clearPhoto());
	}

	_showPhoto(file) {
		if (!file) {
			this._clearPhoto(false);
			return;
		}

		this._revokePhotoUrl();
		this.photoUrl = URL.createObjectURL(file);
		const preview = this.target.querySelector("[data-role='photo-preview']");
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

	created(response) {
		super.created(response);
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

export { CreateNote };
