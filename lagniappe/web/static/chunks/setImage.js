/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b41d0cfc';
import { I as IMAGE_GROUPS } from './toolbar.js?v=b41d0cfc';
import { ToolbarButton } from './toolbarButtons.js?v=b41d0cfc';
import './combobox.js?v=b41d0cfc';
import './foundation.js?v=b41d0cfc';
import './upstreamUnavailable.js?v=b41d0cfc';
import './connectivity.js?v=b41d0cfc';
import './primitives.js?v=b41d0cfc';
import './icons.js?v=b41d0cfc';
import './queryLifecycle.js?v=b41d0cfc';
import './dropdown.js?v=b41d0cfc';
import './buttons.js?v=b41d0cfc';
import './formatting.js?v=b41d0cfc';

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
