import {
	FormController,
	type FormSubmitOptions,
} from "../../forms/controller.ts";
import { installMigrationNotice } from "../../forms/migrationNotice.ts";
import { compatibleField } from "../../forms/representation.ts";
import {
	currentReviewOperation,
	installReviewBar,
	renderReviewBar,
} from "../../forms/reviewBar.ts";
import type { EditWatcher } from "../../forms/revisions/watcher.ts";
import type { DeferredOperationManager } from "../../shared/deferredOperations.ts";
import type { Modal } from "../../shared/modal.ts";
import type { OfflineQueue } from "../../shared/offlineQueue.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { RequestResult } from "../../types/api";
import type {
	CapturedFormState,
	FormReviewOperation,
	FormReviewState,
	FormRevisionConflict,
	FormRevisionResponse,
	FormSchema,
	FormSubmission,
} from "../../types/forms";
import type { WidgetSettings } from "../../types/widgets";

interface FormWidgetComponent {
	active?: object | null;
	elt?: HTMLElement | null;
	formData?: FormData | null;
	kind?: string | null;
	visible?: boolean;
	showEmptyFields?: boolean;
	showError?(message: string): void;
}

type FormQueueWidget = NonNullable<Parameters<OfflineQueue["presentFor"]>[0]>;
type FormEditWatcher = Pick<EditWatcher, "stageConflict">;
type FormDeferredOperations = Pick<
	DeferredOperationManager,
	"receive" | "scan" | "track"
>;

type FormWidgetView = NonNullable<ConstructorParameters<typeof Modal>[0]> & {
	elt?: HTMLElement | null;
	kind?: string | null;
	offline?: boolean;
	offlineQueue?: Pick<OfflineQueue, "presentFor"> | null;
	EditWatcher?: FormEditWatcher | null;
	ensureEditWatcher?(): Promise<FormEditWatcher | null | undefined>;
	ensureDeferredOperations?(): Promise<
		FormDeferredOperations | null | undefined
	>;
	reportStartupError?(error: unknown, target: HTMLElement, stage: string): void;
	operationId?(): string;
};

export interface FormWidgetSettings
	extends Partial<
		WidgetSettings<FormWidgetComponent | null, FormWidgetView | null>
	> {
	target: HTMLElement;
	name: string;
	readonly?: boolean;
	headless?: boolean;
	revisionPreview?: boolean;
	historyFillEnabled?: boolean;
	html?: (Node | string | null | false)[] | null;
	prepend?: FormWidgetSettings["html"];
	append?: FormWidgetSettings["html"];
	htmlFields?: Record<string, string> | null;
	icon?: string | null;
	error?: HTMLElement | null;
	handleOfflineQueue?: FormQueueWidget["handleOfflineQueue"];
	offline?: FormQueueWidget["offline"];
	[attribute: string]: unknown;
}

interface Destroyable {
	destroy?(): void;
}

interface DeferredOperationDescriptor {
	operation?: string | null;
	key?: string | null;
	revision?: FormReviewOperation["revision"] | null;
	scope?: FormReviewOperation["scope"];
	blocks_edit?: boolean;
	status?: FormReviewOperation | null;
}

export interface LocalRevisionOptions {
	remoteSnapshot?: string | null;
	markUnsaved?: boolean;
	selectedSubmission?: FormSubmission;
}

interface RevisionDraft {
	fields?: CapturedFormState["fields"] | null;
	files?: Pick<CapturedFormState["files"][number], "name" | "file">[] | null;
	form_controls?: CapturedFormState["form_controls"] | null;
	renderer_schema?: FormSchema | null;
	renderer_submission?: FormSubmission | null;
}

type FormCombobox = {
	name?: string;
	options?: { id: string }[];
	values?: ReadonlySet<string>;
};

type WidgetTarget = HTMLElement & { _lp_widget?: FormWidget };
type FormFieldTarget = HTMLElement & { _lp_element?: { clear?(): void } };

