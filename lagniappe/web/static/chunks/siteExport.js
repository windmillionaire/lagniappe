/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons } from './buttons.js?v=b2884058';
import { r as request, w as withTransition } from './foundation.js?v=b2884058';
import './connectivity.js?v=b2884058';
import './styles.js?v=b2884058';
import './icons.js?v=b2884058';
import './formatting.js?v=b2884058';

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
			icon: "download",
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
			this.updated(response);
			await withTransition(() => this.postreconcile(), {
				label: "site-export:refresh",
			});
		}
		const operations = await this.view.ensureDeferredOperations?.();
		operations?.track(response.operation, {
			node: this.target,
		});
		this.startButton.deactivate("Export Queued");
	}

	updated(response) {
		const replacement = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		if (!replacement) return;

		this._replacement = replacement;
		this._replacementVisible =
			this.visible || this.target.dataset.visible === "true";
	}

	prepareRefresh(response) {
		this.updated(response);
		return () => this.postreconcile();
	}

	refresh(response) {
		const commit = this.prepareRefresh(response);
		commit();
	}

	postreconcile() {
		if (!this._replacement) return;
		const replacement = this._replacement;
		const visible = this._replacementVisible;
		this._replacement = null;
		this.destroy();
		this.target.replaceWith(replacement);
		this.target = replacement;
		this.visible = visible;
		if (visible) this.target.dataset.visible = "true";
		this.target._lp_widget = this;
		this._bind();
	}

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
