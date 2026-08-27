/*! Third-party licenses: /third-party-licenses.txt */
import { F as FONT_MENU } from './toolbar.js?v=bb55a6e4';
import './combobox.js?v=bb55a6e4';
import './styles.js?v=bb55a6e4';
import './foundation.js?v=bb55a6e4';
import './connectivity.js?v=bb55a6e4';
import './primitives.js?v=bb55a6e4';
import './icons.js?v=bb55a6e4';
import './queryLifecycle.js?v=bb55a6e4';
import './dropdown.js?v=bb55a6e4';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_font_family
 * @matrix editor : font-family reload
 */
class FontFamilyPicker {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.name = "setFontFamily";
		this.usedWithEditor = true;
		this.active = false;
		this.toggles = new Map();
	}

	_fontToggle(style, name) {
		const fontButton = document.createElement("button");
		fontButton.className = `cursor-pointer rounded bg-slate-200 px-3 py-1.5 text-base transition-transform hover:scale-110 hover:bg-slate-300 data-[active=true]:bg-slate-300 sm:text-sm`;
		fontButton.textContent = name;
		fontButton.dataset.style = style;
		fontButton.title = name;
		fontButton.dataset.active = "false";
		return fontButton;
	}

	setActiveFontStyle(activeFont) {
		this.toggles.forEach((toggle, style) => {
			const isActive = style === activeFont;
			if (isActive !== toggle.active) {
				toggle.button.dataset.active = isActive ? "true" : "false";
				toggle.active = isActive;
			}
		});
	}

	init() {
		const fontOptions = this.toolbar.element.appendChild(
			document.createElement("div"),
		);
		fontOptions.dataset.option = this.name;
		fontOptions.className = `group mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form="setFontFamily"]/toolbar:flex`;

		FONT_MENU.forEach(({ style, name }) => {
			const fontButton = this._fontToggle(style, name);
			this.toggles.set(style, { active: false, button: fontButton });
		});

		fontOptions.append(
			...Array.from(this.toggles.values()).map((toggle) => toggle.button),
		);
		this.active = true;

		fontOptions.addEventListener("click", (e) => {
			const fontButton = e.target.closest("button");
			if (!fontButton) return;

			const toggle = this.toggles.get(fontButton.dataset.style);

			const currentActive = Array.from(this.toggles.values()).find(
				(t) => t.active && t !== toggle,
			);
			if (currentActive) {
				currentActive.active = false;
				currentActive.button.dataset.active = "false";
			}

			toggle.active = !toggle.active;
			fontButton.dataset.active = toggle.active ? "true" : "false";

			if (toggle.active) {
				this.toolbar.editor
					.chain()
					.focus()
					.setFontFamily(fontButton.dataset.style)
					.run();
			} else {
				this.toolbar.editor.chain().focus().unsetFontFamily().run();
			}
		});
	}
}

export { FontFamilyPicker as setFontFamily };
