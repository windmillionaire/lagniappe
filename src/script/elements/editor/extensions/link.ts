import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import {
	type Attribute,
	type Editor,
	getMarkRange,
	Mark,
	type Range,
} from "@tiptap/core";
import { isAllowedUri, Link, type LinkOptions } from "@tiptap/extension-link";
import type { MarkType } from "@tiptap/pm/model";
import { Plugin, PluginKey, type Transaction } from "@tiptap/pm/state";
import { ENDPOINTS } from "../../../shared/endpoints.ts";
import { request } from "../../../shared/request.ts";
import { normalizeLinkAttributes } from "./linkAttributes.ts";

const LINK_EDIT_EVENT = "editor-link-edit";
type LinkAction = "open" | "edit" | "remove";

interface LinkPreview {
	title?: string;
	display_url?: string;
	url?: string;
	description?: string;
}

interface LinkStorage {
	popover: LinkPopover | null;
}

declare global {
	interface HTMLElementEventMap {
		"editor-link-edit": CustomEvent<{ range: Range }>;
	}
}

const ACTIONS = new Set<string>(["open", "edit", "remove"]);

const equalLinkAttributes = (
	left: Record<string, unknown> = {},
	right: Record<string, unknown> = {},
) => {
	const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
	for (const key of keys) {
		if ((left[key] ?? null) !== (right[key] ?? null)) return false;
	}
	return true;
};

const linkAttributesAllowed = (
	extension: { options: LinkOptions },
	href: string,
) =>
	extension.options.isAllowedUri(href, {
		defaultValidate: (url) => !!isAllowedUri(url, extension.options.protocols),
		protocols: extension.options.protocols,
		defaultProtocol: extension.options.defaultProtocol,
	});

const normalizeLinkMarks = (type: MarkType) =>
	new Plugin({
		key: new PluginKey("normalizeLinkMarks"),
		appendTransaction: (transactions, _oldState, newState) => {
			if (!transactions.some((transaction) => transaction.docChanged)) {
				return null;
			}

			let tr: Transaction | null = null;
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

const linkFromEvent = (editor: Editor, event: MouseEvent) => {
	const target = event.target as Node | null;
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

const opensInCurrentTab = (href: string | null | undefined) =>
	Boolean(href) &&
	!String(href).startsWith("//") &&
	!/^[a-z][a-z0-9+.-]*:/i.test(String(href));

const displayUrl = (href: string | null | undefined) => {
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

const linkRangeFromDom = (editor: Editor, link: HTMLAnchorElement) => {
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

const rangeMatchesLink = (
	editor: Editor,
	range: Range,
	href: string | null | undefined,
) => {
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

const linkRangeFromPosition = (
	editor: Editor,
	pos: number,
	link: HTMLAnchorElement,
) => {
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

const linkRangeFromClick = (
	editor: Editor,
	pos: number,
	event: MouseEvent,
	link: HTMLAnchorElement,
) => {
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

const navigateLink = (link: HTMLAnchorElement) => {
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

const editableMentionClickGuard = (editor: Editor) =>
	new Plugin({
		key: new PluginKey("editableMentionClickGuard"),
		view: (view) => {
			const preventNavigation = (event: MouseEvent) => {
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

class LinkPopover {
	declare editor: Editor;
	declare requestId: number;
	declare panel: HTMLDivElement | null;
	declare link: HTMLAnchorElement | null;
	declare range: Range | null;
	declare cleanup: (() => void) | null;
	declare observer: IntersectionObserver | null;
	declare isMention: boolean;
	declare href: string | null;

	constructor(editor: Editor) {
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

	show(link: HTMLAnchorElement, range: Range | null) {
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

	_createPanel(title: string) {
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

	_button(action: LinkAction, text: string, extraClass = "text-kind-default") {
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.action = action;
		button.className = `rounded-sm px-2 py-1 font-semibold hover:bg-base-bg focus-visible:outline-2 focus-visible:outline-kind-default ${extraClass}`;
		button.textContent = text;
		return button;
	}

	_addHandlers() {
		this.panel?.addEventListener("click", this._panelClick);
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
		const { link, panel } = this;
		if (!link || !panel) return;
		this.cleanup = autoUpdate(link, panel, () => {
			computePosition(link, panel, {
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
		if (!this.link) return;
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

	_handleIntersection(entries: IntersectionObserverEntry[]) {
		if (entries.some((entry) => !entry.isIntersecting)) {
			this.close();
		}
	}

	_updatePreview(data: LinkPreview) {
		if (!this.panel || !data) return;

		const title = this.panel.querySelector("[data-role='link-preview-title']");
		const url = this.panel.querySelector("[data-role='link-preview-url']");
		const description = this.panel.querySelector(
			"[data-role='link-preview-description']",
		);

		if (title && data.title) title.textContent = data.title;
		if (url && (data.display_url || data.url)) {
			url.textContent = data.display_url || displayUrl(data.url);
		}
		if (description && data.description) {
			description.textContent = data.description;
			description.classList.remove("hidden");
		}
	}

	async _loadPreview() {
		if (!this.href) return;
		const requestId = ++this.requestId;
		const params = new URLSearchParams();
		params.set("url", this.href);

		const response = await request.get<LinkPreview>(
			ENDPOINTS.linkPreview,
			params,
		);
		if (requestId !== this.requestId || !this.panel || !response?.ok) return;

		this._updatePreview(response);
	}

	_panelClick(event: MouseEvent) {
		const button = (event.target as Element | null)?.closest<HTMLElement>(
			"[data-action]",
		);
		const action = button?.dataset.action;
		if (!action || !ACTIONS.has(action)) return;

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

	_documentPointerDown(event: PointerEvent) {
		if (!this.panel) return;
		if (
			this.panel.contains(event.target as Node | null) ||
			this.link?.contains(event.target as Node | null)
		) {
			return;
		}
		this.close();
	}

	_documentKeydown(event: KeyboardEvent) {
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

export const CustomLink: Mark<LinkOptions, LinkStorage> = Link.extend<
	LinkOptions,
	LinkStorage
>({
	addStorage() {
		return {
			...(this.parent?.() ?? {}),
			popover: null,
		};
	},

	addAttributes() {
		const attributes: Record<string, Attribute> = this.parent?.() ?? {};

		return {
			...attributes,
			href: {
				...attributes?.href,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						class: element.getAttribute("class"),
					}).href,
			},
			target: {
				...attributes?.target,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						target: element.getAttribute("target"),
					}).target,
			},
			rel: {
				...attributes?.rel,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						rel: element.getAttribute("rel"),
					}).rel,
			},
			class: {
				...attributes?.class,
				parseHTML: (element) =>
					normalizeLinkAttributes({
						href: element.getAttribute("href"),
						class: element.getAttribute("class"),
					}).class,
			},
		};
	},

	renderHTML({ mark, HTMLAttributes }) {
		if (!this.parent)
			throw new Error("Link rendering requires the parent extension");
		return this.parent({
			mark,
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
			Space: () => Mark.handleExit({ editor: this.editor, mark: CustomLink }),
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
