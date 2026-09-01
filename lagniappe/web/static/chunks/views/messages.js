/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from '../styles.js?v=b506293e';
import { ensureMessageComposer } from '../messageComposer.js?v=b506293e';
import { r as request, E as ENDPOINTS } from '../foundation.js?v=b506293e';
import '../connectivity.js?v=b506293e';
import { c as createIcon } from '../icons.js?v=b506293e';
import { C as Core } from '../core-foundation.js?v=b506293e';
import '../modal.js?v=b506293e';
import '../facets.js?v=b506293e';
import '../remote.js?v=b506293e';
import '../queryLifecycle.js?v=b506293e';
import '../combobox.js?v=b506293e';
import '../primitives.js?v=b506293e';
import '../results.js?v=b506293e';
import '../storage.js?v=b506293e';
import '../formatting.js?v=b506293e';
import '../submitter.js?v=b506293e';
import '../upstreamUnavailable.js?v=b506293e';

const MESSAGE_POLL_SUBSCRIPTION = "view:channel:messages";

/**
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_messages_view_refreshes_read_races_and_uses_delete_modal
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_messages_page_uses_mobile_peer_selector_with_inline_reply
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_inbound_message_allows_reply_without_compose_permission
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
 * @matrix messaging : active-polling clear-confirmation inline-reply list-race polling-revision preserve-selection read-race reply-permission responsive-peer-selector selection-race unread-peer
 */
class Messages extends Core {
	_initPollingSubscription() {
		if (!this.PollingCoordinator) return;
		this.PollingCoordinator.subscribe(
			{
				id: MESSAGE_POLL_SUBSCRIPTION,
				type: "channel",
				channel: "messages",
				revision: null,
			},
			{
				mode: "periodic",
				initial: "scheduled",
				onResult: async (result) => {
					if (result.status !== "changed") return;
					await this.refresh();
				},
			},
		);
	}

	/** @testable infrastructure */
	_boostMessagePolling() {
		this.PollingCoordinator?.boost?.(MESSAGE_POLL_SUBSCRIPTION, {
			durationMs: 60_000,
			pollAfterMs: 2_000,
		});
	}