type ResetState = {
	target: HTMLElement;
	initialTarget: HTMLElement | null;
	form: FormController | null;
	initialized: boolean;
	loaded: boolean | undefined;
	destroyables: Destroyable[];
	_migrationNotice: { destroy(): void } | null;
	_reviewBar: { destroy(): void } | null;
} & Record<PropertyKey, unknown>;

interface PreparedReset {
	adopt: string[];
	state: ResetState;
	revisionBaseline: string;
	baselineSubmission: FormSubmission;
	activate(): void;
	version?: number;
}

export interface FormResetOptions<Widget extends FormWidget> {
	nextTarget?: HTMLElement;
	staged?: Partial<ResetState>;
	beforeInit?: ((widget: Widget) => void | Promise<void>) | null;
	afterInit?: ((widget: Widget) => void | Promise<void>) | null;
}

export class FormWidget {
	declare target: HTMLElement;
	declare component?: FormWidgetComponent | null;
	declare view?: FormWidgetView | null;
	declare name: string;
	declare key?: string | null;
	declare kind?: string;
	declare visible?: boolean;
	declare modified?: boolean;
	declare readonly?: boolean;
	declare loaded?: boolean;
	declare headless?: boolean;
	declare revisionPreview?: boolean;
	declare htmlFields?: FormWidgetSettings["htmlFields"];
	declare icon?: FormWidgetSettings["icon"];
	declare error?: FormWidgetSettings["error"];
	// Settings and subclasses can supply hooks used by offline submission.
	offline?(
		...args: Parameters<NonNullable<FormQueueWidget["offline"]>>
	): ReturnType<NonNullable<FormQueueWidget["offline"]>>;
	handleOfflineQueue?(
		...args: Parameters<NonNullable<FormQueueWidget["handleOfflineQueue"]>>
	): ReturnType<NonNullable<FormQueueWidget["handleOfflineQueue"]>>;
	declare reviewState?: FormReviewState | null;
	declare _reviewedOperations?: Set<string>;
	declare _usedAutofillOperations?: Set<string>;
	declare _autofillRetry?: string | null;
	declare _autofillRetryPending?: boolean;
	declare _offlineConflict?: FormRevisionConflict | null;
	declare _skipQueuedRestore?: boolean;
	declare _baselineSubmission?: FormSubmission;

	declare destroyables: Destroyable[];
	declare messages: Record<string, string>;
	declare schema: FormSchema | null;
	declare submission: FormSubmission | null;
	declare form: FormController | null;
	declare initialTarget: HTMLElement | null;
	declare initialized: boolean;
	declare unsavedState: boolean;
	declare _revisionBaseline: string | null;
	declare _created: boolean;
	declare _updated: boolean;
	declare _success: boolean;
	declare _resetEpoch: number;
	declare _replacementVersion: number;
	declare _deferredOperation: string | null;
	declare _preparedReset: PreparedReset | null;
	declare _preparingReset: Promise<void> | null;
	declare _preparingState: ResetState | null;
	declare _replacementPromise: Promise<void> | null;
	declare _replacementInert: boolean | null;
	declare _migrationNotice: ResetState["_migrationNotice"];
	declare _reviewBar: ResetState["_reviewBar"];

	constructor(attributes: FormWidgetSettings) {
		Object.assign(this, attributes);
		this.destroyables = [];
		this.messages = {};
		this.schema = attributes.schema || null;
		this.submission = attributes.submission || null;
		this.form = null;
		this.initialTarget = this.target
			? (this.target.cloneNode(true) as HTMLElement)
			: null;
		this.initialized = false;
		this.unsavedState = false;
		this._revisionBaseline = null;

		this._created = false;
		this._updated = false;
		this._success = false;
		this._preparedReset = null;
		this._preparingReset = null;
		this._preparingState = null;
		this._resetEpoch = 0;
		this._replacementVersion = 0;
		this._replacementPromise = null;
		this._replacementInert = null;
		this._migrationNotice = null;
		this._reviewBar = null;

		this._deferredOperation = this.target?.dataset?.operation || null;

		this._click = this._click.bind(this);
	}

