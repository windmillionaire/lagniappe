import { getMarkRange } from "@tiptap/core";
import { STYLES } from "styles";
import { debounce, ENDPOINTS, request } from "../../../shared";
import { BaseForm } from "../../base/baseForm";
import { buttons } from "../../buttons";
import { Combobox } from "../../combobox/combobox";
import { Results } from "../../combobox/results";
import { primitives } from "../../primitives";
import { normalizeLinkAttributes } from "../extensions/linkAttributes.mjs";

const ABSOLUTE_URL_PATTERN = /^[a-z][a-z0-9+.-]*:/i;
const BARE_DOMAIN_PATTERN = /^[^\s/]+\.[^\s]+(?:\/.*)?$/;

/**
 * @testable infrastructure
 */
class LinkSearchBox extends Combobox {
	constructor(element, addLink) {
		super(element);
		this.addLink = addLink;
		this.index = "search";
		this.results = new Results(this.index);
		this.endpoints = ENDPOINTS.search;
		this.placement = "bottom-start";
		this._debouncedInput = debounce(this._input.bind(this), 200);
	}

	init() {
		this.styles.panel = `${STYLES.dropdown.panel} ${STYLES.editor.toolbar.portalIconContext} w-64 sm:w-96 mt-2`;
		this.element.addEventListener("input", this._debouncedInput);
		super.init();
	}

	_input(event) {
		const query = event.target.value.trim();
		if (this.addLink.linkHref(query)) {
			this.hidePanel();
			return;
		}

		if (query.length > 2) {
			this._search(query);
		} else if (query.length === 0) {
			this.hidePanel();
		}
	}

	elementClick(event) {
		super.elementClick(event);
		if (!this.panelOpen && this.options.length > 0) this.showPanel();
	}

	async _search(query) {
		const params = new URLSearchParams();
		params.set("q", query);
		const response = await request.get(this.endpoints.bar, params);
		if (response.ok) {
			this.updatePanel(response.results || null);
		}
		this.showPanel();
	}

	selectOption(option) {
		if (!option.dataset.url) return;

		this.results.save(option);
		this.hidePanel();
		this.addLink.applySearchResult(option.dataset.url);
	}

