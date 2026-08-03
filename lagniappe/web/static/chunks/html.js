/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=b26991f5';
import { r as request } from './request.js?v=b26991f5';
import './connectivity.js?v=b26991f5';
import { waitForAttribute } from './utilities.js?v=b26991f5';
import { i as independentEditor, T as Toolbar } from './toolbar.js?v=b26991f5';
import { E as ENDPOINTS } from './endpoints.js?v=b26991f5';
import { C as Condition } from './base2.js?v=b26991f5';
import './errors.js?v=b26991f5';
import './combobox.js?v=b26991f5';
import './primitives.js?v=b26991f5';
import './icons.js?v=b26991f5';
import './dropdown.js?v=b26991f5';
import './baseForm.js?v=b26991f5';
import './loader.js?v=b26991f5';
import './select2.js?v=b26991f5';
import './results.js?v=b26991f5';
import './formatting.js?v=b26991f5';
import './submitter.js?v=b26991f5';

/**
 * @testable infrastructure
 */
class IndependentDocument {
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

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
 * @features html-field
 * @dimensions builder-html-field
 */
class HtmlEditor extends Condition {
	constructor(builder) {
		super(builder);
		this.expand = true;
		this.endpoints = ENDPOINTS.html(builder.key, this.element.schema.id);
		this.kind = "form";
		this._initialized = false;
	}

	init() {
		if (this._initialized) return;
		this._initialized = true;

		const container = document.createElement("div");
		container.className =
			"border-1 border-slate-300 rounded-md overflow-hidden";

		const editor = new IndependentDocument({
			target: container,
			kind: this.kind,
			endpoints: this.endpoints,
		});
		editor.init();
		this.destroyables.push(editor);

		this.setTitle("Text Editor");
		this.target.append(this.header, container);
	}
}

export { HtmlEditor as default };
