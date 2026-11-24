import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import {
	type Editor,
	type JSONContent,
	mergeAttributes,
	Node,
	type Range,
} from "@tiptap/core";
import { STYLES } from "../../../generated/styles.mjs";
import { captureError } from "../../../shared/errors.ts";
import { QueryLifecycle } from "../../../shared/queryLifecycle.ts";
import { request } from "../../../shared/request.ts";
import { debounce, generateElementId } from "../../../shared/utilities.ts";
import type { SyncMention } from "../../../types/sync.d.ts";

export const LagniappeMention = Node.create({
	name: "lagniappeMention",
	group: "inline",
	inline: true,
	atom: true,
	selectable: false,

	addAttributes() {
		return {
			occurrenceId: {
				default: null,
				parseHTML: (element) => element.getAttribute("data-mention-id"),
			},
			recipient: {
				default: null,
				parseHTML: (element) => element.getAttribute("data-recipient"),
			},
			displayName: {
				default: null,
				parseHTML: (element) => element.getAttribute("data-display-name"),
			},
			profilePage: {
				default: null,
				parseHTML: (element) => element.getAttribute("data-profile-page"),
			},
		};
	},

	parseHTML() {
		return [
			{ tag: 'a[data-type="lagniappe-mention"]', priority: 100 },
			{ tag: 'span[data-type="lagniappe-mention"]' },
		];
	},

	renderHTML({ HTMLAttributes }) {
		const attributes = { ...HTMLAttributes };
		delete attributes.occurrenceId;
		delete attributes.recipient;
		delete attributes.displayName;
		delete attributes.profilePage;
		const profilePage = HTMLAttributes.profilePage;
		return [
			profilePage ? "a" : "span",
			mergeAttributes(attributes, {
				"data-type": "lagniappe-mention",
				"data-mention-id": HTMLAttributes.occurrenceId,
				"data-recipient": HTMLAttributes.recipient,
				"data-display-name": HTMLAttributes.displayName,
				"data-profile-page": profilePage,
				href: profilePage
					? `/pages/${encodeURIComponent(profilePage)}`
					: undefined,
				class:
					"rounded bg-user-bg px-1 font-medium text-user-dark hover:underline",
			}),
			`@${HTMLAttributes.displayName || ""}`,
		];
	},
});

interface MentionQuery extends Range {
	query: string;
}

interface MentionResults {
	results: string;
}

interface MentionSuggestionOptions {
	documentKey: string;
	onInsert?: ((mention: SyncMention) => void) | null;
}

const currentQuery = (editor: Editor): MentionQuery | null => {
	const { selection } = editor.state;
	if (!selection.empty) return null;
	const { $from } = selection;
	const before = $from.parent.textBetween(0, $from.parentOffset, "\n", "\n");
	const match = before.match(/@([^@\n]{1,50})$/u);
	if (!match?.[1].trim()) return null;
	return {
		query: match[1].trim(),
		from: selection.from - match[0].length,
		to: selection.from,
	};
};

const queryKey = (active: MentionQuery | null) =>
	active ? `${active.from}:${active.to}:${active.query}` : null;

export class MentionSuggestions {
	declare editor: Editor;
	declare documentKey: string;
	declare onInsert: MentionSuggestionOptions["onInsert"];
	declare _destroyed: boolean;
	declare focused: number;
	declare queries: QueryLifecycle;
	declare _debouncedSearch: ReturnType<typeof debounce<MentionSuggestions, []>>;
	declare options: HTMLElement[];
	declare rows: HTMLElement[];
	declare active: MentionQuery | null;
	declare dismissedFrom: number | null;
	declare popup: HTMLDivElement | null;
	declare positionCleanup?: (() => void) | null;

	constructor(
		editor: Editor,
		{ documentKey, onInsert = null }: MentionSuggestionOptions,
	) {
		this._destroyed = false;
		this.editor = editor;
		this.documentKey = documentKey;
		this.onInsert = onInsert;
		this.options = [];
		this.focused = 0;
		this.dismissedFrom = null;
		this.queries = new QueryLifecycle();
		this._refresh = this._refresh.bind(this);
		this._keydown = this._keydown.bind(this);
		this._click = this._click.bind(this);
		this._debouncedSearch = debounce(() => {
			this.search().catch((error) => captureError(error, this.popup));
		}, 120);
	}

