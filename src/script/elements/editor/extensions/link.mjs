import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import { getMarkRange, Mark } from "@tiptap/core";
import { isAllowedUri, Link } from "@tiptap/extension-link";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { ENDPOINTS, request } from "../../../shared";
import { normalizeLinkAttributes } from "./linkAttributes.mjs";

const LINK_EDIT_EVENT = "editor-link-edit";
const ACTIONS = new Set(["open", "edit", "remove"]);

// @testable false
// @reason helper-owned-by-custom-link-normalization
const equalLinkAttributes = (left = {}, right = {}) => {
	const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
	for (const key of keys) {
		if ((left[key] ?? null) !== (right[key] ?? null)) return false;
	}
	return true;
};

// @testable false
// @reason helper-owned-by-custom-link-normalization
const linkAttributesAllowed = (extension, href) =>
	extension.options.isAllowedUri(href, {
		defaultValidate: (url) => !!isAllowedUri(url, extension.options.protocols),
		protocols: extension.options.protocols,
		defaultProtocol: extension.options.defaultProtocol,
	});

// @testable false
// @reason helper-owned-by-custom-link-normalization
const normalizeLinkMarks = (type) =>
	new Plugin({
		key: new PluginKey("normalizeLinkMarks"),
		appendTransaction: (transactions, _oldState, newState) => {
			if (!transactions.some((transaction) => transaction.docChanged)) {
				return null;
			}

			let tr = null;
			newState.doc.descendants((node, pos) => {
				if (!node.isText) return true;

				for (const mark of node.marks) {
					if (mark.type !== type) continue;

					const attrs = normalizeLinkAttributes(mark.attrs);
					if (equalLinkAttributes(mark.attrs, attrs)) continue;

					const from = pos;
					const to = pos + node.nodeSize;
					tr ??= newState.tr;
					tr.removeMark(from, to, type);
					tr.addMark(from, to, type.create(attrs));
				}

				return true;
			});

			return tr;
		},
	});

// @testable true
// @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
// @features editor
// @dimensions link internal-link click-navigation popover
const linkFromEvent = (editor, event) => {
	const target = event.target;
	const AnchorElement = globalThis.HTMLAnchorElement;
	const Element = globalThis.Element;
	const targetElement =
		Element && target instanceof Element ? target : target?.parentElement;
	const link =
		AnchorElement && targetElement instanceof AnchorElement
			? targetElement
			: targetElement?.closest("a");

	if (!link || !editor.view.dom.contains(link)) return null;

	return link;
};

// @testable true
// @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
// @features editor
// @dimensions link internal-link click-navigation popover
const opensInCurrentTab = (href) =>
	Boolean(href) &&
	!String(href).startsWith("//") &&
	!/^[a-z][a-z0-9+.-]*:/i.test(String(href));

// @testable false
// @covered-by src/script/elements/editor/extensions/link.mjs::LinkPopover
// @reason display fallback supports the editable link popover contract
const displayUrl = (href) => {
	const value = String(href || "").trim();
	if (!value) return "";

	try {
		const url = new URL(value, globalThis.window?.location?.href);
		if (url.origin === globalThis.window?.location?.origin) {
			return `${url.pathname}${url.search}${url.hash}`;
		}
		return `${url.host}${url.pathname}${url.search}${url.hash}`;
	} catch (_error) {
		return value;
	}
};

