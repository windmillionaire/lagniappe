import type { Dropdown } from "../elements/combobox/dropdown.ts";
import { ensureMessageComposer } from "../elements/messageComposer.ts";
import { STYLES } from "../generated/styles.mjs";
import { createIcon } from "../shared/icons.ts";
import { ENDPOINTS, request } from "../shared/index.ts";
import type { RequestResult } from "../types/api.d.ts";
import type {
	MessageConversation,
	MessageEntry,
	MessageSendResponse,
} from "../types/messaging.d.ts";
import Core, { type ReconcileChange } from "./base/core.ts";

const MESSAGE_POLL_SUBSCRIPTION = "view:channel:messages";

type Conversation = MessageConversation & { id: string };
type ConversationOptions = { selectionRevision?: number | null };
type ConversationList = {
	conversations: MessageConversation[];
	cursor: string | null;
};
type MessageHistory = MessageSendResponse & {
	messages: MessageEntry[];
	cursor: string | null;
};

function hasConversationId(
	conversation: MessageConversation | undefined,
): conversation is Conversation {
	return typeof conversation?.id === "string";
}

function requiredControl<T extends HTMLElement = HTMLElement>(
	root: ParentNode,
	selector: string,
): T {
	const control = root.querySelector<T>(selector);
	if (!control) throw new Error(`Missing message control: ${selector}`);
	return control;
}

export default class Messages extends Core {
	declare list: HTMLElement;
	declare selector: HTMLButtonElement;
	declare selectorLabel: HTMLElement;
	declare mobileClearConversation: HTMLButtonElement;
	declare mobileClearConversationContainer: HTMLElement;
	declare history: HTMLElement;
	declare header: HTMLElement;
	declare loadConversationsButton: HTMLButtonElement;
	declare loadMessagesButton: HTMLButtonElement;
	declare replyForm: HTMLFormElement;
	declare replyTextarea: HTMLTextAreaElement;
	declare replyError: HTMLElement;
	declare replySubmit: HTMLButtonElement;
	declare replySpinner: HTMLElement;
	declare current: Conversation | null;
	declare conversationSelectionRevision: number;
	declare conversationListRevision: number;
	declare conversationCursor: string | null;
	declare messageCursor: string | null;
	declare conversations: Map<string, Conversation>;
	declare conversationStorageKey: string;
	declare preferredConversation: string | null;
	declare composer?: ReturnType<typeof ensureMessageComposer>;
	declare conversationDropdown?: Dropdown | null;
	declare replyOperationId?: string;
	declare _conversationSelectorClick?: (event: MouseEvent) => void;
	declare _messagesMobileResize?: EventListener;
	declare _messageRefresh?: Promise<boolean> | null;
	declare _conversationDropdownPromise?: Promise<Dropdown | null> | null;

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

	_boostMessagePolling() {
		this.PollingCoordinator?.boost?.(MESSAGE_POLL_SUBSCRIPTION, {
			durationMs: 60_000,
			pollAfterMs: 2_000,
		});
	}