	init() {
		if (this._destroyed) return this;
		this.popup = document.createElement("div");
		this.popup.id = generateElementId("mention-suggestions");
		this.popup.dataset.role = "mention-suggestions";
		this.popup.dataset.kind = "user";
		this.popup.dataset.visible = "false";
		this.popup.setAttribute("role", "listbox");
		this.popup.setAttribute("aria-label", "Mention a user");
		this.popup.className = `${STYLES.dropdown.panel} w-72`;
		this.popup.style.position = "fixed";
		document.body.appendChild(this.popup);
		this.editor.view.dom.setAttribute("aria-controls", this.popup.id);
		this.editor.view.dom.setAttribute("aria-expanded", "false");
		this.editor.view.dom.setAttribute("aria-haspopup", "listbox");
		this.editor.on("update", this._refresh);
		this.editor.on("selectionUpdate", this._refresh);
		this.editor.view.dom.addEventListener("keydown", this._keydown, true);
		this.popup.addEventListener("click", this._click);
		return this;
	}

	_refresh() {
		if (this._destroyed) return;
		this.hide();
		this._debouncedSearch();
	}

	async search() {
		if (this._destroyed) return false;
		const active = currentQuery(this.editor);
		if (!active) {
			this.dismissedFrom = null;
			return this.hide();
		}
		if (active.from === this.dismissedFrom) return this.hide();
		this.dismissedFrom = null;
		const params = new URLSearchParams({
			q: active.query,
			permission: "mention",
			document: this.documentKey,
		});
		const key = queryKey(active);
		return this.queries.run(
			key,
			(token) =>
				request.get<MentionResults>("/l/search-index/user", params, {
					signal: token.signal,
				}),
			(response) => {
				if (!response?.ok) return this.hide();
				const template = document.createElement("template");
				template.innerHTML = response.results || "";
				this.rows = Array.from(
					template.content.querySelectorAll<HTMLElement>("[role='option']"),
				);
				this.options = this.rows.filter((option) => option.dataset.id);
				if (!this.rows.length) return this.hide();
				this.active = active;
				this.focused = 0;
				this.render();
			},
			{ getCurrentKey: () => queryKey(currentQuery(this.editor)) },
		);
	}

	render() {
		const popup = this.popup;
		if (this._destroyed || !popup?.isConnected) return;
		popup.replaceChildren(
			...this.rows.map((option, rowIndex) => {
				const rendered = option.cloneNode(true) as HTMLElement;
				const index = this.options.indexOf(option);
				rendered.id = `${popup.id}-option-${rowIndex}`;
				if (index >= 0) {
					rendered.dataset.index = String(index);
					rendered.classList.add("w-full", "text-left", "hover:bg-user-bg");
					rendered.classList.toggle("bg-user-bg", index === this.focused);
					rendered.setAttribute(
						"aria-selected",
						index === this.focused ? "true" : "false",
					);
				}
				return rendered;
			}),
		);
		popup.classList.remove("hidden");
		popup.dataset.visible = "true";
		this.editor.view.dom.setAttribute("aria-expanded", "true");
		const focused = popup.querySelector(`[data-index='${this.focused}']`);
		if (focused) {
			this.editor.view.dom.setAttribute("aria-activedescendant", focused.id);
		} else {
			this.editor.view.dom.removeAttribute("aria-activedescendant");
		}
		this._startPositioning();
	}

	_startPositioning() {
		const { active, popup } = this;
		if (this._destroyed || !active || !popup?.isConnected) return;
		this._cleanupPositioning();
		const contextElement = this.editor.view.dom;
		const reference = {
			contextElement,
			getBoundingClientRect: () => {
				const coordinates = this.editor.view.coordsAtPos(active.to);
				return {
					x: coordinates.left,
					y: coordinates.top,
					top: coordinates.top,
					left: coordinates.left,
					right: coordinates.left,
					bottom: coordinates.bottom,
					width: 0,
					height: coordinates.bottom - coordinates.top,
				};
			},
		};
		this.positionCleanup = autoUpdate(reference, popup, () => {
			computePosition(reference, popup, {
				placement: "bottom-start",
				strategy: "fixed",
				middleware: [offset(4), shift({ padding: 5 }), flip({ padding: 5 })],
			})
				.then(({ x, y }) => {
					if (
						this._destroyed ||
						!this.popup?.isConnected ||
						this.popup.dataset.visible !== "true"
					) {
						return;
					}
					Object.assign(this.popup.style, {
						left: `${x}px`,
						top: `${y}px`,
					});
				})
				.catch((error) => captureError(error, this.popup));
		});
	}