	get deferredLocked() {
		return Boolean(
			this._deferredOperation && this.target?.dataset?.deferredLock,
		);
	}

	lockDeferredOperation(descriptor: DeferredOperationDescriptor = {}) {
		const operation = descriptor.operation || descriptor.key;
		if (!operation) return false;
		this._deferredOperation = operation;
		for (const target of [this.target, this.initialTarget]) {
			if (!target) continue;
			target.dataset.operation = operation;
			target.dataset.operationRevision = String(descriptor.revision ?? 0);
			target.dataset.operationScope = descriptor.scope || "";
			if (descriptor.blocks_edit === true || descriptor.scope === "form-change")
				target.dataset.deferredLock = "form";
			else delete target.dataset.deferredLock;
			if (descriptor.status && typeof descriptor.status === "object") {
				target.dataset.operationBootstrap = JSON.stringify(descriptor.status);
				if (target.dataset.formState) {
					const state: FormReviewState = JSON.parse(target.dataset.formState);
					state.operation = descriptor.status;
					if (
						descriptor.status.type === "autofill" &&
						!descriptor.status.terminal
					)
						state.stale_autofill = false;
					target.dataset.formState = JSON.stringify(state);
				}
			}
		}
		if (descriptor.status && typeof descriptor.status === "object") {
			this.reviewState = { ...this.reviewState, operation: descriptor.status };
			if (descriptor.status.type === "autofill" && !descriptor.status.terminal)
				this.reviewState.stale_autofill = false;
			renderReviewBar(this, descriptor.status);
		}
		return true;
	}

	get showEmptyFields() {
		return this.readonly && this.component?.showEmptyFields === true;
	}
	get formData() {
		const data =
			this.target instanceof HTMLFormElement
				? new FormData(this.target)
				: new FormData();
		const state: FormReviewState =
			this.reviewState ?? JSON.parse(this.target?.dataset?.formState || "{}");
		if (state.revision) data.set("form-revision", state.revision);
		for (const operation of this._reviewedOperations ?? [])
			data.append("reviewed-operation", operation);
		for (const operation of this._usedAutofillOperations ?? [])
			data.append("used-autofill-operation", operation);
		if (this._autofillRetry) data.set("autofill-retry", this._autofillRetry);
		return this.form?._subForm?.applyDirectUploads?.(data) ?? data;
	}

	get revisionEntries(): Iterable<[name: string, value: FormDataEntryValue]> {
		return [];
	}

	get revisionBaseline() {
		return this._revisionBaseline;
	}

	revisionSnapshot() {
		const grouped = new Map<string, string[]>();
		const entries = [...this.formData.entries(), ...this.revisionEntries];
		for (const [name, rawValue] of entries) {
			if (
				[
					"form-revision",
					"reviewed-operation",
					"used-autofill-operation",
					"autofill-retry",
				].includes(name)
			)
				continue;
			let value = rawValue;
			if (typeof File !== "undefined" && rawValue instanceof File) {
				if (!rawValue.name && rawValue.size === 0) continue;
				value = JSON.stringify({
					name: rawValue.name,
					size: rawValue.size,
					type: rawValue.type,
					lastModified: rawValue.lastModified,
				});
			}
			const values = grouped.get(name) ?? [];
			values.push(String(value));
			grouped.set(name, values);
		}

		return JSON.stringify(
			Array.from(grouped.entries())
				.sort(([left], [right]) => left.localeCompare(right))
				.map(([name, values]) => [name, values.sort()]),
		);
	}

	commitRevisionBaseline({ clearUnsaved = false } = {}) {
		this._revisionBaseline = this.revisionSnapshot();
		this._baselineSubmission = structuredClone(
			this.form?.renderer?._packageSubmission?.() ?? this.submission ?? {},
		);
		if (clearUnsaved) this.clearUnsavedState();
		return this._revisionBaseline;
	}