	async init() {
		await super.init();
		this.list = this.elt.querySelector("[data-role='conversation-list']");
		this.selector = this.elt.querySelector(
			"[data-role='conversation-selector']",
		);
		this.selectorLabel = this.selector.querySelector(
			"[data-role='conversation-selector-label']",
		);
		this.mobileClearConversation = this.elt.querySelector(
			"[data-role='mobile-clear-conversation']",
		);
		this.mobileClearConversationContainer = this.elt.querySelector(
			"[data-role='mobile-clear-conversation-container']",
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
		this.conversationSelectionRevision = 0;
		this.conversationListRevision = 0;
		this.conversationCursor = null;
		this.messageCursor = null;
		this.conversations = new Map();
		this.conversationStorageKey = `messages-${this.elt.dataset.currentUser}-active`;
		const initialConversation = this.elt.dataset.initialConversation;
		const storedConversation = localStorage.getItem(
			this.conversationStorageKey,
		);
		this.preferredConversation =
			initialConversation || storedConversation || null;

		const composeButton = this.elt.querySelector(
			"[data-action='compose-message']",
		);
		if (composeButton) {
			this.composer = ensureMessageComposer(this, {
				onSent: (response) => this.handleMessageSent(response),
			});
			composeButton.addEventListener("click", () => this.composer.open());
		}
		this.list.addEventListener("click", (event) => {
			const button = event.target.closest("[data-conversation]");
			if (button) {
				const selectionRevision = this._beginConversationSelection(
					button.dataset.conversation,
				);
				void this.openConversation(button.dataset.conversation, {
					selectionRevision,
				});
			}
		});
		this._conversationSelectorClick = (event) => {
			if (!this.mobile || this.conversationDropdown) return;
			event.preventDefault();
			event.stopPropagation();
			void this.runColdAction(
				this.selector,
				() => this._ensureConversationDropdown(),
				(dropdown) => dropdown?.showPanel?.(),
				this.selector,
			);
		};
		this.selector.addEventListener("click", this._conversationSelectorClick);
		this._messagesMobileResize = () => {
			if (this.mobile) {
				void this._ensureConversationDropdown();
			} else {
				this.conversationDropdown?.destroy?.();
				this.conversationDropdown = null;
			}
		};
		this.elt.addEventListener("mobile-resize", this._messagesMobileResize);
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
		const candidates = [
			initialConversation,
			storedConversation,
			Array.from(this.conversations.values()).find(
				(conversation) => conversation.unread,
			)?.id || this.conversations.values().next().value?.id,
		].filter((key, index, values) => key && values.indexOf(key) === index);
		this.preferredConversation = candidates[0] || null;
		this.renderConversationSelector();
		if (this.mobile && candidates.length) {
			await this._ensureConversationDropdown();
		}
		let opened = false;
		for (const candidate of candidates) {
			this.preferredConversation = candidate;
			this.renderConversationSelector();
			if (await this.openConversation(candidate)) {
				opened = true;
				break;
			}
			if (candidate === storedConversation) {
				localStorage.removeItem(this.conversationStorageKey);
			}
		}
		if (candidates.length && !opened) {
			this.rememberConversation(null);
			this.renderConversationSelector();
		}
		return this;
	}

	/** @testable infrastructure */
	async refresh() {
		if (this._messageRefresh) return this._messageRefresh;
		const pending = this._refreshMessages().finally(() => {
			if (this._messageRefresh === pending) this._messageRefresh = null;
		});
		this._messageRefresh = pending;
		return pending;
	}

	/** @testable infrastructure */
	async _refreshMessages() {
		const selectionRevision = this.conversationSelectionRevision;
		const active = this.preferredConversation || this.current?.id;
		await this.loadConversations();
		if (selectionRevision !== this.conversationSelectionRevision) return false;
		if (
			Array.from(this.conversations.values()).some(
				(conversation) => conversation.unread,
			)
		) {
			this._boostMessagePolling();
		}
		const candidate =
			(active && this.conversations.has(active) ? active : null) ||
			Array.from(this.conversations.values()).find(
				(conversation) => conversation.unread,
			)?.id ||
			this.conversations.values().next().value?.id ||
			null;
		if (candidate) {
			return this.openConversation(candidate, { selectionRevision });
		}

		this.current = null;
		this.messageCursor = null;
		this.history.replaceChildren();
		this.header.textContent = "Choose a conversation";
		this.renderReply();
		this.rememberConversation(null);
		this.renderConversationSelector();
		return false;
	}

	/** @testable infrastructure */
	_beginConversationSelection(key) {
		this.preferredConversation = key || null;
		return ++this.conversationSelectionRevision;
	}

	/** @testable infrastructure */
	async handleMessageSent(response) {
		const conversation = response.conversation.id;
		const active = this.current?.id || null;
		const selectionRevision = active
			? this.conversationSelectionRevision
			: this._beginConversationSelection(conversation);
		this._boostMessagePolling();
		await this.loadConversations();
		if (selectionRevision !== this.conversationSelectionRevision) return false;
		if (active && active !== conversation) return true;
		return this.openConversation(conversation, { selectionRevision });
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/messages.mjs::Messages
	 * @reason private responsive dropdown setup is exercised through the view contract
	 */
	async _ensureConversationDropdown() {
		if (this.conversationDropdown || this._conversationDropdownPromise) {
			return this.conversationDropdown || this._conversationDropdownPromise;
		}
		this._conversationDropdownPromise = import('../dropdown.js?v=b506293e')
			.then(({ Dropdown }) => {
				if (this._destroyed || !this.mobile) return null;
				this.conversationDropdown = new Dropdown(this.selector).init({
					items: [],
					matchReferenceWidth: true,
				});
				this.renderConversationSelector();
				return this.conversationDropdown;
			})
			.catch((error) => {
				this.reportStartupError(
					error,
					this.selector,
					"messages-conversation-dropdown",
				);
				return null;
			})
			.finally(() => {
				this._conversationDropdownPromise = null;
			});
		return this._conversationDropdownPromise;
	}

	/** @testable infrastructure */
	async loadConversations({ append = false } = {}) {
		const listRevision = ++this.conversationListRevision;
		const params =
			append && this.conversationCursor
				? { cursor: this.conversationCursor }
				: null;
		const response = await request.get(
			ENDPOINTS.messages.conversations,
			params,
		);
		if (!response?.ok) return;
		if (listRevision !== this.conversationListRevision) return;
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
					createIcon("trash.active", `${STYLES.toggle.icon.active} icon-lg`),
					createIcon(
						"trash.inactive",
						`${STYLES.toggle.icon.inactive} icon-lg`,
					),
				);
				row.append(button, clear);
				return row;
			}),
		);
		this.renderConversationSelector();
		this.loadConversationsButton.classList.toggle(
			"hidden",
			!this.conversationCursor,
		);
	}

	/** @testable infrastructure */
	renderConversationSelector() {
		const selected =
			this.current ||
			this.conversations.get(this.preferredConversation) ||
			null;
		const selectedName = selected?.peer?.name || "";
		this.selectorLabel.textContent = selectedName;
		this.selector.classList.toggle("hidden", !selectedName);
		this.selector.setAttribute(
			"aria-label",
			selectedName ? `Conversation: ${selectedName}` : "Conversation",
		);
		const activeConversation = this.current || null;
		this.mobileClearConversationContainer.dataset.visible = activeConversation
			? "true"
			: "false";
		this.mobileClearConversation.disabled = !activeConversation;
		if (activeConversation) {
			this.mobileClearConversation.dataset.deleteKey = activeConversation.id;
			this.mobileClearConversation.dataset.deleteModalRoute =
				ENDPOINTS.messages.clearModal(activeConversation.id);
			const clearLabel = `Clear conversation with ${activeConversation.peer.name}`;
			this.mobileClearConversation.setAttribute("aria-label", clearLabel);
			this.mobileClearConversation.title = clearLabel;
		} else {
			delete this.mobileClearConversation.dataset.deleteKey;
			delete this.mobileClearConversation.dataset.deleteModalRoute;
			this.mobileClearConversation.setAttribute(
				"aria-label",
				"Clear conversation",
			);
			this.mobileClearConversation.title = "Clear conversation";
		}
		this.conversationDropdown?.updateOptions(
			Array.from(this.conversations.values()).map((conversation) => ({
				name: `${conversation.peer.name}${
					conversation.unread ? ` (${conversation.unread} unread)` : ""
				}`,
				onClick: () => {
					const selectionRevision = this._beginConversationSelection(
						conversation.id,
					);
					return this.openConversation(conversation.id, {
						selectionRevision,
					});
				},
			})),
		);
	}

	/** @testable infrastructure */
	rememberConversation(key) {
		this.preferredConversation = key || null;
		if (!this.conversationStorageKey) return;
		if (key) localStorage.setItem(this.conversationStorageKey, key);
		else localStorage.removeItem(this.conversationStorageKey);
	}

	/** @testable infrastructure */
	async openConversation(key, { selectionRevision = null } = {}) {
		const response = await request.get(ENDPOINTS.messages.history(key));
		if (!response?.ok) return false;
		if (
			selectionRevision !== null &&
			selectionRevision !== this.conversationSelectionRevision
		) {
			return false;
		}
		this.current = response.conversation;
		this.rememberConversation(this.current.id);
		this.replyOperationId = this.operationId?.() || crypto.randomUUID();
		this.conversations.set(this.current.id, this.current);
		this.messageCursor = response.cursor || null;
		this.renderHeader();
		this.renderMessages(response.messages || []);
		this.renderConversations();
		if (this.mobile && !this.conversationDropdown) {
			await this._ensureConversationDropdown();
		}
		if (this.current.unread) {
			await this.markRead({
				selectionRevision:
					selectionRevision ?? this.conversationSelectionRevision,
			});
		}
		return true;
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
		const selectionRevision = this.conversationSelectionRevision;
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
		this._boostMessagePolling();
		this.replyTextarea.value = "";
		await this.loadConversations();
		if (selectionRevision === this.conversationSelectionRevision) {
			await this.openConversation(response.conversation.id, {
				selectionRevision,
			});
			this.replyTextarea.focus();
		}
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
		const conversation = this.current.id;
		const selectionRevision = this.conversationSelectionRevision;
		const params =
			prepend && this.messageCursor ? { cursor: this.messageCursor } : null;
		const response = await request.get(
			ENDPOINTS.messages.history(conversation),
			params,
		);
		if (!response?.ok) return;
		if (
			selectionRevision !== this.conversationSelectionRevision ||
			this.current?.id !== conversation
		) {
			return;
		}
		this.messageCursor = response.cursor || null;
		this.renderMessages(response.messages || [], { prepend });
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/messages.mjs::Messages
	 * @reason stale revision refresh is exercised through the view contract
	 */
	async markRead({
		selectionRevision = this.conversationSelectionRevision,
	} = {}) {
		const conversation = this.current;
		if (!conversation) return;
		const data = new FormData();
		data.set("revision", String(conversation.revision));
		const response = await request.post(
			ENDPOINTS.messages.read(conversation.id),
			data,
		);
		if (
			selectionRevision !== this.conversationSelectionRevision ||
			this.current?.id !== conversation.id
		) {
			if (response?.conversation) {
				this.conversations.set(conversation.id, response.conversation);
			}
			return;
		}
		if (!response?.ok) {
			if (response?.conversation) {
				await this.openConversation(conversation.id, { selectionRevision });
			}
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
		let replacement = null;
		let selectionRevision = null;
		if (this.current?.id === change.key) {
			this.current = null;
			this.messageCursor = null;
			this.history.replaceChildren();
			this.header.textContent = "Choose a conversation";
			this.renderReply();
			replacement = this.conversations.values().next().value?.id || null;
			selectionRevision = this._beginConversationSelection(replacement);
			this.rememberConversation(replacement);
		}
		this.renderConversations();
		return replacement
			? this.openConversation(replacement, { selectionRevision })
			: Promise.resolve();
	}

	destroy() {
		this.selector?.removeEventListener(
			"click",
			this._conversationSelectorClick,
		);
		this.elt.removeEventListener("mobile-resize", this._messagesMobileResize);
		this.conversationDropdown?.destroy?.();
		this.conversationDropdown = null;
		super.destroy();
	}
}

export { Messages as default };
