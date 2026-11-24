import { COLOR_MENU } from "../config.ts";

import type { Toolbar } from "../toolbar.ts";

class ColorPicker {
	declare toggles: Map<string, { active: boolean; button: HTMLButtonElement }>;
	declare toolbar: Toolbar;
	declare name: "setColor";
	declare usedWithEditor: boolean;
	declare active: boolean;
	constructor(toolbar: Toolbar) {
		this.toolbar = toolbar;
		this.name = "setColor";
		this.usedWithEditor = true;
		this.active = false;
		this.toggles = new Map();
	}

	_colorSwatch(color: string, title: string) {
		const colorButton = document.createElement("button");
		colorButton.className = `size-6 rounded transition-transform hover:scale-110 hover:outline-2 hover:outline-offset-2 data-[active=true]:outline-2 data-[active=true]:outline-offset-2`;
		colorButton.style.backgroundColor = color;
		colorButton.style.outlineColor = color;
		colorButton.title = title;
		colorButton.dataset.active = "false";
		colorButton.dataset.color = color;
		return colorButton;
	}

	setActiveColor(activeColor: string | null | undefined) {
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
			const colorButton = (e.target as Element | null)?.closest("button");
			if (!colorButton) return;

			const color = colorButton.dataset.color;
			if (!color) return;
			const toggle = this.toggles.get(color);
			if (!toggle) return;

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
				this.toolbar.editor.chain().focus().setColor(color).run();
			} else {
				this.toolbar.editor.chain().focus().unsetColor().run();
			}
		});
	}
}

export { ColorPicker as setColor };