	revisionCanReset(preview: Pick<FormWidget, "name"> | null | undefined) {
		return Boolean(preview && preview.name === this.name);
	}

	captureFormState(): CapturedFormState {
		const fields: CapturedFormState["fields"] = [];
		const files: CapturedFormState["files"] = [];
		for (const [name, value] of this.formData.entries()) {
			if (typeof File !== "undefined" && value instanceof File) {
				if (value.name && value.size > 0) {
					files.push({
						name,
						file: value,
						filename: value.name,
						type: value.type,
					});
				}
			} else {
				fields.push([name, value as string]);
			}
		}

		const formControls = Array.from(
			this.target?.querySelectorAll?.<
				HTMLElement & { _lp_combobox?: FormCombobox }
			>("[data-combobox-id]") || [],
		)
			.filter((control) => !control.closest?.(".form-element"))
			.map((control) => {
				const combobox = control._lp_combobox;
				if (!combobox?.name) return null;
				return {
					name: combobox.name,
					options: (combobox.options || []).filter((option) =>
						combobox.values?.has(option.id),
					),
				};
			})
			.filter((control) => control !== null);

		return {
			fields,
			files,
			form_controls: formControls,
			renderer_schema: structuredClone(this.schema),
			renderer_submission: this.form?.renderer?._packageSubmission?.() ?? null,
		};
	}

	buildLocalRevision(
		response: FormRevisionResponse,
		state: RevisionDraft = this.captureFormState(),
	) {
		const latestSchema = response.schema ?? [];
		const localSchema = state.renderer_schema ?? this.schema ?? [];
		const latestIds = new Set(
			latestSchema.map((field) => field?.id).filter(Boolean),
		);
		const localIds = new Set(
			localSchema.map((field) => field?.id).filter(Boolean),
		);
		const remoteSubmission = response.submission ?? {};
		const mergedSubmission = structuredClone(remoteSubmission);
		const localSubmission = state.renderer_submission ?? {};
		for (const id of localIds) {
			if (
				!latestIds.has(id) ||
				!Object.hasOwn(localSubmission, id) ||
				!compatibleField(
					localSchema.find((field) => field.id === id),
					latestSchema.find((field) => field.id === id),
				)
			)
				continue;
			mergedSubmission[id] = structuredClone(localSubmission[id]);
		}

		const html = response.html
			? (response.html.cloneNode(true) as Document)
			: null;
		const target = html?.querySelector<HTMLElement>(
			`[data-widget='${this.name}']`,
		);
		this._applyQueuedFields(target, state);
		return {
			state,
			response: {
				...response,
				html,
				schema: latestSchema,
				submission: mergedSubmission,
			},
		};
	}

	async prepareRevision(response: FormRevisionResponse) {
		await this.updated(response);
		this._success = false;
		await this.prereconcile();
		return () => {
			this.postreconcile();
			this.commitRevisionBaseline({ clearUnsaved: true });
		};
	}

	async applyRevision(response: FormRevisionResponse) {
		const commit = await this.prepareRevision(response);
		commit();
	}

	async prepareLocalRevision(
		response: FormRevisionResponse,
		{
			remoteSnapshot = null,
			markUnsaved = false,
			selectedSubmission = undefined,
		}: LocalRevisionOptions = {},
	) {
		const wasUnsaved = this.unsavedState === true;
		const wasQueued = this.form?._queued === true;
		const local = this.buildLocalRevision(response);
		if (selectedSubmission !== undefined) {
			local.response.submission = selectedSubmission;
		}
		await this.updated(local.response);
		this._success = false;
		await this.prereconcile();

		return () => {
			this._skipQueuedRestore = true;
			try {
				this.postreconcile();
				this._restoreQueuedFiles(local.state);
			} finally {
				this._skipQueuedRestore = false;
			}

			if (remoteSnapshot !== null) this._revisionBaseline = remoteSnapshot;
			this._baselineSubmission = structuredClone(response.submission ?? {});
			if (wasQueued) {
				this.form?.queued();
			} else if (wasUnsaved || markUnsaved) {
				this.markUnsavedState();
			} else {
				this.commitRevisionBaseline({ clearUnsaved: true });
			}
			return local;
		};
	}

