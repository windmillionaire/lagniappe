import { captureError } from "../../shared/errors.ts";
import { request } from "../../shared/request.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { RequestResult } from "../../types/api";
import type {
	FormReviewOperation,
	FormRevisionFields,
} from "../../types/forms";
import type { LoadedWidget } from "../../types/widgets";
import type { FormWidget } from "../../widgets/base/formWidget.ts";
import type ViewComponent from "./component.ts";
import type Core from "./core.ts";

interface SubmitAction {
	role?: string;
	route?: string;
	update?: boolean;
	onSettled?(): void;
}

export type ViewSubmitEvent = SubmitEvent | CustomEvent<SubmitAction>;

type SubmissionFields = FormRevisionFields & {
	already_running: boolean;
	background: boolean;
	blocks_edit: boolean;
	deferred: boolean;
	form_revision: string;
	locked: boolean;
	message: string;
	notification: string | null;
	operation: string | null;
	revision: number | string;
	scope: string;
};

type SubmissionResponse = RequestResult<SubmissionFields>;
type Submitter = HTMLElement & { disabled: boolean };

function getSubmissionWidget(component: ViewComponent): LoadedWidget | null {
	const { active } = component;
	return active && !("standalone" in active) ? active : null;
}

function isRevisionWidget(
	widget: LoadedWidget | null,
): widget is LoadedWidget & FormWidget {
	return Boolean(
		widget &&
			"revisionSnapshot" in widget &&
			typeof widget.revisionSnapshot === "function",
	);
}

function isOperationStatus(value: unknown): value is FormReviewOperation {
	return Boolean(
		value &&
			typeof value === "object" &&
			"key" in value &&
			typeof value.key === "string",
	);
}

function isSubmitter(
	element: HTMLElement | null | undefined,
): element is Submitter {
	return Boolean(
		element && "disabled" in element && typeof element.disabled === "boolean",
	);
}

function isSubmitTarget(target: EventTarget | null): target is Element {
	return Boolean(
		target && "closest" in target && typeof target.closest === "function",
	);
}

/**
 * Coordinates the view-scoped form submission lifecycle.
 *
 */
export class SubmissionManager {
	declare view: Core | null;
	declare activeSubmitter: Submitter | null;

