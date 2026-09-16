/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb1ed2ee';
import { I as IMAGE_GROUPS } from './toolbar.js?v=bb1ed2ee';
import { ToolbarButton } from './toolbarButtons.js?v=bb1ed2ee';
import './combobox.js?v=bb1ed2ee';
import './foundation.js?v=bb1ed2ee';
import './upstreamUnavailable.js?v=bb1ed2ee';
import './connectivity.js?v=bb1ed2ee';
import './primitives.js?v=bb1ed2ee';
import './icons.js?v=bb1ed2ee';
import './queryLifecycle.js?v=bb1ed2ee';
import './dropdown.js?v=bb1ed2ee';
import './buttons.js?v=bb1ed2ee';
import './formatting.js?v=bb1ed2ee';

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