	async applyLocalRevision(
		response: FormRevisionResponse,
		options: LocalRevisionOptions = {},
	) {
		const commit = await this.prepareLocalRevision(response, options);
		return commit();
	}

	async prepareSubmit(options?: FormSubmitOptions) {
		if (this.deferredLocked) return false;
		return (await this.form?._subForm?.prepareSubmit?.(options)) ?? true;
	}

	markUnsavedState() {
		if (this.readonly || this.headless) return;

		this.unsavedState = true;
		this.form?.syncOfflineState?.();
	}

	clearUnsavedState() {
		this.unsavedState = false;
	}

	init(): void | Promise<void>;
	async init() {
		if (
			this.target?.hasAttribute("lp-load") &&
			!this.target.hasAttribute("loaded")
		)
			return;
		await this._initForm();
		this.commitRevisionBaseline();
		this.initialized = true;
		this.target.setAttribute("initialized", "");
		const queue = this.view?.offlineQueue;
		if (
			typeof queue?.presentFor === "function" &&
			typeof this.handleOfflineQueue === "function"
		) {
			void queue.presentFor(this).catch((error) => {
				this.view?.reportStartupError?.(
					error,
					this.target,
					"offline-conflict-restore",
				);
			});
		}
	}

	async stageOfflineConflict(conflict = this._offlineConflict) {
		if (!conflict) return;
		const watcher =
			this.view?.EditWatcher || (await this.view?.ensureEditWatcher?.());
		return watcher?.stageConflict?.(this, conflict);
	}

	_applyQueuedFields(
		target: HTMLElement | null | undefined,
		record: RevisionDraft,
	) {
		if (!target) return;

		const fields = new Map<string, string[]>();
		for (const [name, value] of record.fields || []) {
			const values = fields.get(name) || [];
			values.push(String(value));
			fields.set(name, values);
		}

		for (const name of ["name", "description"]) {
			const values = fields.get(name);
			if (values) target.dataset[name] = values[0] || "";
		}

		for (const control of target.querySelectorAll<
			HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
		>("[name]")) {
			if (
				["form-generation", "form-revision", "reviewed-operation"].includes(
					control.name,
				)
			)
				continue;
			const values = fields.get(control.name) || [];
			if (control instanceof HTMLInputElement) {
				if (["checkbox", "radio"].includes(control.type)) {
					const checked = values.includes(control.value);
					control.checked = checked;
					control.defaultChecked = checked;
					control.toggleAttribute("checked", checked);
					const attribute = control.closest<HTMLElement>(
						"[data-role='attribute']",
					);
					if (attribute) attribute.dataset.selected = checked.toString();
				} else if (control.type !== "file" && values.length > 0) {
					control.value = values[0];
					control.defaultValue = values[0];
					control.setAttribute("value", values[0]);
				}
			} else if (control instanceof HTMLTextAreaElement) {
				control.value = values[0] || "";
				control.defaultValue = control.value;
				control.textContent = control.value;
			} else if (control instanceof HTMLSelectElement) {
				for (const option of control.options) {
					const selected = values.includes(option.value);
					option.selected = selected;
					option.defaultSelected = selected;
					option.toggleAttribute("selected", selected);
				}
			}
		}

		const preloadSources = Array.from(
			target.querySelectorAll<HTMLElement>("[name], [data-index]"),
		);
		for (const state of record.form_controls || []) {
			const source = preloadSources.find(
				(element) =>
					element.getAttribute("name") === state.name ||
					element.dataset.index === state.name,
			);
			if (!source) continue;
			const root = source.closest<HTMLElement>("[lp-select]") || source;
			const preload = JSON.stringify(state.options || []);
			source.dataset.preload = preload;
			root.dataset.preload = preload;
		}
	}

