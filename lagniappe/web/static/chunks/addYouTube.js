/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseForm } from './baseForm.js?v=bc116afe';
import { b as buttons } from './buttons.js?v=bc116afe';
import { p as primitives } from './primitives.js?v=bc116afe';
import './foundation.js?v=bc116afe';
import './connectivity.js?v=bc116afe';
import './icons.js?v=bc116afe';
import './loader.js?v=bc116afe';
import './styles.js?v=bc116afe';
import './formatting.js?v=bc116afe';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_youtube
 * @features editor
 * @dimensions youtube-embed
 */
class AddYouTube {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.submit = this.submit.bind(this);
		this.endpoints = toolbar.endpoints;
		this.name = "addYouTube";
		this.messages = {
			url: "Please add a YouTube URL",
			submit: "Add YouTube Video",
		};
		this._active = false;
	}

	get active() {
		return this._active;
	}

	set active(value) {
		this._active = value;
		this.link.focus();
	}

	init() {
		this.target = this.toolbar.element.appendChild(
			document.createElement("form"),
		);
		this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addYouTube"]/toolbar:flex`;
		this.target.dataset.option = this.name;

		this.link = primitives.input({
			name: "url",
			placeholder: "YouTube URL...",
			type: "url",
		});
		const submit = buttons.submit({
			kind: "editor",
		});
		this.html = [this.link, submit];

		this.form = new BaseForm(this);
		this.form.init();
	}

	submit() {
		const url = this.link.value;
		if (url) {
			this.toolbar.editor.chain().focus().setYoutubeVideo({ src: url }).run();
			this.form.resetSubmitButton();
			this.toolbar.toggleForm(this.name);
			this.link.value = "";
		} else {
			this.form.showError(this.messages.url);
		}
	}
}

export { AddYouTube as addYouTube };
