/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=be1b1fb2';
import { I as IMAGE_GROUPS } from './toolbar.js?v=be1b1fb2';
import { ToolbarButton } from './toolbarButtons.js?v=be1b1fb2';
import './combobox.js?v=be1b1fb2';
import './request.js?v=be1b1fb2';
import './errors.js?v=be1b1fb2';
import './connectivity.js?v=be1b1fb2';
import './utilities.js?v=be1b1fb2';
import './primitives.js?v=be1b1fb2';
import './icons.js?v=be1b1fb2';
import './endpoints.js?v=be1b1fb2';
import './dropdown.js?v=be1b1fb2';

/**
 * @testable infrastructure
 */
class ImageOptions {
	constructor(toolbar) {
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
				this.toggles[option.name] = option;
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

	toggleOption(option) {
		const currentOption = Object.values(this.toggles).find(
			(toggle) => toggle.active && toggle.name,
		);
		option.active = !option.active;
		option.active ? option.enable() : option.disable();
		currentOption?.disable();

		this.toolbar.editor.chain()[option.command](option.args).run();
	}
}

export { ImageOptions as setImage };