	_restoreQueuedFiles(record: RevisionDraft) {
		if (typeof DataTransfer === "undefined") return;

		const files = new Map<string, Blob[]>();
		for (const entry of record.files || []) {
			const values = files.get(entry.name) || [];
			values.push(entry.file);
			files.set(entry.name, values);
		}

		for (const input of this.target.querySelectorAll<HTMLInputElement>(
			"input[type='file'][name]",
		)) {
			const saved = files.get(input.name);
			if (!saved?.length) continue;
			try {
				const transfer = new DataTransfer();
				for (const file of saved) transfer.items.add(file as File);
				input.files = transfer.files;
			} catch {
				// Some browsers do not allow programmatic file-input restoration.
			}
		}
	}

	async _initForm({ replace = true } = {}) {
		if (replace && this.initialTarget) {
			const visible = this.target?.dataset.visible;
			if (visible !== undefined) {
				this.initialTarget.dataset.visible = visible;
			}
			this.target.replaceWith(this.initialTarget);
			this.target = this.initialTarget;
			this.initialTarget = this.target.cloneNode(true) as HTMLElement;
		} else if (!this.initialTarget) {
			this.initialTarget = this.target.cloneNode(true) as HTMLElement;
		}
		(this.target as WidgetTarget)._lp_widget = this;
		this.form = new FormController(this);
		await this.form.init();
		if (this.target.dataset.formState) installReviewBar(this);
		if (
			this.target.dataset.migrationNotice &&
			this.target.dataset.migrationNotice !== "[]"
		)
			installMigrationNotice(this);
		if (this.target.dataset.formGeneration !== undefined) {
			const generation = document.createElement("input");
			generation.type = "hidden";
			generation.name = "form-generation";
			generation.value = this.target.dataset.formGeneration;
			this.target.append(generation);
		}
		this.target.addEventListener("click", this._click);
		const hasDeferredOperation =
			this.target.matches?.("[data-operation]") ||
			this.target.querySelector?.("[data-operation]");
		if (hasDeferredOperation) {
			const manager = await this.view?.ensureDeferredOperations?.();
			manager?.scan(this.target);
		}
		this.initialized = true;
		this.loaded = this.target.hasAttribute("loaded");
		this.target.setAttribute("initialized", "");
	}

	_click(e: MouseEvent) {
		if (this.readonly) return;

		const target = e.target as Element | null;
		if (!target?.closest) return;
		const element = target.closest<FormFieldTarget>(".form-element");
		const role = target.closest<HTMLElement>("[data-role]")?.dataset.role;
		if (role !== "edit" && role !== "clear") return;

		e.preventDefault();
		e.stopPropagation();
		if (!element) return;

		if (role === "edit") {
			void withTransition(
				() => {
					element.dataset.mode = "edit";
				},
				{ label: "form:edit-field" },
			);
		} else if (role === "clear") {
			const field =
				element._lp_element ?? this.form?.renderer?.elements.get(element.id);
			field?.clear?.();
		}
	}

	get header() {
		return this.target?.querySelector<HTMLElement>("[data-role='header']");
	}

	get submitGroup() {
		return this.target?.querySelector<HTMLElement>(
			"[data-role='submit-group']",
		);
	}

	get submitButton() {
		return this.target?.querySelector<HTMLButtonElement>(
			'button[type="submit"]:not([data-role])',
		);
	}

	async prepareReset(options: FormResetOptions<this> = {}) {
		if (this._preparingReset) return this._preparingReset;
		if (this._preparedReset) return;
		const pending = this._prepareReset(options);
		this._preparingReset = pending;
		try {
			await pending;
		} finally {
			if (this._preparingReset === pending) this._preparingReset = null;
		}
	}

