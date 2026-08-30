/*! Third-party licenses: /third-party-licenses.txt */
import { C as COLOR_MENU } from './toolbar.js?v=bb782d98';
import './combobox.js?v=bb782d98';
import './styles.js?v=bb782d98';
import './foundation.js?v=bb782d98';
import './connectivity.js?v=bb782d98';
import './primitives.js?v=bb782d98';
import './icons.js?v=bb782d98';
import './queryLifecycle.js?v=bb782d98';
import './dropdown.js?v=bb782d98';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_color_picker
 * @matrix editor : color reload
 */
class ColorPicker {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.name = "setColor";
		this.usedWithEditor = true;
		this.active = false;
		this.toggles = new Map();
	}

	_colorSwatch(color, title) {
		const colorButton = document.createElement("button");
		colorButton.className = `size-6 rounded transition-transform hover:scale-110 hover:outline-2 hover:outline-offset-2 data-[active=true]:outline-2 data-[active=true]:outline-offset-2`;
		colorButton.style.backgroundColor = color;
		colorButton.style.outlineColor = color;
		colorButton.title = title;
		colorButton.dataset.active = "false";
		colorButton.dataset.color = color;
		return colorButton;
	}

	setActiveColor(activeColor) {
		this.toggles.forEach((toggle, color) => {
			const isActive = color === activeColor;
			if (isActive !== toggle.active) {
				toggle.button.dataset.active = isActive ? "true" : "false";
				toggle.active = isActive;
			}
		});
	}

	init() {
		const colorOptions = this.toolbar.element.appendChild(
			document.createElement("div"),
		);
		colorOptions.dataset.option = this.name;
		colorOptions.className = `mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form="setColor"]/toolbar:flex group`;

		COLOR_MENU.forEach(({ color, title }) => {
			const colorButton = this._colorSwatch(color, title);
			this.toggles.set(color, { active: false, button: colorButton });
		});

		colorOptions.append(
			...Array.from(this.toggles.values()).map((toggle) => toggle.button),
		);
		this.active = true;

		colorOptions.addEventListener("click", (e) => {
			const colorButton = e.target.closest("button");
			if (!colorButton) return;

			const toggle = this.toggles.get(colorButton.dataset.color);

			const currentActive = Array.from(this.toggles.values()).find(
				(t) => t.active && t !== toggle,
			);
			if (currentActive) {
				currentActive.active = false;
				currentActive.button.dataset.active = "false";
			}

			toggle.active = !toggle.active;
			colorButton.dataset.active = toggle.active ? "true" : "false";

			if (toggle.active) {
				this.toolbar.editor
					.chain()
					.focus()
					.setColor(colorButton.dataset.color)
					.run();
			} else {
				this.toolbar.editor.chain().focus().unsetColor().run();
			}
		});
	}
}

export { ColorPicker as setColor };
