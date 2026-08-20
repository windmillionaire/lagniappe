import { STYLES } from "styles";
import { request, waitForAttribute } from "../../shared";
import { independentEditor } from "./editor";
import { Toolbar } from "./toolbar";

/**
 * @testable infrastructure
 */
export class IndependentDocument {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.content = "";
	}

	init() {
		this._createContainer();

		if (!this.readonly) {
			this._initEditor();
			this._initToolbar();
		}

		request.get(this.endpoints.getContent).then((response) => {
			if (this.readonly) {
				this.container.innerHTML = response.markup || "";
			} else if (response.markup || response.html) {
				this.content = (response.html || response.markup).trim();
			}
			this.container.setAttribute("loaded", "");
		});
	}

	_createContainer() {
		this.container = document.createElement("div");
		this.container.dataset.role = "editor";
		this.container.className = `${STYLES.editor.container}`;
		this.target.replaceChildren(this.container);
	}

	async _saveDocument() {
		const loaded = this.container.hasAttribute("loaded");
		if (!loaded || this.saving) return;
		this.saving = true;

		const html = this.editor.getHTML();
		const empty = html.trim() === "<p></p>" || html.trim() === "<p><br></p>";
		if (empty) {
			this.saving = false;
			return;
		}

		if (this.content !== html) {
			this.content = html;
			await request.put(this.endpoints.save, { html: this.content });
		}
		this.saving = false;
	}

	_initEditor() {
		this.editor = independentEditor(this.container);

		this.editor.on("create", async () => {
			await waitForAttribute(this.container, "loaded");

			if (this.content.length > 0) {
				this.editor.commands.setContent(this.content);
			} else {
				this.container
					.querySelector(".ProseMirror")
					.classList.add("min-h-[200px]");
				this.editor.commands.focus("start");
			}
		});

		this.editor.on("blur", () => {
			requestAnimationFrame(() => {
				const activeElement = document.activeElement;
				if (activeElement.closest("[data-role='toolbar'], [role='listbox']"))
					return;
				this._saveDocument();
			});
		});

		this.editor.on("destroy", () => {
			this._saveDocument();
		});
	}

	_initToolbar() {
		this.toolbar = new Toolbar(this);
		this.toolbar.init();
		this.target.prepend(this.toolbar.element);
	}

	hide() {
		this.target.classList.add("hidden");
	}

	show() {
		this.target.classList.remove("hidden");
	}

	destroy() {
		if (this.editor) {
			this.editor.destroy();
		}
		if (this.toolbar) {
			this.toolbar.destroy();
		}
	}
}
