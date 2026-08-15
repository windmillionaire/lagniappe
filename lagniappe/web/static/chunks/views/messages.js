/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from '../styles.js?v=b13679a7';
import { ensureMessageComposer } from '../messageComposer.js?v=b13679a7';
import { r as request, E as ENDPOINTS } from '../foundation.js?v=b13679a7';
import '../connectivity.js?v=b13679a7';
import { c as createIcon } from '../icons.js?v=b13679a7';
import { C as Core } from '../core-foundation.js?v=b13679a7';
import '../modal.js?v=b13679a7';
import '../facets.js?v=b13679a7';
import '../combobox.js?v=b13679a7';
import '../primitives.js?v=b13679a7';
import '../results.js?v=b13679a7';
import '../formatting.js?v=b13679a7';
import '../submitter.js?v=b13679a7';

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_messages_view_refreshes_read_races_and_uses_delete_modal
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_messages_page_uses_mobile_peer_selector_with_inline_reply
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_inbound_message_allows_reply_without_compose_permission
 * @pairs messaging:read-race messaging:clear-confirmation messaging:inline-reply
 * @pairs messaging:responsive-peer-selector messaging:reply-permission
 */
class Messages extends Core {
	async init() {
		await super.init();
		this.list = this.elt.querySelector("[data-role='conversation-list']");
		this.selector = this.elt.querySelector(
			"[data-role='conversation-selector']",
		);
		this.history = this.elt.querySelector("[data-role='message-history']");
		this.header = this.elt.querySelector("[data-role='message-header']");
		this.loadConversationsButton = this.elt.querySelector(
			"[data-action='load-conversations']",
		);
		this.loadMessagesButton = this.elt.querySelector(
			"[data-action='load-messages']",
		);
		this.replyForm = this.elt.querySelector("[data-role='message-reply']");
		this.replyTextarea = this.replyForm.querySelector("textarea[name='body']");
		this.replyError = this.replyForm.querySelector(
			"[data-role='message-reply-error']",
		);
		this.replySubmit = this.replyForm.querySelector("button[type='submit']");
		this.replySpinner = this.replySubmit.querySelector("[data-role='icon']");
		this.current = null;
		this.conversationCursor = null;
		this.messageCursor = null;
		this.conversations = new Map();

		const composeButton = this.elt.querySelector(
			"[data-action='compose-message']",
		);
		if (composeButton) {
			this.composer = ensureMessageComposer(this, {
				onSent: async (response) => {
					await this.loadConversations();
					await this.openConversation(response.conversation.id);
				},
			});
			composeButton.addEventListener("click", () => this.composer.open());
		}
		this.list.addEventListener("click", (event) => {
			const button = event.target.closest("[data-conversation]");
			if (button) void this.openConversation(button.dataset.conversation);
		});
		this.selector.addEventListener("change", () => {
			if (this.selector.value) void this.openConversation(this.selector.value);
		});
		this.history.addEventListener("click", (event) => {
			const button = event.target.closest("[data-action='delete-message']");
			if (button) void this.deleteMessage(button.dataset.message);
		});
		this.loadConversationsButton.addEventListener("click", () =>
			this.loadConversations({ append: true }),
		);
		this.loadMessagesButton.addEventListener("click", () =>
			this.loadHistory({ prepend: true }),
		);
		this.replyForm.addEventListener(
			"submit",
			(event) => void this.sendReply(event),
		);
		await this.loadConversations();
		const initial = this.elt.dataset.initialConversation;
		const preferred =
			initial ||
			Array.from(this.conversations.values()).find(
				(conversation) => conversation.unread,
			)?.id ||
			this.conversations.values().next().value?.id;
		if (preferred) await this.openConversation(preferred);
		return this;
	}

	/** @testable infrastructure */
	async loadConversations({ append = false } = {}) {
		const params =
			append && this.conversationCursor
				? { cursor: this.conversationCursor }
				: null;
		const response = await request.get(
			ENDPOINTS.messages.conversations,
			params,
		);
		if (!response?.ok) return;
		if (!append) this.conversations.clear();
		for (const conversation of response.conversations || []) {
			this.conversations.set(conversation.id, conversation);
		}
		this.conversationCursor = response.cursor || null;
		this.renderConversations();
	}

