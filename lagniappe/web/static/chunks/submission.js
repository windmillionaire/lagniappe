/*! Third-party licenses: /third-party-licenses.txt */
import { c as captureError, w as withTransition, r as request } from './foundation.js?v=b276e1c2';
import './upstreamUnavailable.js?v=b276e1c2';
import './connectivity.js?v=b276e1c2';

/**
 * Coordinates the view-scoped form submission lifecycle.
 *
 * @testable true
 * @tests tests_js/test_015_core_submit_frontend.mjs::test_submit_abandons_stale_widget_after_async_prepare
 * @tests tests_js/test_015_core_submit_frontend.mjs::test_submit_does_not_show_upload_error_after_stale_prepare
 * @tests tests_js/test_015_core_submit_frontend.mjs::test_submit_stops_before_appending_when_form_data_is_missing
 * @tests tests_js/test_015_core_submit_frontend.mjs::test_submit_uses_explicit_action_route_over_active_widget_route
 * @tests tests_js/test_015_core_submit_frontend.mjs::test_conflict_review_failure_settles_update_button
 * @matrix submit : active-widget direct-upload-error direct-upload-navigation missing-form-data route-override stale-widget update-feedback
 * @matrix edited-entity-notice : structured-conflict
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
		const settle = () => event.detail?.onSettled?.();
		const component = this.view.getComponent(event.target);
		if (!component) {
			captureError(new Error("No component found"), event.target);
			settle();
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
			settle();
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
			settle();
			return;
		}
		if (prepared === false) {
			this._clearActiveSubmitter();
			settle();
			return;
		}

		if (
			component.active !== submitWidget ||
			!submitWidget?.target?.isConnected ||
			!submitForm?.isConnected
		) {
			this._clearActiveSubmitter();
			settle();
			return;
		}

		const data = component.formData;
		if (!data) {
			captureError(new Error("No form data found"), submitWidget.target);
			this._clearActiveSubmitter();
			settle();
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

		if (submitWidget.target?.hasAttribute("lp-create")) {
			this.create(component, data, route);
			settle();
		} else if (
			event.detail?.update ||
			submitWidget.target?.hasAttribute("lp-update")
		) {
			if (event.detail?.onSettled) {
				try {
					await this.update(component, data, route);
				} catch (error) {
					component.showError?.(error?.message || "Could not retry autofill.");
					captureError(error);
					this._clearActiveSubmitter();
				} finally {
					settle();
				}
			} else {
				void this.update(component, data, route).catch((error) => {
					if (
						component.active === submitWidget &&
						submitWidget?.target?.isConnected
					) {
						component.showError?.(
							"Could not finish the update. Please try again.",
						);
					}
					this._clearActiveSubmitter();
					captureError(error, submitWidget?.target);
				});
			}
		} else {
			settle();
		}
	}

	successfulResponse(response, component) {
		if (!response) return false;
		if (response.already_running) {
			component.active?.lockDeferredOperation?.(response);
			void this.view.ensureDeferredOperations?.().then((manager) =>
				manager?.track(response.operation, {
					node: component.active?.target,
				}),
			);
			component?.showError?.(
				response.message || "Autofill is already running. Your draft was kept.",
			);
			this._clearActiveSubmitter();
			return false;
		}
		if (response.conflict) return false;

		if (response.reload) {
			window.location.reload();
			return false;
		} else if (response.error || response.ok === false) {
			component?.showError?.(
				response.error ||
					response.message ||
					"The update was not saved. Please try again.",
			);
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

		const submittedWidget = component.active;
		const submittedSnapshot = submittedWidget?.revisionSnapshot?.();
		const response = await request.put(route, data);
		if (
			component.active !== submittedWidget ||
			submittedWidget?.target?.isConnected === false
		) {
			// The request still belongs to its original form after navigation.
			if (response?.deferred && response.operation) {
				const operations = await this.view.ensureDeferredOperations?.();
				operations?.track(response.operation, {
					status: response.status,
					revision: response.revision,
				});
			}
			this._clearActiveSubmitter();
			return;
		}
		if (response?.conflict) {
			try {
				const watcher = await this.view.ensureEditWatcher?.();
				if (await watcher?.stageConflict?.(submittedWidget, { response }))
					await watcher?.openConflictReview?.(submittedWidget, {
						blockedAction:
							data.get("role") === "autofill-submit" ? "autofill" : null,
					});
			} finally {
				submittedWidget.form?.resetSubmitButton?.();
				this._clearActiveSubmitter();
			}
			return;
		}
		if (!this.successfulResponse(response, component)) return;
		const changedDuringSave =
			submittedSnapshot !== submittedWidget?.revisionSnapshot?.();
		if (response.deferred) {
			if (response.form_revision && submittedWidget) {
				submittedWidget.reviewState =
					response.form_state ?? submittedWidget.reviewState ?? {};
				submittedWidget.reviewState.revision = response.form_revision;
				if (submittedWidget.initialTarget) {
					submittedWidget.initialTarget.dataset.formState = JSON.stringify(
						submittedWidget.reviewState,
					);
				}
				// A deferred start does not change the saved baseline or this tab's draft.
				delete submittedWidget._autofillRetry;
			}
			await this._deferredUpdated(response, component);
			return;
		}
		// A successful ordinary save consumed the review markers on the server.
		// Carrying them into a later Update would refer to an obsolete review.
		submittedWidget?._reviewedOperations?.clear();
		submittedWidget?._usedAutofillOperations?.clear();
		if (changedDuringSave) {
			if (Object.hasOwn(response, "submission"))
				submittedWidget._baselineSubmission = structuredClone(
					response.submission ?? {},
				);
			try {
				const watcher = await this.view.ensureEditWatcher?.();
				await watcher?.stageConflict?.(submittedWidget, { response });
			} finally {
				this._clearActiveSubmitter();
			}
			return;
		}
		submittedWidget?.form?.clearUnsavedState?.();

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
	 * @tests tests_js/test_015_core_submit_frontend.mjs::test_deferred_background_create_does_not_decorate_source_form
	 * @matrix deferred-jobs submit : background deferred-create destination-row
	 * @pair deferred-jobs:hosted-e2e
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
	 * @matrix deferred-jobs : form-schema refresh
	 * @matrix notifications tasks : autofill deferred
	 * @matrix pages : autofill deferred form-schema refresh
	 */
	async _deferredUpdated(response, component) {
		if (response.scope === "form-autofill" && !response.already_running) {
			const subform = component.active?.form?._subForm;
			if (subform) {
				subform.target.dataset.visible = "false";
				subform.reset?.();
				component.active.form.toggleSubForm();
			}
		}
		if (response.locked) {
			component.active?.lockDeferredOperation?.(response);
		}
		const [operations, notifications] = await Promise.all([
			this.view.ensureDeferredOperations?.(),
			response.notification ? this.view.ensureNotifications?.() : null,
		]);
		operations?.track(response.operation, {
			node: component.active?.target,
			status: response.status,
			revision: response.revision,
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
				response.scope !== "form-autofill" &&
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