// @testable false
// @covered-by src/script/elements/editor/extensions/link.mjs::LinkPopover
// @reason link mark discovery is exercised through editable link popover actions
const linkRangeFromDom = (editor, link) => {
	try {
		const from = editor.view.posAtDOM(link, 0);
		const to = editor.view.posAtDOM(link, link.childNodes.length);
		if (Number.isInteger(from) && Number.isInteger(to) && to > from) {
			return { from, to };
		}
	} catch (_error) {
		return null;
	}

	return null;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/link.mjs::LinkPopover
// @reason link mark discovery is exercised through editable link popover actions
const rangeMatchesLink = (editor, range, href) => {
	const linkType = editor.state.schema.marks.link;
	let matched = false;

	editor.state.doc.nodesBetween(range.from, range.to, (node) => {
		if (!node.isText) return true;

		const mark = node.marks.find((mark) => mark.type === linkType);
		if (!mark) return true;

		const attrs = normalizeLinkAttributes({ href: mark.attrs.href });
		matched = !href || attrs.href === href;
		return false;
	});

	return matched;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/link.mjs::LinkPopover
// @reason link mark discovery is exercised through editable link popover actions
const linkRangeFromPosition = (editor, pos, link) => {
	const linkType = editor.state.schema.marks.link;
	if (!linkType) return null;

	const href = normalizeLinkAttributes({
		href: link.getAttribute("href"),
		class: link.getAttribute("class"),
	}).href;
	const docEnd = editor.state.doc.content.size;
	const positions = [pos, pos - 1, pos + 1].filter(
		(value) => Number.isInteger(value) && value >= 0 && value <= docEnd,
	);

	for (const position of positions) {
		const range = getMarkRange(editor.state.doc.resolve(position), linkType);
		if (range && rangeMatchesLink(editor, range, href)) return range;
	}

	return null;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/link.mjs::LinkPopover
// @reason link mark discovery is exercised through editable link popover actions
const linkRangeFromClick = (editor, pos, event, link) => {
	const directRange = linkRangeFromPosition(editor, pos, link);
	if (directRange) return directRange;

	const coords = editor.view.posAtCoords({
		left: event.clientX,
		top: event.clientY,
	});
	if (coords) {
		const coordsRange = linkRangeFromPosition(editor, coords.pos, link);
		if (coordsRange) return coordsRange;
	}

	return linkRangeFromDom(editor, link);
};

// @testable true
// @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
// @features editor
// @dimensions link internal-link click-navigation popover
const navigateLink = (link) => {
	const attributes = normalizeLinkAttributes({
		href: link.getAttribute("href"),
		target: link.getAttribute("target"),
		rel: link.getAttribute("rel"),
		class: link.getAttribute("class"),
	});

	if (!attributes.href) return false;

	if (opensInCurrentTab(attributes.href)) {
		globalThis.window.location.assign(attributes.href);
		return true;
	}

	globalThis.window.open(
		link.href || attributes.href,
		attributes.target || "_blank",
	);
	return true;
};

/**
 * @testable true
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_document_mentions_use_anchored_menu_and_profile_links
 * @pair mentions:link-popover
 */
const editableMentionClickGuard = (editor) =>
	new Plugin({
		key: new PluginKey("editableMentionClickGuard"),
		view: (view) => {
			/**
			 * @testable false
			 * @covered-by src/script/elements/editor/extensions/link.mjs::editableMentionClickGuard
			 * @reason capture-phase suppression is exercised through the mention popover
			 */
			const preventNavigation = (event) => {
				if (!editor.isEditable || event.button !== 0) return;
				const link = linkFromEvent(editor, event);
				if (link?.matches('[data-type="lagniappe-mention"]')) {
					event.preventDefault();
				}
			};
			view.dom.addEventListener("click", preventNavigation, true);
			return {
				destroy: () =>
					view.dom.removeEventListener("click", preventNavigation, true),
			};
		},
	});

// @testable true
// @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
// @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_document_mentions_use_anchored_menu_and_profile_links
// @features editor
// @dimensions link popover click-navigation
// @pairs mentions:link-popover mentions:unlink
class LinkPopover {
	constructor(editor) {
		this.editor = editor;
		this.panel = null;
		this.link = null;
		this.range = null;
		this.cleanup = null;
		this.observer = null;
		this.requestId = 0;

		this._documentPointerDown = this._documentPointerDown.bind(this);
		this._documentKeydown = this._documentKeydown.bind(this);
		this._panelClick = this._panelClick.bind(this);
		this._handleIntersection = this._handleIntersection.bind(this);
	}

	show(link, range) {
		const attrs = normalizeLinkAttributes({
			href: link.getAttribute("href"),
			target: link.getAttribute("target"),
			rel: link.getAttribute("rel"),
			class: link.getAttribute("class"),
		});
		if (!attrs.href) return false;

		this.close();
		this.isMention = link.matches('[data-type="lagniappe-mention"]');
		this.link = link;
		this.range = range;
		this.href = attrs.href;
		this.panel = this._createPanel(link.textContent?.trim() || attrs.href);
		document.body.appendChild(this.panel);
		this._addHandlers();
		this._startAutoUpdate();
		this._startObserver();
		this._loadPreview();
		return true;
	}

	_createPanel(title) {
		const panel = document.createElement("div");
		panel.dataset.role = "editor-link-popover";
		panel.dataset.linkType = this.isMention ? "mention" : "link";
		panel.setAttribute("role", "dialog");
		panel.setAttribute(
			"aria-label",
			this.isMention ? "Mention options" : "Link options",
		);
		panel.className =
			"absolute z-101 flex flex-col gap-2 rounded-md bg-white p-3 text-sm shadow-lg outline outline-base-light/50";
		panel.style.width = "min(22rem, calc(100vw - 1rem))";

		const header = panel.appendChild(document.createElement("div"));
		header.className = "flex flex-col gap-0.5";

		const titleElt = header.appendChild(document.createElement("div"));
		titleElt.dataset.role = "link-preview-title";
		titleElt.className = "truncate font-semibold text-kind-default";
		titleElt.textContent = title || displayUrl(this.href);

		const urlElt = header.appendChild(document.createElement("div"));
		urlElt.dataset.role = "link-preview-url";
		urlElt.className = "truncate text-xs text-base-medium";
		urlElt.textContent = displayUrl(this.href);

		const description = panel.appendChild(document.createElement("p"));
		description.dataset.role = "link-preview-description";
		description.className = "hidden text-sm leading-snug text-base-default";

		const actions = panel.appendChild(document.createElement("div"));
		actions.className =
			"flex flex-row flex-wrap items-center gap-1 border-t border-base-light/50 pt-2";
		actions.append(this._button("open", "Open"));
		if (!this.isMention) actions.append(this._button("edit", "Edit"));
		actions.append(this._button("remove", "Remove", "text-delete-default"));

		return panel;
	}

	_button(action, text, extraClass = "text-kind-default") {
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.action = action;
		button.className = `rounded-sm px-2 py-1 font-semibold hover:bg-base-bg focus-visible:outline-2 focus-visible:outline-kind-default ${extraClass}`;
		button.textContent = text;
		return button;
	}

	_addHandlers() {
		this.panel.addEventListener("click", this._panelClick);
		document.addEventListener("pointerdown", this._documentPointerDown, {
			capture: true,
		});
		document.addEventListener("keydown", this._documentKeydown, {
			capture: true,
		});
	}

	_removeHandlers() {
		if (this.panel) {
			this.panel.removeEventListener("click", this._panelClick);
		}
		document.removeEventListener("pointerdown", this._documentPointerDown, {
			capture: true,
		});
		document.removeEventListener("keydown", this._documentKeydown, {
			capture: true,
		});
	}

	_startAutoUpdate() {
		this.cleanup = autoUpdate(this.link, this.panel, () => {
			computePosition(this.link, this.panel, {
				placement: "top-start",
				middleware: [offset(8), shift({ padding: 5 }), flip({ padding: 5 })],
			}).then(({ x, y, placement }) => {
				if (!this.panel) return;
				Object.assign(this.panel.style, {
					left: `${x}px`,
					top: `${y}px`,
				});
				this.panel.dataset.placement = placement;
			});
		});
	}

	_cleanupAutoUpdate() {
		if (this.cleanup) {
			this.cleanup();
			this.cleanup = null;
		}
	}

	_startObserver() {
		this.observer = new IntersectionObserver(this._handleIntersection, {
			threshold: 0,
		});
		this.observer.observe(this.link);
	}

	_cleanupObserver() {
		if (this.observer) {
			this.observer.disconnect();
			this.observer = null;
		}
	}

	_handleIntersection(entries) {
		if (entries.some((entry) => !entry.isIntersecting)) {
			this.close();
		}
	}

	_updatePreview(data) {
		if (!this.panel || !data) return;

		const title = this.panel.querySelector("[data-role='link-preview-title']");
		const url = this.panel.querySelector("[data-role='link-preview-url']");
		const description = this.panel.querySelector(
			"[data-role='link-preview-description']",
		);

		if (data.title) title.textContent = data.title;
		if (data.display_url || data.url) {
			url.textContent = data.display_url || displayUrl(data.url);
		}
		if (data.description) {
			description.textContent = data.description;
			description.classList.remove("hidden");
		}
	}

	async _loadPreview() {
		const requestId = ++this.requestId;
		const params = new URLSearchParams();
		params.set("url", this.href);

		const response = await request.get(ENDPOINTS.linkPreview, params);
		if (requestId !== this.requestId || !this.panel || !response?.ok) return;

		this._updatePreview(response);
	}

	_panelClick(event) {
		const button = event.target.closest("[data-action]");
		const action = button?.dataset.action;
		if (!ACTIONS.has(action)) return;

		event.preventDefault();
		event.stopPropagation();

		if (action === "open") {
			const link = this.link;
			this.close();
			if (link) navigateLink(link);
		} else if (action === "edit") {
			this._editLink();
		} else if (action === "remove") {
			this._removeLink();
		}
	}

	_editLink() {
		if (!this.range) return;

		const event = new CustomEvent(LINK_EDIT_EVENT, {
			bubbles: true,
			detail: { range: this.range },
		});
		this.editor.view.dom.dispatchEvent(event);
		this.close();
	}

	_removeLink() {
		if (!this.range) return;

		if (this.isMention) {
			const text = this.link?.textContent || "";
			this.editor
				.chain()
				.focus()
				.insertContentAt(this.range, text)
				.setTextSelection({
					from: this.range.from,
					to: this.range.from + text.length,
				})
				.run();
		} else {
			this.editor
				.chain()
				.focus()
				.setTextSelection(this.range)
				.unsetLink()
				.run();
		}
		this.close();
	}

	_documentPointerDown(event) {
		if (!this.panel) return;
		if (
			this.panel.contains(event.target) ||
			this.link?.contains(event.target)
		) {
			return;
		}
		this.close();
	}

	_documentKeydown(event) {
		if (event.key === "Escape") {
			event.preventDefault();
			this.close();
		}
	}

	close() {
		this.requestId += 1;
		this._removeHandlers();
		this._cleanupAutoUpdate();
		this._cleanupObserver();
		this.panel?.remove();
		this.panel = null;
		this.link = null;
		this.range = null;
		this.href = null;
		this.isMention = false;
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_space_exits_link_at_document_end
 * @features editor
 * @dimensions link internal-link click-navigation popover paste readonly delimiter
 */
export const CustomLink = Link.extend({
	addStorage() {
		return {
			...(this.parent?.() ?? {}),
			popover: null,
		};
	},

	addAttributes() {
		const attributes = this.parent?.() ?? {};

		return {
			...attributes,
			href: {
				...attributes.href,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						class: element.getAttribute("class"),
					}).href,
			},
			target: {
				...attributes.target,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						target: element.getAttribute("target"),
					}).target,
			},
			rel: {
				...attributes.rel,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						rel: element.getAttribute("rel"),
					}).rel,
			},
			class: {
				...attributes.class,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						class: element.getAttribute("class"),
					}).class,
			},
		};
	},

	renderHTML({ HTMLAttributes }) {
		return this.parent?.({
			HTMLAttributes: normalizeLinkAttributes(HTMLAttributes),
		});
	},

	addCommands() {
		return {
			...(this.parent?.() ?? {}),
			setLink:
				(attributes) =>
				({ chain }) => {
					const normalized = normalizeLinkAttributes(attributes);
					if (!linkAttributesAllowed(this, normalized.href)) return false;

					return chain()
						.setMark(this.name, normalized)
						.setMeta("preventAutolink", true)
						.run();
				},
			toggleLink:
				(attributes) =>
				({ chain }) => {
					const normalized = attributes
						? normalizeLinkAttributes(attributes)
						: attributes;
					if (
						normalized?.href &&
						!linkAttributesAllowed(this, normalized.href)
					) {
						return false;
					}

					return chain()
						.toggleMark(this.name, normalized, { extendEmptyMarkRange: true })
						.setMeta("preventAutolink", true)
						.run();
				},
		};
	},

	addKeyboardShortcuts() {
		return {
			...(this.parent?.() ?? {}),
			Space: () => Mark.handleExit({ editor: this.editor, mark: this }),
		};
	},

	addProseMirrorPlugins() {
		return [
			normalizeLinkMarks(this.type),
			editableMentionClickGuard(this.editor),
			new Plugin({
				key: new PluginKey("customLinkClick"),
				props: {
					handleClick: (_view, pos, event) => {
						const link = linkFromEvent(this.editor, event);
						if (event.button !== 0 || !link) return false;
						const isMention = link.matches('[data-type="lagniappe-mention"]');
						if (event.defaultPrevented && !isMention) return false;

						event.preventDefault();
						if (!this.editor.isEditable) {
							return navigateLink(link);
						}

						const range = linkRangeFromClick(this.editor, pos, event, link);
						this.storage.popover ??= new LinkPopover(this.editor);
						return this.storage.popover.show(link, range);
					},
				},
			}),
			...(this.parent?.() ?? []),
		];
	},

	onDestroy() {
		this.storage.popover?.close();
		this.storage.popover = null;
	},
});