	/** @testable infrastructure */
	renderConversations() {
		const conversations = Array.from(this.conversations.values());
		this.list.replaceChildren(
			...conversations.map((conversation) => {
				const row = document.createElement("div");
				row.dataset.conversationRow = conversation.id;
				row.className = `${
					STYLES.list.itemHeader
				} group bg-white hover:bg-user-bg data-[active=true]:bg-user-bg/50`;
				if (conversation.id === this.current?.id) row.dataset.active = "true";

				const button = document.createElement("button");
				button.type = "button";
				button.dataset.conversation = conversation.id;
				button.className =
					"flex min-w-0 grow items-center justify-between gap-2 text-left focus-visible:outline-none focus-visible:underline";
				const name = document.createElement("span");
				name.className = "font-medium";
				name.textContent = conversation.peer.name;
				button.appendChild(name);
				if (conversation.unread) {
					const unread = document.createElement("span");
					unread.className =
						"rounded-full bg-user-default px-2 py-0.5 text-xs font-bold text-white";
					unread.textContent = String(conversation.unread);
					button.appendChild(unread);
				}

				const clear = document.createElement("button");
				clear.type = "button";
				clear.className = STYLES.toggle.container;
				clear.dataset.controls = "delete";
				clear.dataset.kind = "delete";
				clear.dataset.active = "false";
				clear.dataset.deleteKey = conversation.id;
				clear.dataset.deleteModalRoute = ENDPOINTS.messages.clearModal(
					conversation.id,
				);
				clear.setAttribute("lp-control", "delete");
				clear.setAttribute("lp-delete", "");
				clear.setAttribute(
					"aria-label",
					`Clear conversation with ${conversation.peer.name}`,
				);
				clear.title = `Clear conversation with ${conversation.peer.name}`;
				clear.append(
					createIcon("trash.active", STYLES.toggle.icon.active),
					createIcon("trash.inactive", STYLES.toggle.icon.inactive),
				);
				row.append(button, clear);
				return row;
			}),
		);
		this.selector.replaceChildren(
			...[
				Object.assign(document.createElement("option"), {
					value: "",
					textContent: "Choose a conversation",
				}),
				...conversations.map((conversation) =>
					Object.assign(document.createElement("option"), {
						value: conversation.id,
						textContent: `${conversation.peer.name}${
							conversation.unread ? ` (${conversation.unread} unread)` : ""
						}`,
					}),
				),
			],
		);
		this.selector.value = this.current?.id || "";
		this.loadConversationsButton.classList.toggle(
			"hidden",
			!this.conversationCursor,
		);
	}

	/** @testable infrastructure */
	async openConversation(key) {
		const response = await request.get(ENDPOINTS.messages.history(key));
		if (!response?.ok) return;
		this.current = response.conversation;
		this.replyOperationId = this.operationId?.() || crypto.randomUUID();
		this.conversations.set(this.current.id, this.current);
		this.messageCursor = response.cursor || null;
		this.renderHeader();
		this.renderMessages(response.messages || []);
		this.renderConversations();
		if (this.current.unread) await this.markRead();
	}

	/** @testable infrastructure */
	renderHeader() {
		const title = document.createElement("span");
		title.className = "font-semibold";
		title.textContent = this.current.peer.deleted
			? `${this.current.peer.name} (deleted)`
			: this.current.peer.name;
		this.header.replaceChildren(title);
		this.renderReply();
	}

	/** @testable infrastructure */
	renderReply() {
		const available = Boolean(this.current?.peer?.replyable);
		this.replyForm.classList.toggle("hidden", !available);
		this.replyTextarea.disabled = !available;
		this.replySubmit.disabled = !available;
		this.replySpinner.dataset.visible = "false";
		this.replyError.classList.add("hidden");
		this.replyError.textContent = "";
	}

