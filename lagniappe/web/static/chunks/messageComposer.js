/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd5baecd';
import { r as request, E as ENDPOINTS } from './foundation.js?v=bd5baecd';
import './connectivity.js?v=bd5baecd';
import { c as createIcon } from './icons.js?v=bd5baecd';
import { Modal } from './modal.js?v=bd5baecd';
import { F as FacetsBox } from './facets.js?v=bd5baecd';
import './combobox.js?v=bd5baecd';
import './primitives.js?v=bd5baecd';
import './results.js?v=bd5baecd';
import './formatting.js?v=bd5baecd';
import './submitter.js?v=bd5baecd';

/**
 * @testable infrastructure
 * @covered-by src/script/elements/messageComposer.mjs::MessageComposer
 */
class ComposerModal extends Modal {
	constructor(composer) {
		super(composer.view, null);
		this.composer = composer;
	}

	destroy() {
		this.composer._releaseModal(this);
		super.destroy();
	}
}

/**
 * Shared modal used by the notification menu and messages page.
 *
 * @testable true
 * @tests tests_js/test_042_messaging_frontend.py::test_message_composer_prefills_peer_and_reuses_operation_on_submit
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
 * @pairs messaging:compose-modal messaging:prefilled-peer messaging:operation-id
 * @pairs messaging:user-kind messaging:selection-focus
 */
class MessageComposer {
	constructor(view, { onSent = null } = {}) {
		this.view = view;
		this.onSent = onSent;
		this.operationId = null;
		this._submit = this._submit.bind(this);
		this._recipientUpdated = this._recipientUpdated.bind(this);
	}

	init() {
		this.confirmation = document.querySelector(
			"[data-role='message-compose-confirmation']",
		);
		if (!this.confirmation) {
			this.confirmation = document.createElement("div");
			this.confirmation.dataset.role = "message-compose-confirmation";
			this.confirmation.setAttribute("role", "status");
			this.confirmation.className =
				"fixed bottom-4 right-4 z-50 hidden rounded-md bg-user-default px-4 py-3 font-medium text-white shadow-lg";
			document.body.appendChild(this.confirmation);
		}
		return this;
	}

