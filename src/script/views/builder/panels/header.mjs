import { Renderer } from "../../../elements/renderer";
import { request, withTransition } from "../../../shared";

/**
 * @testable infrastructure
 */
export class Header {
	constructor(builder) {
		this._destroyed = false;
		this._previewGeneration = 0;
		this._messageTimer = null;
		this.builder = builder;
		this.nameDisplay = document.getElementById("form-name-display");
		this.nameInput = document.getElementById("form-name-input");
		this.nameHidden = document.getElementById("form-name-hidden");
		this.saveButton = document.querySelector("[data-saved]");
		this.schemaForm = document.getElementById("schema-form");
		this.notification = document.getElementById("notification");
		this.previewToggle = document.getElementById("preview-toggle");
		this.previewPanel = document.getElementById("preview-panel");

		this.togglePreviewPanel = this.togglePreviewPanel.bind(this);
		this.saveForm = this.saveForm.bind(this);
		this.editFormName = this.editFormName.bind(this);
		this._nameBlur = this._nameBlur.bind(this);
		this._nameKeyDown = this._nameKeyDown.bind(this);

		this.renderer = null;

		this.init();
	}

	init() {
		this.nameInput.addEventListener("blur", this._nameBlur);
		this.nameInput.addEventListener("keydown", this._nameKeyDown);
	}

	saved() {
		if (!this.saveButton) return;
		this.saveButton.disabled = false;
		this.saveButton.classList.remove("opacity-50");
		this.saveButton.dataset.saved = "true";
		this.saveButton.dataset.kind = "saved";
	}

	unsaved() {
		if (!this.saveButton) return;
		this.saveButton.dataset.saved = "false";
		this.saveButton.dataset.kind = "unsaved";
	}

	message(text) {
		if (this._destroyed) return;
		clearTimeout(this._messageTimer);
		this.notification.textContent = text;
		this.notification.dataset.visible = "true";
		this._messageTimer = setTimeout(() => {
			if (this._destroyed) return;
			this.notification.dataset.visible = "false";
		}, 3000);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
	 * @features forms
	 * @dimensions builder-preview
	 */
	async togglePreviewPanel() {
		if (this._destroyed) return;
		const generation = ++this._previewGeneration;
		const active = this.previewToggle.dataset.active === "true";
		this.previewToggle.dataset.active = active ? "false" : "true";
		this.previewToggle.setAttribute("aria-checked", active ? "false" : "true");

		let renderer = null;
		if (!active) {
			renderer = new Renderer({
				target: this.previewPanel,
				schema: this.builder.schema,
				kind: "form",
				key: this.builder.key,
				submission: {},
			});
			await renderer.render();
			if (this._destroyed || generation !== this._previewGeneration) {
				renderer.destroy();
				return;
			}
		}

		await withTransition(
			() => {
				if (this._destroyed || generation !== this._previewGeneration) {
					renderer?.destroy();
					return;
				}
				if (!active) {
					this.renderer = renderer;
					this.builder.elt.dataset.expanded = "true";
					this.previewPanel.dataset.visible = "true";
					this.builder.conditions.hide();
					this.builder.model.hide();
				} else {
					this.renderer?.destroy();
					this.renderer = null;
					this.builder.elt.dataset.expanded = "false";
					this.previewPanel.dataset.visible = "false";
					this.builder.model.show();
				}
			},
			{ label: "builder:toggle-preview" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
	 * @features forms
	 * @dimensions builder-save builder-reload
	 */
	async saveForm() {
		if (this._destroyed || !this.saveButton || !this.schemaForm) return;
		this.saveButton.disabled = true;
		this.saveButton.classList.add("opacity-50");
		const response = await request.put(
			this.schemaForm.dataset.route,
			new FormData(this.schemaForm),
		);
		if (this._destroyed) return;
		response.ok ? this.saved() : this.message(response.error);
	}

	editFormName() {
		this.nameDisplay.dataset.visible = "false";
		this.nameInput.dataset.visible = "true";
		this.nameInput.focus();
		this.nameInput.select();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
	 * @pairs forms:builder-form-name entity-menu:title-menu
	 * @pairs frontend-icons:material-icon-preservation
	 */
	_nameBlur() {
		const newName = this.nameInput.value.trim();
		if (newName !== this.nameDisplay.textContent) {
			this.nameDisplay.textContent = newName;
			this.nameHidden.value = newName;
			this.unsaved();
		}
		this.nameInput.dataset.visible = "false";
		this.nameDisplay.dataset.visible = "true";
	}

	_nameKeyDown(e) {
		if (e.key === "Enter") {
			e.preventDefault();
			this.nameInput.blur();
		} else if (e.key === "Escape") {
			this.nameInput.value = this.nameDisplay.textContent;
			this.nameInput.blur();
		}
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this._previewGeneration += 1;
		clearTimeout(this._messageTimer);
		this._messageTimer = null;
		this.nameInput.removeEventListener("blur", this._nameBlur);
		this.nameInput.removeEventListener("keydown", this._nameKeyDown);
		this.renderer?.destroy();
		this.renderer = null;
	}
}