	destroy() {
		this.element.removeEventListener("input", this._debouncedInput);
		super.destroy();
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_external_link_persists_searches_and_unlinks
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_link_form_dismissal_preserves_selection_interactions
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
 * @features editor
 * @dimensions link reload external-link internal-link shortcut search unlink form-dismissal selection
 */
class AddLink {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.editor = toolbar.editor;
		this.submit = this.submit.bind(this);
		this.name = "addLink";
		this.messages = {
			select: "Please select some text first",
			link: "Please add a URL",
			submit: "Set Link",
		};
		this.usedWithEditor = false;
		this._onSelectionUpdate = this._onSelectionUpdate.bind(this);
		this._active = false;
		this.linkState = null;
		this.combobox = null;
	}

	get active() {
		return this._active;
	}

	set active(value) {
		this._active = value;
		if (value) {
			this.captureSelection();
			this.focus();
			this.editor.on("selectionUpdate", this._onSelectionUpdate);
		} else {
			this.editor.off("selectionUpdate", this._onSelectionUpdate);
			this.editor.commands.clearSelectionHighlight();
		}
	}

	get emailMode() {
		return this.toolbar.kind === "email";
	}

	_onSelectionUpdate() {
		if (this._active) {
			this.captureSelection();
		}
	}

	init() {
		this.target = this.toolbar.element.appendChild(
			document.createElement("form"),
		);
		this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addLink"]/toolbar:flex`;
		this.target.dataset.option = this.name;

		this.link = primitives.input({
			name: "link",
			placeholder: "Paste URL or search...",
			type: "search",
		});
		this.combobox = new LinkSearchBox(this.link, this);

		const submit = buttons.submit({
			kind: "editor",
		});
		this.html = [this.link, submit];

		this.form = new BaseForm(this);
		this.form.init();
		this.form.destroyables.push(this.combobox);
		this.combobox.init();
	}

	focus() {
		this.link?.focus();
		this.link?.select();
	}

	captureSelection() {
		const { from, to } = this.editor.state.selection;
		if (from !== to) {
			this.editor.commands.setSelectionHighlight();
		} else {
			this.editor.commands.clearSelectionHighlight();
		}
		this.linkState = this.findCurrentLink();
		this.link.value = this.displayHref(this.linkState?.attrs?.href || "");
	}

	findCurrentLink() {
		const linkType = this.editor.state.schema.marks.link;
		if (!linkType) return null;

		const { selection } = this.editor.state;
		if (selection.empty) {
			const range = getMarkRange(selection.$from, linkType);
			return range ? this.singleLinkInRange(range) : null;
		}

		return this.singleLinkInRange({
			from: selection.from,
			to: selection.to,
		});
	}

	singleLinkInRange(range) {
		const linkType = this.editor.state.schema.marks.link;
		const links = new Map();

		this.editor.state.doc.nodesBetween(range.from, range.to, (node, pos) => {
			if (!node.isText) return true;

			const mark = node.marks.find((mark) => mark.type === linkType);
			if (!mark) return true;

			const key = JSON.stringify(mark.attrs);
			const from = Math.max(range.from, pos);
			const to = Math.min(range.to, pos + node.nodeSize);
			const link = links.get(key) || { attrs: mark.attrs, from, to };
			link.from = Math.min(link.from, from);
			link.to = Math.max(link.to, to);
			links.set(key, link);

			return true;
		});

		const values = Array.from(links.values());
		if (values.length !== 1) return null;

		const link = values[0];
		return {
			attrs: link.attrs,
			range: { from: link.from, to: link.to },
		};
	}

	highlightRange() {
		return this.editor.commands.getSelectionHighlightRange();
	}

	activeRange() {
		return this.linkState?.range || this.highlightRange();
	}

	displayHref(href) {
		if (!href || !this.emailMode) return href;

		return this.fullyQualifiedUrl(href) || href;
	}

	linkHref(value) {
		const href = value.trim();
		if (!href) return "";

		if (this.emailMode) {
			return this.fullyQualifiedUrl(href);
		}

		if (
			ABSOLUTE_URL_PATTERN.test(href) ||
			href.startsWith("//") ||
			href.startsWith("/") ||
			href.startsWith("#") ||
			href.startsWith("?")
		) {
			return href;
		}

		if (BARE_DOMAIN_PATTERN.test(href)) {
			return `https://${href}`;
		}

		return null;
	}

	fullyQualifiedUrl(value) {
		const href = value.trim();
		if (!href) return "";

		try {
			if (ABSOLUTE_URL_PATTERN.test(href)) {
				return new URL(href).href;
			}

			if (href.startsWith("//")) {
				return new URL(`${window.location.protocol}${href}`).href;
			}

			if (
				href.startsWith("/") ||
				href.startsWith("#") ||
				href.startsWith("?")
			) {
				return new URL(href, window.location.origin).href;
			}

			return new URL(`https://${href}`).href;
		} catch (_error) {
			return null;
		}
	}

	linkAttributes(href) {
		if (this.emailMode) return { href };

		return normalizeLinkAttributes({ href });
	}

	applySearchResult(url) {
		const href = this.emailMode ? this.fullyQualifiedUrl(url) : url;
		if (!href) {
			this.form.showError(this.messages.link);
			return;
		}

		this.link.value = href;
		this.submit();
	}

	reset() {
		this.linkState = null;
		this.link.value = "";
		this.combobox?.hidePanel();
		this.form?.resetSubmitButton();
	}

	submit() {
		const range = this.activeRange();
		const href = this.linkHref(this.link.value);

		if (href && range) {
			this.editor
				.chain()
				.focus()
				.setTextSelection(range)
				.setLink(this.linkAttributes(href))
				.run();
			this.form.resetSubmitButton();
			this.toolbar.closeForm(this.name);
		} else if (!this.link.value.trim() && range) {
			const linkRange =
				this.linkState?.range || this.singleLinkInRange(range)?.range;
			if (!linkRange) {
				this.form.showError(this.messages.link);
				return;
			}
			this.editor.chain().focus().setTextSelection(linkRange).unsetLink().run();
			this.form.resetSubmitButton();
			this.toolbar.closeForm(this.name);
		} else if (!range) {
			this.form.showError(this.messages.select);
		} else {
			this.form.showError(this.messages.link);
		}
	}

	destroy() {
		this.form?.destroy();
	}
}

export { AddLink as addLink };
