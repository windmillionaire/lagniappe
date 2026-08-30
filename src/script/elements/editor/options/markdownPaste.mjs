import { STYLES } from "styles";
import { ENDPOINTS, generateElementId, request } from "../../../shared";
import { buttons } from "../../buttons";

/**
 * Own the nonmodal decision and asynchronous replacement for one pasted
 * Markdown source block at a time.
 *
 * @testable true
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_markdown_table_preserves_table_after_reload
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_common_markdown_preserves_formatting
 * @tests tests_e2e/004_projects/test_004d_document.py::test_keeping_pasted_markdown_preserves_source_block
 * @matrix editor markdown : conversion paste source-block
 */
export class MarkdownPastePrompt {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.editor = toolbar.editor;
		this.current = null;
		this.requestController = null;
		this.requestGeneration = 0;
		this.applying = false;
		this.confirm = this.open.bind(this);
		this.submit = this._submit.bind(this);
		this.keydown = this._keydown.bind(this);
		this.transaction = this._transaction.bind(this);
	}

	init() {
		const headingId = generateElementId("markdown-paste-heading");
		this.target = document.createElement("form");
		this.target.className = STYLES.editor.toolbar.markdownPrompt;
		this.target.dataset.role = "markdown-paste-prompt";
		this.target.dataset.active = "false";
		this.target.setAttribute("aria-labelledby", headingId);

		const heading = document.createElement("h3");
		heading.id = headingId;
		heading.className = STYLES.editor.toolbar.optionHeader;
		heading.textContent = "Convert pasted text?";

		const message = document.createElement("p");
		message.className = STYLES.editor.toolbar.markdownPromptMessage;
		message.textContent =
			"This looks like Markdown or wrapped text. Convert it to formatted document content?";

		this.status = document.createElement("p");
		this.status.className = STYLES.editor.toolbar.markdownPromptStatus;
		this.status.dataset.role = "markdown-paste-status";
		this.status.setAttribute("role", "status");
		this.status.setAttribute("aria-live", "polite");

		const actions = document.createElement("div");
		actions.className = STYLES.editor.toolbar.markdownPromptActions;
		this.convertAction = buttons.active({
			type: "submit",
			text: "Convert",
			processingText: "Converting…",
			kind: "editor",
			data: { action: "convert" },
		});
		this.keepButton = buttons.default({
			type: "submit",
			text: "Keep as text",
			style: STYLES.editor.toolbar.markdownPromptKeep,
			data: { action: "keep" },
		});
		actions.append(this.convertAction.element, this.keepButton);
		this.target.append(heading, message, this.status, actions);
		this.toolbar.element.appendChild(this.target);

		this.target.addEventListener("submit", this.submit);
		this.target.addEventListener("keydown", this.keydown);
		this.editorElement = this.editor.view.dom;
		this.editorElement.addEventListener("keydown", this.keydown);
		this.editor.on("transaction", this.transaction);
		this.editor.storage.editorPaste.confirm = this.confirm;
	}

	_source() {
		if (!this.current || this.editor.isDestroyed) return null;
		const storedRange = this.editor.storage.trackedRanges.ranges.get(
			this.current.rangeKey,
		);
		if (!storedRange) return null;
		const range = { ...storedRange };
		const node = this.editor.state.doc.nodeAt(range.from);
		if (
			node?.type.name !== "markdownSource" ||
			range.to !== range.from + node.nodeSize
		) {
			return null;
		}
		return { range, node, text: node.textContent };
	}

	open({ rangeKey }) {
		if (typeof rangeKey !== "string" || !rangeKey) return;
		if (this.current) this._close({ clearRange: true });
		this.current = { rangeKey, submittedText: null };
		if (!this._source()) {
			this._close({ clearRange: false });
			return;
		}
		this._setStatus("");
		this.convertAction.deactivate("Convert");
		this.target.dataset.active = "true";
	}

	_submit(event) {
		event.preventDefault();
		event.stopPropagation();
		if (event.submitter?.dataset.action === "keep") {
			this._close({ clearRange: true });
			return;
		}
		void this._convert();
	}

	_keydown(event) {
		if (event.key !== "Escape" || !this.current) return;
		event.preventDefault();
		event.stopPropagation();
		this._close({ clearRange: true });
	}

	_transaction() {
		if (!this.current || this.applying) return;
		const source = this._source();
		if (!source) {
			this._close({ clearRange: false });
			return;
		}
		if (this.requestController && this.current.submittedText !== source.text) {
			this._abortRequest();
			this._setStatus("The source changed. Convert again when it is ready.");
		}
	}

	async _convert() {
		const source = this._source();
		if (!source || this.requestController) return;
		if (!source.text) {
			this._setStatus("There is no source text to convert.");
			return;
		}

		const generation = ++this.requestGeneration;
		const rangeKey = this.current.rangeKey;
		this.current.submittedText = source.text;
		this.requestController = new AbortController();
		this._setStatus("");
		this.convertAction.activate();

		const response = await request.post(
			ENDPOINTS.markdown,
			{ markdown: source.text },
			{ signal: this.requestController.signal },
		);
		if (
			generation !== this.requestGeneration ||
			this.current?.rangeKey !== rangeKey
		) {
			return;
		}

		this.requestController = null;
		this.convertAction.deactivate("Convert");
		const currentSource = this._source();
		if (!currentSource) {
			this._close({ clearRange: false });
			return;
		}
		if (currentSource.text !== source.text) {
			this.current.submittedText = null;
			this._setStatus("The source changed. Convert again when it is ready.");
			return;
		}
		if (!response?.ok || typeof response.markup !== "string") {
			this.current.submittedText = null;
			this._setStatus(response?.error || "Unable to convert the pasted text.");
			return;
		}

		this.applying = true;
		const chain = this.editor.chain().focus();
		const converted = response.markup
			? chain.insertContentAt(currentSource.range, response.markup).run()
			: chain.deleteRange(currentSource.range).run();
		this.applying = false;
		if (converted) {
			this._close({ clearRange: false });
		} else {
			this._setStatus("Unable to replace the pasted source.");
		}
	}

	_abortRequest() {
		this.requestGeneration += 1;
		this.requestController?.abort();
		this.requestController = null;
		if (this.current) this.current.submittedText = null;
		this.convertAction.deactivate("Convert");
	}

	_setStatus(message) {
		this.status.textContent = message;
	}

	_close({ clearRange }) {
		const rangeKey = this.current?.rangeKey;
		this.current = null;
		this._abortRequest();
		this._setStatus("");
		this.target.dataset.active = "false";
		if (clearRange && rangeKey && !this.editor.isDestroyed) {
			this.editor.commands.clearTrackedRange(rangeKey);
		}
	}

	destroy() {
		const storage = this.editor.storage.editorPaste;
		if (storage?.confirm === this.confirm) storage.confirm = null;
		this.current = null;
		this._abortRequest();
		this.target.removeEventListener("submit", this.submit);
		this.target.removeEventListener("keydown", this.keydown);
		this.editorElement?.removeEventListener("keydown", this.keydown);
		this.editor.off("transaction", this.transaction);
		this.target.remove();
	}
}
