import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import { mergeAttributes, Node } from "@tiptap/core";
import { STYLES } from "styles";
import { generateElementId, request } from "../../../shared";

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_mention_node_collection_insertion_and_keyboard_contract
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_document_mentions_use_anchored_menu_and_profile_links
 * @pairs mentions:node-attributes mentions:profile-link
 */
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

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_mention_node_collection_insertion_and_keyboard_contract
 * @pair mentions:query-detection
 */
const currentQuery = (editor) => {
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

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_mention_node_collection_insertion_and_keyboard_contract
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_document_mentions_use_anchored_menu_and_profile_links
 * @pairs mentions:pending-occurrence mentions:keyboard mentions:mouse mentions:node-attributes
 * @pairs mentions:floating-menu mentions:empty-results mentions:profile-link
 */
export class MentionSuggestions {
	constructor(editor, { documentKey, onInsert = null }) {
		this.editor = editor;
		this.documentKey = documentKey;
		this.onInsert = onInsert;
		this.options = [];
		this.focused = 0;
		this.sequence = 0;
		this._refresh = this._refresh.bind(this);
		this._keydown = this._keydown.bind(this);
		this._click = this._click.bind(this);
	}

	init() {
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

	/** @testable infrastructure */
	_refresh() {
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.search(), 120);
	}

	/** @testable infrastructure */
	async search() {
		const active = currentQuery(this.editor);
		if (!active) return this.hide();
		this.active = active;
		const sequence = ++this.sequence;
		const params = new URLSearchParams({
			q: active.query,
			permission: "mention",
			document: this.documentKey,
		});
		const response = await request.get("/l/search-index/user", params);
		if (sequence !== this.sequence || !response?.ok) return;
		const template = document.createElement("template");
		template.innerHTML = response.results || "";
		this.rows = Array.from(
			template.content.querySelectorAll("[role='option']"),
		);
		this.options = this.rows.filter((option) => option.dataset.id);
		if (!this.rows.length) return this.hide();
		this.focused = 0;
		this.render();
	}

	/** @testable infrastructure */
	render() {
		this.popup.replaceChildren(
			...this.rows.map((option, rowIndex) => {
				const rendered = option.cloneNode(true);
				const index = this.options.indexOf(option);
				rendered.id = `${this.popup.id}-option-${rowIndex}`;
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
		this.popup.classList.remove("hidden");
		this.popup.dataset.visible = "true";
		this.editor.view.dom.setAttribute("aria-expanded", "true");
		const focused = this.popup.querySelector(`[data-index='${this.focused}']`);
		if (focused) {
			this.editor.view.dom.setAttribute("aria-activedescendant", focused.id);
		} else {
			this.editor.view.dom.removeAttribute("aria-activedescendant");
		}
		this._startPositioning();
	}

	/** @testable infrastructure */
	_startPositioning() {
		this._cleanupPositioning();
		const contextElement = this.editor.view.dom;
		const reference = {
			contextElement,
			getBoundingClientRect: () => {
				const coordinates = this.editor.view.coordsAtPos(this.active.to);
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
		this.positionCleanup = autoUpdate(reference, this.popup, () => {
			computePosition(reference, this.popup, {
				placement: "bottom-start",
				strategy: "fixed",
				middleware: [offset(4), shift({ padding: 5 }), flip({ padding: 5 })],
			}).then(({ x, y }) => {
				if (this.popup?.dataset.visible !== "true") return;
				Object.assign(this.popup.style, {
					left: `${x}px`,
					top: `${y}px`,
				});
			});
		});
	}

	/** @testable infrastructure */
	_cleanupPositioning() {
		this.positionCleanup?.();
		this.positionCleanup = null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/editor/extensions/mention.mjs::MentionSuggestions
	 * @reason keyboard behavior is exercised through the suggestion controller contract
	 */
	_keydown(event) {
		if (this.popup.classList.contains("hidden")) return;
		if (event.key === "Escape") {
			event.preventDefault();
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

	/**
	 * @testable false
	 * @covered-by src/script/elements/editor/extensions/mention.mjs::MentionSuggestions
	 * @reason mouse selection is exercised through the suggestion controller contract
	 */
	_click(event) {
		const button = event.target.closest("[role='option'][data-index]");
		if (!button) return;
		this.insert(this.options[Number(button.dataset.index)]);
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/editor/extensions/mention.mjs::MentionSuggestions
	 * @reason node insertion and pending payloads are exercised through the controller contract
	 */
	insert(option) {
		if (!option || !this.active) return;
		const details = JSON.parse(option.dataset.details || "{}");
		if (!details.recipient_key) return;
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
						displayName: option.dataset.name,
						profilePage: option.dataset.id,
					},
				},
				{ type: "text", text: " " },
			])
			.run();
		this.onInsert?.({
			occurrence_id: occurrenceId,
			recipient: details.recipient_key,
			display_name: option.dataset.name,
		});
		this.hide();
	}

	/** @testable infrastructure */
	hide() {
		this.sequence += 1;
		this._cleanupPositioning();
		this.popup.classList.add("hidden");
		this.popup.dataset.visible = "false";
		this.editor.view.dom.setAttribute("aria-expanded", "false");
		this.editor.view.dom.removeAttribute("aria-activedescendant");
		this.options = [];
		this.rows = [];
		this.active = null;
	}

	destroy() {
		clearTimeout(this.timer);
		this._cleanupPositioning();
		this.editor.off("update", this._refresh);
		this.editor.off("selectionUpdate", this._refresh);
		this.editor.view.dom.removeEventListener("keydown", this._keydown, true);
		this.popup.removeEventListener("click", this._click);
		this.popup.remove();
		this.editor.view.dom.removeAttribute("aria-controls");
		this.editor.view.dom.removeAttribute("aria-expanded");
		this.editor.view.dom.removeAttribute("aria-haspopup");
		this.editor.view.dom.removeAttribute("aria-activedescendant");
	}
}

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_mention_node_collection_insertion_and_keyboard_contract
 * @pair mentions:pending-occurrence
 */
export const collectMentions = (document) => {
	const mentions = [];
	/**
	 * @testable false
	 * @covered-by src/script/elements/editor/extensions/mention.mjs::collectMentions
	 * @reason recursive traversal is exercised through the public collector
	 */
	const visit = (node) => {
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