	_cleanupPositioning() {
		this.positionCleanup?.();
		this.positionCleanup = null;
	}

	_keydown(event: KeyboardEvent) {
		if (this.popup?.classList.contains("hidden")) return;
		if (event.key === "Escape") {
			event.preventDefault();
			this.dismissedFrom = this.active?.from ?? null;
			this.hide();
		} else if (
			this.options.length &&
			(event.key === "ArrowDown" || event.key === "ArrowUp")
		) {
			event.preventDefault();
			const direction = event.key === "ArrowDown" ? 1 : -1;
			this.focused =
				(this.focused + direction + this.options.length) % this.options.length;
			this.render();
		} else if (this.options.length && event.key === "Enter") {
			event.preventDefault();
			this.insert(this.options[this.focused]);
		}
	}

	_click(event: MouseEvent) {
		const button = (event.target as Element | null)?.closest<HTMLElement>(
			"[role='option'][data-index]",
		);
		if (!button) return;
		this.insert(this.options[Number(button.dataset.index)]);
	}

	insert(option: HTMLElement | undefined) {
		if (!option || !this.active) return;
		const details: { recipient_key?: string } = JSON.parse(
			option.dataset.details || "{}",
		);
		const displayName = option.dataset.name;
		if (!details.recipient_key || displayName === undefined) return;
		const occurrenceId =
			globalThis.crypto?.randomUUID?.() ||
			`mention-${Date.now()}-${Math.random().toString(16).slice(2)}`;
		this.editor
			.chain()
			.focus()
			.deleteRange({ from: this.active.from, to: this.active.to })
			.insertContent([
				{
					type: "lagniappeMention",
					attrs: {
						occurrenceId,
						recipient: details.recipient_key,
						displayName,
						profilePage: option.dataset.id,
					},
				},
				{ type: "text", text: " " },
			])
			.run();
		this.onInsert?.({
			occurrence_id: occurrenceId,
			recipient: details.recipient_key,
			display_name: displayName,
		});
		this.hide();
	}

	hide() {
		this.queries.invalidate();
		this._cleanupPositioning();
		this.popup?.classList.add("hidden");
		if (this.popup) this.popup.dataset.visible = "false";
		this.editor.view.dom.setAttribute("aria-expanded", "false");
		this.editor.view.dom.removeAttribute("aria-activedescendant");
		this.options = [];
		this.rows = [];
		this.active = null;
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this._debouncedSearch.cancel();
		this.queries.destroy();
		this._cleanupPositioning();
		this.editor.off("update", this._refresh);
		this.editor.off("selectionUpdate", this._refresh);
		this.editor.view.dom.removeEventListener("keydown", this._keydown, true);
		this.popup?.removeEventListener("click", this._click);
		this.popup?.remove();
		this.popup = null;
		this.editor.view.dom.removeAttribute("aria-controls");
		this.editor.view.dom.removeAttribute("aria-expanded");
		this.editor.view.dom.removeAttribute("aria-haspopup");
		this.editor.view.dom.removeAttribute("aria-activedescendant");
	}
}

export const collectMentions = (
	document: JSONContent | null | undefined,
): SyncMention[] => {
	const mentions: SyncMention[] = [];
	const visit = (node: JSONContent | null | undefined) => {
		if (node?.type === "lagniappeMention" && node.attrs) {
			mentions.push({
				occurrence_id: node.attrs.occurrenceId,
				recipient: node.attrs.recipient,
				display_name: node.attrs.displayName,
			});
		}
		for (const child of node?.content || []) visit(child);
	};
	visit(document);
	return mentions.filter(
		(item) => item.occurrence_id && item.recipient && item.display_name,
	);
};