	/** @testable infrastructure */
	async sendReply(event) {
		event.preventDefault();
		if (!this.current?.peer?.replyable || this.replySubmit.disabled) return;
		const conversation = this.current.id;
		const data = new FormData();
		data.set("recipient", this.current.peer.id);
		data.set("conversation", conversation);
		data.set("body", this.replyTextarea.value);
		data.set(
			"operation_id",
			this.replyOperationId || this.operationId?.() || crypto.randomUUID(),
		);
		this.replyError.classList.add("hidden");
		this.replySubmit.disabled = true;
		this.replySpinner.dataset.visible = "true";
		let response;
		try {
			response = await request.post(ENDPOINTS.messages.send, data);
		} finally {
			this.replySubmit.disabled = false;
			this.replySpinner.dataset.visible = "false";
		}
		if (!response?.ok) {
			this.replyError.textContent =
				response?.error || "Reply could not be sent.";
			this.replyError.classList.remove("hidden");
			return;
		}
		this.replyTextarea.value = "";
		await this.loadConversations();
		await this.openConversation(response.conversation.id);
		this.replyTextarea.focus();
	}

	/** @testable infrastructure */
	renderMessages(messages, { prepend = false } = {}) {
		const nodes = messages.map((message) => {
			const article = document.createElement("article");
			article.dataset.message = message.id;
			article.className = `group max-w-[85%] rounded-lg p-3 ${
				message.mine ? "self-end bg-user-bg" : "self-start bg-base-bg"
			}`;
			const body = document.createElement("p");
			body.className = "whitespace-pre-wrap break-words";
			body.textContent = message.body;
			const footer = document.createElement("div");
			footer.className =
				"mt-1 flex items-center justify-between gap-3 text-xs text-base-medium";
			const time = document.createElement("time");
			time.dateTime = message.created || "";
			time.textContent = message.created
				? new Date(message.created).toLocaleString()
				: "";
			const remove = document.createElement("button");
			remove.type = "button";
			remove.dataset.action = "delete-message";
			remove.dataset.message = message.id;
			remove.className =
				"text-delete-default opacity-0 group-hover:opacity-100";
			remove.textContent = "Delete";
			footer.append(time, remove);
			article.append(body, footer);
			return article;
		});
		if (prepend) this.history.prepend(...nodes);
		else this.history.replaceChildren(...nodes);
		this.loadMessagesButton.classList.toggle("hidden", !this.messageCursor);
		if (!prepend) this.history.scrollTop = this.history.scrollHeight;
	}

	/** @testable infrastructure */
	async loadHistory({ prepend = false } = {}) {
		if (!this.current) return;
		const params =
			prepend && this.messageCursor ? { cursor: this.messageCursor } : null;
		const response = await request.get(
			ENDPOINTS.messages.history(this.current.id),
			params,
		);
		if (!response?.ok) return;
		this.messageCursor = response.cursor || null;
		this.renderMessages(response.messages || [], { prepend });
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/messages.mjs::Messages
	 * @reason stale revision refresh is exercised through the view contract
	 */
	async markRead() {
		const data = new FormData();
		data.set("revision", String(this.current.revision));
		const response = await request.post(
			ENDPOINTS.messages.read(this.current.id),
			data,
		);
		if (!response?.ok) {
			if (response?.conversation) await this.openConversation(this.current.id);
			return;
		}
		this.current = response.conversation;
		this.conversations.set(this.current.id, this.current);
		this.renderConversations();
	}

	/** @testable infrastructure */
	async deleteMessage(key) {
		const response = await request.delete(ENDPOINTS.messages.remove(key));
		if (!response?.ok) return;
		this.history.querySelector(`[data-message="${CSS.escape(key)}"]`)?.remove();
	}

	reconcileChange(change = {}) {
		if (change.type !== "delete" || !this.conversations.has(change.key)) {
			return super.reconcileChange(change);
		}
		this.conversations.delete(change.key);
		if (this.current?.id === change.key) {
			this.current = null;
			this.messageCursor = null;
			this.history.replaceChildren();
			this.header.textContent = "Choose a conversation";
			this.renderReply();
		}
		this.renderConversations();
		return Promise.resolve();
	}
}

export { Messages as default };