	/** @testable infrastructure */
	_buildModal() {
		const spinner = createIcon("spinner").outerHTML;
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.dataset.role = "message-composer";
		modal.dataset.kind = "user";
		modal.className = STYLES.modal.wrapper;
		modal.setAttribute("role", "dialog");
		modal.setAttribute("aria-modal", "true");
		modal.setAttribute("aria-labelledby", "message-composer-title");
		modal.innerHTML = `
			<div id="modal-content" class="${STYLES.modal.content} w-full max-w-lg">
				<div class="${STYLES.modal.header}">
					<h2 id="message-composer-title" class="text-xl font-bold text-base-dark">New message</h2>
					<button type="button" lp-control="close" class="${STYLES.button.close}">Close</button>
				</div>
				<form data-role="message-compose-form" data-kind="user" class="space-y-4 p-6">
					<label class="block text-sm font-medium">To
						<input type="search" name="recipient" data-index="user" data-permission="message"
							data-kind="user"
							data-placeholder="Search managed users"
							class="${STYLES.input} mt-1">
					</label>
					<label class="block text-sm font-medium">Message
						<textarea name="body" data-kind="user" maxlength="1000" required rows="5"
							class="${STYLES.textarea} mt-1"></textarea>
					</label>
					<p data-role="message-compose-error" class="hidden text-sm text-delete-default"></p>
					<div class="${STYLES.modal.actions}">
						<button type="submit" data-kind="user" class="${STYLES.button.submit}">
							<span data-role="icon" data-visible="false" aria-hidden="true">${spinner}</span>
							<span data-role="text">Send</span>
						</button>
					</div>
				</form>
			</div>`;
		return modal;
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/messageComposer.mjs::MessageComposer
	 * @reason prefill and operation allocation are exercised through the modal contract
	 */
	async open(recipient = null) {
		await this.close();
		const modal = this._buildModal();
		const controller = new ComposerModal(this);
		this.modalController = controller;
		await controller.attach(modal, this);
		this.dialog = modal;
		this.form = modal.querySelector("[data-role='message-compose-form']");
		this.input = this.form.querySelector("input[data-index='user']");
		this.body = this.form.querySelector("textarea[name='body']");
		this.submit = this.form.querySelector("button[type='submit']");
		this.error = this.form.querySelector("[data-role='message-compose-error']");
		this.recipient = new FacetsBox(this.input);
		this.recipient.init();
		this.input.addEventListener("updated", this._recipientUpdated);
		this.form.addEventListener("submit", this._submit);
		this._activate(recipient);
	}

	/** @testable infrastructure */
	_recipientUpdated(event) {
		if (Object.keys(event.detail?.options || {}).length) this.body?.focus();
	}

	/** @testable infrastructure */
	_setSubmitting(value) {
		if (!this.submit) return;
		this.submit.disabled = value;
		const icon = this.submit.querySelector("[data-role='icon']");
		if (icon) icon.dataset.visible = value ? "true" : "false";
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/messageComposer.mjs::MessageComposer
	 * @reason modal state initialization is exercised through the composer contract
	 */
	_activate(recipient = null) {
		this.operationId = this.view.operationId?.() || crypto.randomUUID();
		this.error.classList.add("hidden");
		this.error.textContent = "";
		this.recipient.clear({ notify: false });
		if (recipient?.id && recipient?.available !== false) {
			this.recipient.addOption(
				{
					id: recipient.id,
					name: recipient.name,
					kind: "user",
				},
				true,
			);
		}
		(recipient ? this.body : this.input).focus();
	}

	/** @testable infrastructure */
	async close() {
		await this.modalController?.remove();
	}

	/** @testable infrastructure */
	_releaseModal(controller) {
		this.form?.removeEventListener("submit", this._submit);
		this.input?.removeEventListener("updated", this._recipientUpdated);
		this.recipient?.destroy?.();
		this.form = null;
		this.input = null;
		this.body = null;
		this.submit = null;
		this.error = null;
		this.recipient = null;
		this.dialog = null;
		if (this.modalController === controller) this.modalController = null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/messageComposer.mjs::MessageComposer
	 * @reason idempotent submission is exercised through the modal contract
	 */
	async _submit(event) {
		event.preventDefault();
		const selected = this.recipient.selectedOptions?.[0];
		if (!selected?.recipient_key && !selected?.id) {
			this.error.textContent = "Choose a message recipient.";
			this.error.classList.remove("hidden");
			this.input.focus();
			return;
		}
		const data = new FormData(this.form);
		if (selected?.recipient_key || selected?.id) {
			data.set("recipient", selected.recipient_key || selected.id);
		}
		data.set("operation_id", this.operationId || crypto.randomUUID());
		this._setSubmitting(true);
		let response;
		try {
			response = await request.post(ENDPOINTS.messages.send, data);
		} finally {
			this._setSubmitting(false);
		}
		if (!response?.ok) {
			this.error.textContent = response?.error || "Message could not be sent.";
			this.error.classList.remove("hidden");
			return;
		}
		this.body.value = "";
		this.recipient.clear({ notify: false });
		await this.close();
		this.confirmation.textContent = "Message sent.";
		this.confirmation.classList.remove("hidden");
		clearTimeout(this.confirmationTimer);
		this.confirmationTimer = setTimeout(
			() => this.confirmation.classList.add("hidden"),
			3000,
		);
		await this.onSent?.(response);
	}

	destroy() {
		clearTimeout(this.confirmationTimer);
		this.modalController?.destroy();
	}
}

/**
 * @testable false
 * @covered-by src/script/elements/messageComposer.mjs::MessageComposer
 * @reason singleton reuse is composition around the tested modal controller
 */
const ensureMessageComposer = (view, options = {}) => {
	if (!view.MessageComposer) {
		view.MessageComposer = new MessageComposer(view, options).init();
	} else if (options.onSent) {
		view.MessageComposer.onSent = options.onSent;
	}
	return view.MessageComposer;
};

export { MessageComposer, ensureMessageComposer };