	async _prepareReset({
		nextTarget = (this.initialTarget || this.target).cloneNode(
			true,
		) as HTMLElement,
		staged = {},
		beforeInit = null,
		afterInit = null,
	}: FormResetOptions<this> = {}) {
		if (this._preparedReset) return;
		const epoch = this._resetEpoch;

		const visible = this.target?.dataset.visible;
		if (visible !== undefined) nextTarget.dataset.visible = visible;

		const stagedState: ResetState = {
			target: nextTarget,
			initialTarget: null,
			form: null,
			initialized: false,
			loaded: this.loaded,
			destroyables: [],
			_migrationNotice: null,
			_reviewBar: null,
			...staged,
		};
		let adopted = false;
		const stagedWidget = new Proxy(this, {
			get(target, property, receiver) {
				if (!adopted && Object.hasOwn(stagedState, property)) {
					return stagedState[property];
				}
				return Reflect.get(target, property, receiver);
			},
			set(target, property, value) {
				if (!adopted) {
					stagedState[property] = value;
					return true;
				}
				return Reflect.set(target, property, value);
			},
		});
		this._preparingState = stagedState;
		try {
			await beforeInit?.(stagedWidget);
			if (epoch !== this._resetEpoch) return;
			await stagedWidget._initForm({ replace: false });
			if (epoch !== this._resetEpoch) return;
			await afterInit?.(stagedWidget);
			if (epoch !== this._resetEpoch) return;
			this._preparedReset = {
				adopt: Object.keys(stagedState),
				state: stagedState,
				revisionBaseline: stagedWidget.revisionSnapshot(),
				baselineSubmission: structuredClone(
					stagedWidget.form?.renderer?._packageSubmission?.() ??
						stagedWidget.submission ??
						{},
				),
				activate: () => {
					adopted = true;
				},
			};
		} finally {
			if (this._preparedReset?.state !== stagedState)
				this._destroyFormState(stagedState);
			if (this._preparingState === stagedState) this._preparingState = null;
		}
	}

	commitReset() {
		if (!this._preparedReset) return false;
		const { adopt, state, revisionBaseline, baselineSubmission, activate } =
			this._preparedReset;
		this._preparedReset = null;
		const previousTarget = this.target;
		const previousInert = this._replacementInert;
		const visible = previousTarget?.dataset.visible;
		if (visible !== undefined) state.target.dataset.visible = visible;

		this.clearUnsavedState();
		this.destroy();
		if (previousTarget !== state.target)
			previousTarget.replaceWith(state.target);
		const widget = this as FormWidget & Record<string, unknown>;
		for (const property of adopt) widget[property] = state[property];
		if (previousInert != null) this.target.inert = previousInert;
		activate?.();
		(this.target as WidgetTarget)._lp_widget = this;
		this._revisionBaseline = revisionBaseline;
		this._baselineSubmission = baselineSubmission;
		return true;
	}

	discardPreparedReset() {
		this._resetEpoch = (this._resetEpoch || 0) + 1;
		if (this._preparingState) this._destroyFormState(this._preparingState);
		if (this._preparedReset) this._destroyFormState(this._preparedReset.state);
		this._preparedReset = null;
	}

	_destroyFormState(state: ResetState) {
		state._reviewBar?.destroy();
		state._reviewBar = null;
		state._migrationNotice?.destroy();
		state._migrationNotice = null;
		state.form?.destroy?.();
		state.destroyables?.forEach((destroyable) => {
			destroyable.destroy?.();
		});
		state.destroyables = [];
	}

	async reset() {
		await this.prepareReset();
		this.commitReset();
	}

	setEntityMetadata() {
		if (this.revisionPreview) return;
		const pageTitle = document.querySelector(
			"[data-nav='view'] [data-role='title']",
		);
		const pageDescription = document.querySelector("[data-role='description']");

		const name =
			this.target.querySelector<HTMLInputElement>("[name='name']")?.value ||
			this.target.dataset.name ||
			"";
		const description =
			this.target.querySelector<HTMLTextAreaElement>("[name='description']")
				?.value ||
			this.target.dataset.description ||
			"";

		if (pageTitle && pageTitle.textContent !== name)
			pageTitle.textContent = name;
		if (pageDescription && pageDescription.textContent !== description)
			pageDescription.textContent = description;
	}

	created(response?: RequestResult): void;
	created() {
		this._created = true;
	}

