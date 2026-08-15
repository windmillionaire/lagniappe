/*! Third-party licenses: /third-party-licenses.txt */
import { c as captureError, w as withTransition, r as request } from './foundation.js?v=b3ba4dd3';
import './connectivity.js?v=b3ba4dd3';

/**
 * Coordinates the view-scoped form submission lifecycle.
 *
 * @testable true
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_abandons_stale_widget_after_async_prepare
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_does_not_show_upload_error_after_stale_prepare
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_stops_before_appending_when_form_data_is_missing
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_uses_explicit_action_route_over_active_widget_route
 * @features submit
 * @dimensions stale-widget direct-upload-navigation direct-upload-error missing-form-data route-override active-widget
 */
class SubmissionManager {
	constructor(view) {
		this.view = view;
		this.activeSubmitter = null;
		this.submit = this.submit.bind(this);
	}

	_clearActiveSubmitter() {
		if (this.activeSubmitter) {
			this.activeSubmitter.disabled = false;
			this.activeSubmitter = null;
		}
		this._syncOfflineSubmitStates();
	}

	_syncOfflineSubmitStates() {
		for (const component of Object.values(this.view?.components ?? {})) {
			for (const widget of Object.values(component.widgets)) {
				widget.form?.syncOfflineState?.();
			}
		}
	}

	_setActiveSubmitter(submitter) {
		if (!submitter) return;

		this.activeSubmitter = submitter;
		this.activeSubmitter.disabled = true;
	}

	async submit(event) {
		const component = this.view.getComponent(event.target);
		if (!component) {
			captureError(new Error("No component found"), event.target);
			return;
		}

		event.preventDefault();
		event.stopPropagation();

		const submitWidget = component.active;
		const submitForm = event.target;
		const route = event.detail?.route || component.route;

		this._setActiveSubmitter(event.submitter);
		if (submitWidget?.form?.syncOfflineState?.()) {
			this._clearActiveSubmitter();
			return;
		}

		let prepared = true;
		try {
			prepared = await submitWidget?.prepareSubmit?.({
				route,
				submitter: event.submitter,
			});
		} catch (error) {
			if (
				component.active === submitWidget &&
				submitWidget?.target?.isConnected &&
				submitForm?.isConnected
			) {
				component.showError(error.message || "Could not prepare upload");
			}
			this._clearActiveSubmitter();
			return;
		}
		if (prepared === false) {
			this._clearActiveSubmitter();
			return;
		}

		if (
			component.active !== submitWidget ||
			!submitWidget?.target?.isConnected ||
			!submitForm?.isConnected
		) {
			this._clearActiveSubmitter();
			return;
		}

		const data = component.formData;
		if (!data) {
			captureError(new Error("No form data found"), submitWidget.target);
			this._clearActiveSubmitter();
			return;
		}

		const role = event.submitter?.dataset?.role || event.detail?.role;
		if (
			submitWidget.target?.hasAttribute("lp-deferred") &&
			(typeof data.has !== "function" || !data.has("operation-id"))
		) {
			data.append("operation-id", this.view.operationId());
		}
		if (role) data.append("role", role);

		const explain = event.submitter?.dataset?.explain;
		if (explain) data.append("explain", explain);

		if (submitWidget.target?.hasAttribute("lp-create")) {
			this.create(component, data, route);
		} else if (
			event.detail?.update ||
			submitWidget.target?.hasAttribute("lp-update")
		) {
			this.update(component, data, route);
		}
	}

	successfulResponse(response, component) {
		if (!response) return false;

		if (response.reload) {
			window.location.reload();
			return false;
		} else if (response.error) {
			component?.showError?.(response.error);
			this._clearActiveSubmitter();
			return false;
		} else if (response.modal) {
			void this.view.ensureModalClasses?.().then(({ Modal } = {}) => {
				if (!Modal || this.view?._destroyed) return;
				new Modal(this.view).attach(response.modal, component);
			});
			this._clearActiveSubmitter();
			return false;
		}

		return true;
	}

	async update(component, data, route = component.route) {
		if (!this.view.online) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			const response = await queue?.queueSubmit(component, data, route, "PUT");
			if (response) {
				await withTransition(
					() => {
						component.active?.form?.queued?.();
						this._clearActiveSubmitter();
					},
					{ label: "submission:queue-offline" },
				);
			} else {
				this._clearActiveSubmitter();
			}
			return;
		}

		const response = await request.put(route, data);
		if (!this.successfulResponse(response, component)) return;
		component.active?.form?.clearUnsavedState?.();
		if (response.deferred) {
			await this._deferredUpdated(response, component);
			return;
		}

		try {
			await component.updated(response);
		} finally {
			this._clearActiveSubmitter();
		}
	}

	async create(component, data, route = component.route) {
		if (!this.view.online) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			const response = await queue?.queueSubmit(component, data, route, "POST");
			if (response) {
				try {
					await component.created(response);
				} finally {
					this._clearActiveSubmitter();
				}
			} else {
				this._clearActiveSubmitter();
			}
			return;
		}

		const response = await request.post(route, data);
		if (!this.successfulResponse(response, component)) return;
		component.active?.form?.clearUnsavedState?.();
		if (response.deferred) {
			await this._deferredCreated(response, component);
			return;
		}

		try {
			await component.created(response);
		} finally {
			this._clearActiveSubmitter();
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
	 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_submit_marks_form_successful
	 * @features pages
	 * @dimensions deferred-submit
	 */
	async _deferredCreated(response, component) {
		const [operations, notifications] = await Promise.all([
			this.view.ensureDeferredOperations?.(),
			response.notification ? this.view.ensureNotifications?.() : null,
		]);
		operations?.track(response.operation, {
			node: response.background ? null : component.active?.target,
		});
		if (response.notification) {
			notifications?.upsertNotification?.(response.notification);
		}

		if (response.html) {
			try {
				await component.created(response);
			} finally {
				this._clearActiveSubmitter();
			}
			return;
		}

		await component.active?.created?.(response);
		await component.active?.prereconcile?.();
		await withTransition(
			() => {
				component.active?.postreconcile?.();
				component.active?.success?.();
				this._clearActiveSubmitter();
			},
			{ label: "submission:create-without-html" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
	 * @pairs pages:autofill pages:deferred tasks:autofill tasks:deferred
	 * @pairs notifications:autofill notifications:deferred
	 * @pairs deferred-jobs:refresh deferred-jobs:form-schema
	 * @pairs pages:refresh pages:form-schema
	 */
	async _deferredUpdated(response, component) {
		if (response.locked) {
			component.active?.lockDeferredOperation?.(response);
		}
		const [operations, notifications] = await Promise.all([
			this.view.ensureDeferredOperations?.(),
			response.notification ? this.view.ensureNotifications?.() : null,
		]);
		operations?.track(response.operation, {
			node: component.active?.target,
		});
		if (response.notification) {
			notifications?.upsertNotification?.(response.notification);
		}

		if (response.html) {
			try {
				await component.updated(response);
			} finally {
				this._clearActiveSubmitter();
			}
			return;
		}

		await withTransition(() => {
			if (
				!component.active?.target?.querySelector(
					"[data-role='deferred-progress']",
				)
			) {
				component.active?.form?.success?.();
			}
			this._clearActiveSubmitter();
		});
	}

	destroy() {
		this._clearActiveSubmitter();
		this.view = null;
	}
}

export { SubmissionManager };