	constructor(view: Core) {
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

	_setActiveSubmitter(submitter: Submitter | null) {
		if (!submitter) return;

		this.activeSubmitter = submitter;
		this.activeSubmitter.disabled = true;
	}

	async submit(event: ViewSubmitEvent) {
		const view = this.view;
		if (!view) return;
		const detail = "detail" in event ? event.detail : undefined;
		const settle = () => detail?.onSettled?.();
		const submitForm = isSubmitTarget(event.target) ? event.target : null;
		const component = view.getComponent(submitForm);
		if (!component) {
			captureError(new Error("No component found"), event.target);
			settle();
			return;
		}

		event.preventDefault();
		event.stopPropagation();

		const submitWidget = getSubmissionWidget(component);
		const route = detail?.route || component.route;
		const submitter = "submitter" in event ? event.submitter : null;

		this._setActiveSubmitter(isSubmitter(submitter) ? submitter : null);
		if (submitWidget?.form?.syncOfflineState?.()) {
			this._clearActiveSubmitter();
			settle();
			return;
		}

		let prepared: boolean | undefined;
		try {
			prepared = await submitWidget?.prepareSubmit?.({
				route,
				submitter,
			});
		} catch (error) {
			if (
				component.active === submitWidget &&
				submitWidget?.target?.isConnected &&
				submitForm?.isConnected
			) {
				component.showError(
					(error instanceof Error && error.message) ||
						"Could not prepare upload",
				);
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

		const role = submitter?.dataset?.role || detail?.role;
		if (
			submitWidget.target?.hasAttribute("lp-deferred") &&
			(typeof data.has !== "function" || !data.has("operation-id"))
		) {
			data.append("operation-id", view.operationId());
		}
		if (role) data.append("role", role);

		if (submitWidget.target?.hasAttribute("lp-create")) {
			void this.create(component, data, route);
			settle();
		} else if (
			detail?.update ||
			submitWidget.target?.hasAttribute("lp-update")
		) {
			if (detail?.onSettled) {
				try {
					await this.update(component, data, route);
				} catch (error) {
					component.showError?.(
						(error instanceof Error && error.message) ||
							"Could not retry autofill.",
					);
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

	successfulResponse(
		response: SubmissionResponse | undefined,
		component: ViewComponent,
	): response is SubmissionResponse {
		if (!response) return false;
		if (response.already_running) {
			const widget = getSubmissionWidget(component);
			if (isRevisionWidget(widget)) {
				widget.lockDeferredOperation?.({
					...response,
					status: isOperationStatus(response.status)
						? response.status
						: undefined,
				});
			}
			const operation = response.operation;
			if (operation) {
				void this.view
					?.ensureDeferredOperations?.()
					.then((manager) =>
						manager?.track(operation, { node: component.active?.target }),
					);
			}
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
			const { modal } = response;
			void this.view?.ensureModalClasses?.().then((classes) => {
				if (!classes?.Modal || !this.view || this.view._destroyed) return;
				if (typeof modal === "string") {
					captureError(
						new TypeError("Modal markup must be parsed before attachment"),
						component,
					);
					return;
				}
				void new classes.Modal(this.view).attach(modal, component);
			});
			this._clearActiveSubmitter();
			return false;
		}

		return true;
	}

	async update(
		component: ViewComponent,
		data: FormData,
		route: string | URL | undefined = component.route,
	) {
		const view = this.view;
		if (!view) return;
		if (!view.online) {
			const queue = view.offlineQueue || (await view.ensureOfflineQueue?.());
			const response =
				route &&
				(await queue?.queueSubmit(component, data, String(route), "PUT"));
			if (response) {
				await withTransition(
					() => {
						getSubmissionWidget(component)?.form?.queued?.();
						this._clearActiveSubmitter();
					},
					{ label: "submission:queue-offline" },
				);
			} else {
				this._clearActiveSubmitter();
			}
			return;
		}

		const submittedWidget = getSubmissionWidget(component);
		const revisionWidget = isRevisionWidget(submittedWidget)
			? submittedWidget
			: null;
		const submittedSnapshot = revisionWidget?.revisionSnapshot();
		const response = await request.put<SubmissionFields>(
			route ?? String(route),
			data,
		);
		if (
			component.active !== submittedWidget ||
			submittedWidget?.target?.isConnected === false
		) {
			// The request still belongs to its original form after navigation.
			if (response?.deferred && response.operation) {
				const operations = await this.view?.ensureDeferredOperations?.();
				operations?.track(response.operation, {
					status: isOperationStatus(response.status)
						? response.status
						: undefined,
					revision: response.revision,
				});
			}
			this._clearActiveSubmitter();
			return;
		}
		if (response?.conflict) {
			try {
				const watcher = await this.view?.ensureEditWatcher?.();
				if (
					revisionWidget &&
					(await watcher?.stageConflict?.(revisionWidget, { response }))
				)
					await watcher?.openConflictReview?.(revisionWidget, {
						blockedAction:
							data.get("role") === "autofill-submit" ? "autofill" : null,
					});
			} finally {
				submittedWidget?.form?.resetSubmitButton?.();
				this._clearActiveSubmitter();
			}
			return;
		}
		if (!this.successfulResponse(response, component)) return;
		const changedDuringSave =
			revisionWidget && submittedSnapshot !== revisionWidget.revisionSnapshot();
		if (response.deferred) {
			if (response.form_revision && revisionWidget) {
				revisionWidget.reviewState =
					response.form_state ?? revisionWidget.reviewState ?? {};
				revisionWidget.reviewState.revision = response.form_revision;
				if (revisionWidget.initialTarget) {
					revisionWidget.initialTarget.dataset.formState = JSON.stringify(
						revisionWidget.reviewState,
					);
				}
				// A deferred start does not change the saved baseline or this tab's draft.
				delete revisionWidget._autofillRetry;
			}
			await this._deferredUpdated(response, component);
			return;
		}
		// A successful ordinary save consumed the review markers on the server.
		// Carrying them into a later Update would refer to an obsolete review.
		revisionWidget?._reviewedOperations?.clear();
		revisionWidget?._usedAutofillOperations?.clear();
		if (changedDuringSave && revisionWidget) {
			if (Object.hasOwn(response, "submission"))
				revisionWidget._baselineSubmission = structuredClone(
					response.submission ?? {},
				);
			try {
				const watcher = await this.view?.ensureEditWatcher?.();
				await watcher?.stageConflict?.(revisionWidget, { response });
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

	async create(
		component: ViewComponent,
		data: FormData,
		route: string | URL | undefined = component.route,
	) {
		const view = this.view;
		if (!view) return;
		if (!view.online) {
			const queue = view.offlineQueue || (await view.ensureOfflineQueue?.());
			const response =
				route &&
				(await queue?.queueSubmit(component, data, String(route), "POST"));
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

		const response = await request.post<SubmissionFields>(
			route ?? String(route),
			data,
		);
		if (!this.successfulResponse(response, component)) return;
		getSubmissionWidget(component)?.form?.clearUnsavedState?.();
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

	async _deferredCreated(
		response: SubmissionResponse,
		component: ViewComponent,
	) {
		const [operations, notifications] = await Promise.all([
			this.view?.ensureDeferredOperations?.(),
			response.notification ? this.view?.ensureNotifications?.() : null,
		]);
		if (response.operation) {
			operations?.track(response.operation, {
				node: response.background ? null : component.active?.target,
			});
		}
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

		await getSubmissionWidget(component)?.created?.(response);
		await getSubmissionWidget(component)?.prereconcile?.();
		await withTransition(
			() => {
				const widget = getSubmissionWidget(component);
				widget?.postreconcile?.();
				widget?.success?.();
				this._clearActiveSubmitter();
			},
			{ label: "submission:create-without-html" },
		);
	}

	async _deferredUpdated(
		response: SubmissionResponse,
		component: ViewComponent,
	) {
		const widget = getSubmissionWidget(component);
		if (response.scope === "form-autofill" && !response.already_running) {
			const form = widget?.form;
			const subform = form?._subForm;
			if (subform) {
				if (subform.target) subform.target.dataset.visible = "false";
				subform.reset?.();
				form.toggleSubForm();
			}
		}
		if (response.locked && isRevisionWidget(widget)) {
			widget.lockDeferredOperation?.({
				...response,
				status: isOperationStatus(response.status)
					? response.status
					: undefined,
			});
		}
		const [operations, notifications] = await Promise.all([
			this.view?.ensureDeferredOperations?.(),
			response.notification ? this.view?.ensureNotifications?.() : null,
		]);
		if (response.operation) {
			operations?.track(response.operation, {
				node: component.active?.target,
				status: isOperationStatus(response.status)
					? response.status
					: undefined,
				revision: response.revision,
			});
		}
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
				getSubmissionWidget(component)?.form?.success?.();
			}
			this._clearActiveSubmitter();
		});
	}

	destroy() {
		this._clearActiveSubmitter();
		this.view = null;
	}
}