	async init() {
		await super.init();
		this.list = requiredControl(this.elt, "[data-role='conversation-list']");
		this.selector = requiredControl<HTMLButtonElement>(
			this.elt,
			"[data-role='conversation-selector']",
		);
		this.selectorLabel = requiredControl(
			this.selector,
			"[data-role='conversation-selector-label']",
		);
		this.mobileClearConversation = requiredControl<HTMLButtonElement>(
			this.elt,
			"[data-role='mobile-clear-conversation']",
		);
		this.mobileClearConversationContainer = requiredControl(
			this.elt,
			"[data-role='mobile-clear-conversation-container']",
		);
		this.history = requiredControl(this.elt, "[data-role='message-history']");
		this.header = requiredControl(this.elt, "[data-role='message-header']");
		this.loadConversationsButton = requiredControl<HTMLButtonElement>(
			this.elt,
			"[data-action='load-conversations']",
		);
		this.loadMessagesButton = requiredControl<HTMLButtonElement>(
			this.elt,
			"[data-action='load-messages']",
		);
		this.replyForm = requiredControl<HTMLFormElement>(
			this.elt,
			"[data-role='message-reply']",
		);
		this.replyTextarea = requiredControl<HTMLTextAreaElement>(
			this.replyForm,
			"textarea[name='body']",
		);
		this.replyError = requiredControl(
			this.replyForm,
			"[data-role='message-reply-error']",
		);
		this.replySubmit = requiredControl<HTMLButtonElement>(
			this.replyForm,
			"button[type='submit']",
		);
		this.replySpinner = requiredControl(this.replySubmit, "[data-role='icon']");
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
			composeButton.addEventListener("click", () => this.composer?.open());
		}
		this.list.addEventListener("click", (event) => {
			const button = (
				event.target as Element | null
			)?.closest?.<HTMLButtonElement>("[data-conversation]");
			const key = button?.dataset.conversation;
			if (key) {
				const selectionRevision = this._beginConversationSelection(key);
				void this.openConversation(key, {
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
			const target = event.target as Element | null;
			if (
				target?.closest?.<HTMLButtonElement>(
					"[data-action='start-conversation']",
				)
			) {
				this.composer?.open();
				return;
			}
			const button = target?.closest?.<HTMLButtonElement>(
				"[data-action='delete-message']",
			);
			if (button?.dataset.message)
				void this.deleteMessage(button.dataset.message);
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
		].filter((key, index, values): key is string =>
			Boolean(key && values.indexOf(key) === index),
		);
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
		if (!opened) {
			this.renderEmptyHistory();
		}
		return this;
	}

	async refresh() {
		if (this._messageRefresh) return this._messageRefresh;
		const pending = this._refreshMessages().finally(() => {
			if (this._messageRefresh === pending) this._messageRefresh = null;
		});
		this._messageRefresh = pending;
		return pending;
	}

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
		this.header.textContent =
			this.conversations.size > 0 ? "Choose a conversation" : "Messages";
		this.renderEmptyHistory();
		this.renderReply();
		this.rememberConversation(null);
		this.renderConversationSelector();
		return false;
	}

	_beginConversationSelection(key: string | null) {
		this.preferredConversation = key || null;
		return ++this.conversationSelectionRevision;
	}

	async handleMessageSent(response: RequestResult<MessageSendResponse>) {
		const conversation = response.conversation?.id;
		if (!conversation) return false;
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

	async _ensureConversationDropdown(): Promise<Dropdown | null> {
		if (this.conversationDropdown || this._conversationDropdownPromise) {
			return (
				this.conversationDropdown ?? this._conversationDropdownPromise ?? null
			);
		}
		this._conversationDropdownPromise = import(
			"../elements/combobox/dropdown.ts"
		)
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

	async loadConversations({ append = false } = {}) {
		const listRevision = ++this.conversationListRevision;
		const params =
			append && this.conversationCursor
				? { cursor: this.conversationCursor }
				: null;
		const response = await request.get<ConversationList>(
			ENDPOINTS.messages.conversations,
			params,
		);
		if (!response?.ok) return;
		if (listRevision !== this.conversationListRevision) return;
		if (!append) this.conversations.clear();
		for (const conversation of response.conversations || []) {
			if (hasConversationId(conversation))
				this.conversations.set(conversation.id, conversation);
		}
		this.conversationCursor = response.cursor || null;
		this.renderConversations();
	}

	renderConversations() {
		const conversations = Array.from(this.conversations.values());
		this.elt.dataset.empty = conversations.length === 0 ? "true" : "false";
		if (conversations.length === 0 && typeof document !== "undefined") {
			const empty = document.createElement("p");
			empty.dataset.role = "empty";
			empty.className = STYLES.messages?.sidebarEmpty || "";
			empty.textContent = "No conversations yet.";
			this.list.replaceChildren(empty);
		} else {
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
		}
		this.renderConversationSelector();
		this.loadConversationsButton.classList.toggle(
			"hidden",
			!this.conversationCursor,
		);
	}

	renderConversationSelector() {
		const selected =
			this.current ||
			(this.preferredConversation &&
				this.conversations.get(this.preferredConversation)) ||
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

	rememberConversation(key: string | null) {
		this.preferredConversation = key || null;
		if (!this.conversationStorageKey) return;
		if (key) localStorage.setItem(this.conversationStorageKey, key);
		else localStorage.removeItem(this.conversationStorageKey);
	}

	async openConversation(
		key: string,
		{ selectionRevision = null }: ConversationOptions = {},
	) {
		const response = await request.get<MessageHistory>(
			ENDPOINTS.messages.history(key),
		);
		if (!response?.ok || !hasConversationId(response.conversation))
			return false;
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

	renderHeader() {
		if (!this.current) return;
		const title = document.createElement("span");
		title.className = "font-semibold";
		title.textContent = this.current.peer.deleted
			? `${this.current.peer.name} (deleted)`
			: this.current.peer.name;
		this.header.replaceChildren(title);
		this.renderReply();
	}

	renderReply() {
		const available = Boolean(this.current?.peer?.replyable);
		this.replyForm.classList.toggle("hidden", !available);
		this.replyTextarea.disabled = !available;
		this.replySubmit.disabled = !available;
		this.replySpinner.dataset.visible = "false";
		this.replyError.classList.add("hidden");
		this.replyError.textContent = "";
	}

	async sendReply(event: Event) {
		event.preventDefault();
		if (!this.current?.peer?.replyable || this.replySubmit.disabled) return;
		const selectionRevision = this.conversationSelectionRevision;
		const conversation = this.current.id;
		const data = new FormData();
		data.set("recipient", String(this.current.peer.id));
		data.set("conversation", conversation);
		data.set("body", this.replyTextarea.value);
		data.set(
			"operation_id",
			this.replyOperationId || this.operationId?.() || crypto.randomUUID(),
		);
		this.replyError.classList.add("hidden");
		this.replySubmit.disabled = true;
		this.replySpinner.dataset.visible = "true";
		let response: RequestResult<MessageSendResponse> | undefined;
		try {
			response = await request.post<MessageSendResponse>(
				ENDPOINTS.messages.send,
				data,
			);
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
		const sentConversation = response.conversation?.id;
		if (
			sentConversation &&
			selectionRevision === this.conversationSelectionRevision
		) {
			await this.openConversation(sentConversation, {
				selectionRevision,
			});
			this.replyTextarea.focus();
		}
	}

	renderEmptyHistory() {
		if (typeof document === "undefined" || !this.elt) {
			this.history.replaceChildren();
			return;
		}
		const container = document.createElement("div");
		container.dataset.role = "empty";
		container.className = STYLES.messages?.empty?.container || "";

		const hasConversations = this.conversations.size > 0;
		this.elt.dataset.empty = hasConversations ? "false" : "true";
		const title = document.createElement("p");
		title.className = STYLES.messages?.empty?.title || "";
		title.textContent = hasConversations
			? "Select a conversation"
			: "No conversations yet";

		const body = document.createElement("p");
		body.className = STYLES.messages?.empty?.body || "";
		if (hasConversations) {
			body.textContent =
				"Choose a conversation from the list to view messages.";
		} else if (this.composer) {
			body.textContent =
				"Start a direct message with someone in your workspace.";
		} else {
			body.textContent = "Direct messages from other users will appear here.";
		}

		container.append(title, body);

		if (!hasConversations && this.composer) {
			const button = document.createElement("button");
			button.type = "button";
			button.dataset.action = "start-conversation";
			button.className = STYLES.messages?.empty?.action || "";
			button.append(createIcon("add"), document.createTextNode("New message"));
			container.append(button);
		}

		this.history.replaceChildren(container);
		this.loadMessagesButton?.classList?.add("hidden");
	}

	renderMessages(messages: MessageEntry[], { prepend = false } = {}) {
		const nodes = messages.map((message) => {
			const article = document.createElement("article");
			article.dataset.message = String(message.id);
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
			remove.dataset.message = String(message.id);
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

	async loadHistory({ prepend = false } = {}) {
		if (!this.current) return;
		const conversation = this.current.id;
		const selectionRevision = this.conversationSelectionRevision;
		const params =
			prepend && this.messageCursor ? { cursor: this.messageCursor } : null;
		const response = await request.get<MessageHistory>(
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

	async markRead({
		selectionRevision = this.conversationSelectionRevision,
	} = {}) {
		const conversation = this.current;
		if (!conversation) return;
		const data = new FormData();
		data.set("revision", String(conversation.revision));
		const response = await request.post<MessageSendResponse>(
			ENDPOINTS.messages.read(conversation.id),
			data,
		);
		if (
			selectionRevision !== this.conversationSelectionRevision ||
			this.current?.id !== conversation.id
		) {
			if (hasConversationId(response?.conversation)) {
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
		if (!hasConversationId(response.conversation)) return;
		this.current = response.conversation;
		this.conversations.set(this.current.id, this.current);
		this.renderConversations();
	}

	async deleteMessage(key: string) {
		const response = await request.delete(ENDPOINTS.messages.remove(key));
		if (!response?.ok) return;
		this.history.querySelector(`[data-message="${CSS.escape(key)}"]`)?.remove();
	}

	reconcileChange(change: ReconcileChange = {}) {
		if (
			change.type !== "delete" ||
			!change.key ||
			!this.conversations.has(change.key)
		) {
			return super.reconcileChange(change);
		}
		this.conversations.delete(change.key);
		let replacement = null;
		let selectionRevision = null;
		if (this.current?.id === change.key) {
			this.current = null;
			this.messageCursor = null;
			this.header.textContent = "Choose a conversation";
			replacement = this.conversations.values().next().value?.id || null;
			if (replacement) this.history.replaceChildren();
			else this.renderEmptyHistory();
			this.renderReply();
			selectionRevision = this._beginConversationSelection(replacement);
			this.rememberConversation(replacement);
		}
		this.renderConversations();
		return replacement
			? this.openConversation(replacement, { selectionRevision })
			: Promise.resolve();
	}

	destroy() {
		if (this._conversationSelectorClick) {
			this.selector?.removeEventListener(
				"click",
				this._conversationSelectorClick,
			);
		}
		if (this._messagesMobileResize) {
			this.elt.removeEventListener("mobile-resize", this._messagesMobileResize);
		}
		this.conversationDropdown?.destroy?.();
		this.conversationDropdown = null;
		super.destroy();
	}
}
