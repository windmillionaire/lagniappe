/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons } from './buttons.js?v=b7488009';
import { r as request } from './request.js?v=b7488009';
import './connectivity.js?v=b7488009';
import { withTransition } from './utilities.js?v=b7488009';
import './styles.js?v=b7488009';
import './icons.js?v=b7488009';
import './formatting.js?v=b7488009';
import './errors.js?v=b7488009';

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001f_site_export.py::test_owner_can_start_html_export
 * @pairs export:start-export export:notification
 */
class SiteExport {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.refreshScope = "collection";
		this.startButton = null;
		this.error = null;
		this._click = this._click.bind(this);
	}

	init() {
		this._bind();
	}

	_bind() {
		this.startButton = buttons.active({
			existingButton: this.target.querySelector("[data-role='start-export']"),
			text: "Start Export",
			processingText: "Starting Export",
			completedText: "Export Queued",
			processingIcon: "spinner",
			completedIcon: "check",
		});
		this.error = this.target.querySelector("[data-role='site-export-error']");
		this.target.addEventListener("click", this._click);
		this.target.setAttribute("initialized", "");
	}

	async _click(event) {
		const button = event.target.closest("[data-role='start-export']");
		if (!button) return;

		event.preventDefault();
		event.stopPropagation();
		await this._start();
	}

	async _start() {
		this._showError("");
		this.startButton.activate();

		const response = await request.post(this.endpoints.start, {
			operation_id: this.view.operationId(),
		});
		if (!response?.ok) {
			this._showError(response?.error || "Unable to start export.");
			this.startButton.deactivate("Start Export");
			return;
		}

		if (response.notification) {
			const notifications = await this.view.ensureNotifications?.();
			notifications?.upsertNotification?.(response.notification);
		}
		if (response.html) {
			await this.updated(response);
		}
		const operations = await this.view.ensureDeferredOperations?.();
		operations?.track(response.operation, {
			node: this.target,
		});
		this.startButton.deactivate("Export Queued");
	}

	async updated(response) {
		const replacement = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		if (!replacement) return;

		const wasVisible = this.visible || this.target.dataset.visible === "true";
		this.destroy();
		await withTransition(() => {
			this.target.replaceWith(replacement);
			this.target = replacement;
			this.visible = wasVisible;
			if (wasVisible) this.target.dataset.visible = "true";
			this.target._lp_widget = this;
			this._bind();
		});
	}

	async refresh(response) {
		await this.updated(response);
	}

	postreconcile() {}

	_showError(message) {
		if (!this.error) return;
		this.error.textContent = message || "";
		this.error.dataset.visible = message ? "true" : "false";
	}

	destroy() {
		this.target?.removeEventListener("click", this._click);
	}
}

export { SiteExport };
