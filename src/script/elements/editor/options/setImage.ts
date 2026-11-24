import { STYLES } from "../../../generated/styles.mjs";
import { IMAGE_GROUPS } from "../config.ts";
import type { Toolbar } from "../toolbar.ts";
import { runToolCommand, ToolbarButton } from "./toolbarButtons.ts";

class ImageOptions {
	declare toggles: Record<string, ToolbarButton>;
	declare imagePosition: string | null;
	declare toolbar: Toolbar;
	declare name: "setImage";
	declare usedWithEditor: boolean;
	declare active: boolean;
	constructor(toolbar: Toolbar) {
		this.toolbar = toolbar;
		this.name = "setImage";
		this.usedWithEditor = true;
		this.active = false;
		this.toggles = {};
		this.imagePosition = null;
	}

	init() {
		const imageSettings = this.toolbar.element.appendChild(
			document.createElement("div"),
		);
		imageSettings.dataset.option = this.name;
		imageSettings.dataset.position = "false";
		imageSettings.className = `${STYLES.editor.toolbar.imageSettings}`;

		IMAGE_GROUPS.forEach((group, index) => {
			const wrapper = imageSettings.appendChild(document.createElement("div"));
			wrapper.className = `${STYLES.editor.toolbar.tools}`;
			group.forEach((settings) => {
				const option = new ToolbarButton(this.toolbar);
				option.init(settings);
				option.onClick = () => this.toggleOption(option);
				this.toggles[String(option.name)] = option;
				if (option.name) {
					this.toolbar.options[option.name] = option;
				}
				wrapper.appendChild(option.button);
			});
			if (index < IMAGE_GROUPS.length - 1) {
				const divider = document.createElement("div");
				divider.className = `${STYLES.editor.toolbar.divider}`;
				imageSettings.appendChild(divider);
			}
		});
	}

	toggleOption(option: ToolbarButton) {
		const currentOption = Object.values(this.toggles).find(
			(toggle) => toggle.active && toggle.name,
		);
		option.active = !option.active;
		option.active ? option.enable() : option.disable();
		currentOption?.disable();

		runToolCommand(
			this.toolbar.editor.chain(),
			option.command,
			option.args,
			true,
		);
	}
}

export { ImageOptions as setImage };
