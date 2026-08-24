/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b05079d4';
import { c as captureError, E as ENDPOINTS, r as request, w as withTransition } from './foundation.js?v=b05079d4';
import './connectivity.js?v=b05079d4';

/**
 * @testable infrastructure
 */
class Modal {
	constructor(view, trigger) {
		this.trigger = trigger;
		this.view = view;
		this.keydown = this._keydown.bind(this);
		this.click = this._click.bind(this);
		this.key = null;
	}

	_attachListeners() {
		document.addEventListener("keydown", this.keydown);
		document.addEventListener("click", this.click);
		this.modal._lp_modal = this;
	}

	destroy() {
		document.removeEventListener("keydown", this.keydown);
		document.removeEventListener("click", this.click);
		if (this.modal) this.modal.remove();
		if (this.trigger) this.trigger.disabled = false;
	}

	get modal() {
		return document.getElementById("modal");
	}

	_keydown(event) {
		const modal = this.modal;
		if (!modal) return;

		if (event.key === "Escape") {
			this.remove();
		} else if (event.key === "Enter" && event.target.tagName === "BUTTON") {
			event.target.click();
		} else if (event.key === "Tab") {
			const focusable = modal.querySelectorAll(
				'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
			);
			if (!focusable.length) return;

			const first = focusable[0];
			const last = focusable[focusable.length - 1];

			if (event.shiftKey) {
				if (
					document.activeElement === first ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					last.focus();
				}
			} else {
				if (
					document.activeElement === last ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					first.focus();
				}
			}
		}
	}

	_click(event) {
		const modal = this.modal;

		if (this.trigger?.contains(event.target)) return;

		const content = modal?.querySelector("#modal-content");
		if (content && !content.contains(event.target)) {
			this.remove();
		} else if (event.target.closest("[lp-control='close']")) {
			event.stopPropagation();
			this.remove();
		}
	}

	async remove() {
		await withTransition(
			() => {
				this.destroy();
			},
			{ label: "modal:remove" },
		);
	}

	async load(route) {
		if (this.trigger) this.trigger.disabled = true;
		try {
			const modal = await request.get(route);
			if (!modal.html) {
				captureError(new Error("No modal HTML provided"), this.trigger, {
					view: this.view?.dataset,
					route,
					modal,
				});
				if (this.trigger) this.trigger.disabled = false;
				return null;
			}
			await this.attach(modal.html);
			if (this.trigger) this.trigger.disabled = false;
		} catch (error) {
			captureError(error, this.trigger, this.view?.dataset);
			if (this.trigger) this.trigger.disabled = false;
		}
	}

	async attach(html, component) {
		try {
			if (this.trigger) this.trigger.disabled = true;
			const modal = html.querySelector("#modal") || html;
			await withTransition(
				() => {
					document.body.appendChild(modal);
					this._attachListeners();
				},
				{ label: "modal:attach" },
			);
			return modal;
		} catch (error) {
			captureError(error, component, this.view?.dataset);
			return null;
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_delete_category
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_delete_project
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_delete_page_from_title_menu
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_delete_page_task_from_page_row
 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_delete_task_from_row
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_delete_user_can_preserve_page
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
 * @pairs categories:delete projects:delete model-tasks:delete pages:delete
 * @pairs tasks:delete task-index:delete forms:delete users:delete users:options
 * @pair messaging:clear-confirmation
 */
class DeleteModal extends Modal {
	async init() {
		const entity =
			this.trigger.closest("[lp-entity]") ||
			this.trigger
				.closest("[lp-component]")
				?._lp_component?.active?.target?.closest("[lp-entity]");
		this.key =
			this.trigger.dataset.deleteKey || entity?.dataset?.key || entity?.id;

		if (!this.key || !this.view) {
			captureError(
				new Error("No key or view provided"),
				this.trigger,
				this.view?.dataset,
			);
			return;
		}

		await this.load(
			this.trigger.dataset.deleteModalRoute || ENDPOINTS.delete(this.key),
		);

		const modal = this.modal;
		if (!modal) {
			if (this.trigger) this.trigger.disabled = false;
			return;
		}

		this.deleteButton = modal.querySelector("[data-role='delete']");
		if (!this.deleteButton) {
			if (this.trigger) this.trigger.disabled = false;
			captureError(
				new Error("Delete modal missing [data-role='delete']"),
				this.trigger,
				{ view: this.view?.dataset },
			);
			return;
		}
		this.deleteButton.addEventListener("click", this.delete.bind(this));
		this.deleteButton.focus();
	}

	removeEntity(key) {
		document.querySelectorAll(`[data-key='${key}']`).forEach((elt) => {
			elt.closest("[lp-component]");
			if (elt._lp_component) elt._lp_component.destroy();
			elt.remove();
		});
	}

	async delete() {
		try {
			this.deleteButton.disabled = true;
			this.deleteButton.querySelector("#spinner").dataset.visible = "true";
			const route = this.deleteButton.dataset.route;
			const options = Array.from(
				this.modal.querySelectorAll("[data-delete-option][name]"),
			);
			const data = options.length
				? Object.fromEntries(
						options.map((option) => [option.name, option.checked]),
					)
				: null;

			const response = await request.delete(route, data);
			if (!response.ok) {
				this.deleteButton.disabled = false;
				this.deleteButton.querySelector("#spinner").dataset.visible = "false";
				return;
			}

			await this.remove();
			const returnUrl = this.trigger?.dataset.returnUrl;
			if (returnUrl) {
				window.location.assign(returnUrl);
				return;
			}

			await this.view?.reconcileChange?.({ type: "delete", key: this.key });
		} catch (error) {
			this.deleteButton.disabled = false;
			this.deleteButton.querySelector("#spinner").dataset.visible = "false";
			captureError(error, this.deleteButton, this.view.dataset);
		}
	}
}

/**
 * @testable infrastructure
 */
class HelpModal extends Modal {
	async init() {
		const section =
			this.trigger.closest("[lp-component]")?._lp_component?.help ||
			this.trigger.getAttribute("lp-help") ||
			this.trigger.closest("nav[lp-help]").getAttribute("lp-help");

		if (!section) {
			captureError(
				new Error("No section provided"),
				this.trigger,
				this.view.dataset,
			);
			return;
		}

		await this.load(ENDPOINTS.help(section));
	}
}

/**
 * @testable infrastructure
 */
class OfflineModal extends Modal {
	async attach() {
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;

		const content = modal.appendChild(document.createElement("div"));
		content.className = STYLES.modal.content;
		content.id = "modal-content";

		const header = content.appendChild(document.createElement("div"));
		header.className = STYLES.modal.header;
		const headerText = header.appendChild(document.createElement("h2"));
		headerText.textContent = "Offline";
		headerText.className = "text-lg font-bold text-base-dark";
		const close = header.appendChild(document.createElement("button"));
		close.textContent = "Close";
		close.className = `${STYLES.button.close}`;
		close.onclick = () => {
			void this.remove();
		};

		const body = content.appendChild(document.createElement("div"));
		body.className = "p-6 text-slate-600";
		const bodyText = body.appendChild(document.createElement("p"));
		bodyText.textContent =
			"You are offline (or the server is starting up). You will be able to view any pages that have been " +
			"cached, but search, documents and forms will be in read-only mode until you are online again.";

		await super.attach(modal);
	}

	enable() {
		if (!this.trigger) return;
		this.trigger.addEventListener("click", this.attach.bind(this));
	}
}

export { DeleteModal, HelpModal, Modal, OfflineModal };