	success() {
		this._success = true;
	}

	updated(response: FormRevisionResponse) {
		const updatedTarget = (response.html || null)?.querySelector<HTMLElement>(
			`[data-widget='${this.name}']`,
		);
		const ownsRendererState =
			!updatedTarget ||
			[updatedTarget, this.target, this.initialTarget].some(
				(target) =>
					target?.hasAttribute?.("data-schema") ||
					target?.hasAttribute?.("data-submission"),
			);
		if (updatedTarget) {
			this.initialTarget = updatedTarget;
			this._deferredOperation = updatedTarget.dataset.operation || null;
			this._updated = true;
			this._replacementVersion = (this._replacementVersion || 0) + 1;
		}
		if (ownsRendererState && Object.hasOwn(response, "schema")) {
			this.schema = response.schema as FormSchema | null;
		}
		if (ownsRendererState && Object.hasOwn(response, "submission")) {
			this.submission = response.submission as FormSubmission | null;
		}
		if (
			ownsRendererState &&
			Object.hasOwn(response, "form_state") &&
			this.initialTarget
		) {
			const formState = response.form_state as FormReviewState;
			const operation = currentReviewOperation(this, formState.operation);
			this.initialTarget.dataset.formState = JSON.stringify({
				...formState,
				operation,
			});
			if (operation?.key)
				this.lockDeferredOperation({
					operation: operation.key,
					revision: operation.revision,
					scope: operation.scope,
					blocks_edit: operation.blocks_edit,
					status: operation,
				});
		}
		if (
			ownsRendererState &&
			Object.hasOwn(response, "generation") &&
			this.initialTarget
		)
			this.initialTarget.dataset.formGeneration = String(response.generation);
		if (
			ownsRendererState &&
			Object.hasOwn(response, "migration_notice") &&
			this.initialTarget
		)
			this.initialTarget.dataset.migrationNotice = JSON.stringify(
				response.migration_notice,
			);
	}

	async prereconcile() {
		if (this._replacementPromise) return this._replacementPromise;
		if (!this._updated) return;
		if (this._preparedReset?.version === this._replacementVersion) return;
		this._replacementInert ??= Boolean(this.target.inert);
		this.target.inert = true;
		const pending = (async () => {
			let preparedVersion: number;
			do {
				preparedVersion = this._replacementVersion;
				this.discardPreparedReset();
				await this.prepareReset();
				if (this._preparedReset) this._preparedReset.version = preparedVersion;
			} while (preparedVersion !== this._replacementVersion);
		})();
		this._replacementPromise = pending;
		try {
			await pending;
		} catch (error) {
			this._restoreInteractivity();
			throw error;
		} finally {
			if (this._replacementPromise === pending) this._replacementPromise = null;
		}
	}

	_restoreInteractivity() {
		if (this._replacementInert == null) return;
		this.target.inert = this._replacementInert;
		this._replacementInert = null;
	}

	postreconcile() {
		const updated = this._updated;
		if (!this._created && !updated) return;
		if (
			updated &&
			(this._replacementPromise ||
				(this._preparedReset?.version !== undefined &&
					this._preparedReset.version !== this._replacementVersion))
		) {
			this.modified = true;
			return;
		}

		this._created = false;
		this._updated = false;

		if (updated) {
			this.commitReset();
			this._restoreInteractivity();
			if (this.visible) this.target.dataset.visible = "true";
		}

		if (this._success) {
			this.form?.success();
			this._success = false;
		}
	}

	destroy() {
		this.discardPreparedReset();
		this._restoreInteractivity();
		this._reviewBar?.destroy();
		this._reviewBar = null;
		this._migrationNotice?.destroy();
		this._migrationNotice = null;
		this.form?.destroy();
		this.destroyables.forEach((destroyable) => {
			if (destroyable.destroy) destroyable.destroy();
		});
		this.destroyables = [];
		this.form = null;
	}

	showError(error: string) {
		this.form?.showError(error);
	}
}
