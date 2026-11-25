import type { FormController } from "../forms/controller.ts";
import type { FormWidget } from "../widgets/base/formWidget.ts";
import type { RequestResult } from "./api";
import type { FormSchema, FormSubmission } from "./forms";
import type { SyncWidget } from "./sync";

declare global {
	/** Replaced by Rollup in the main frontend bundle. */
	const __BUILD_ID__: string;
	const __VERSION__: string;
}

export interface WidgetEndpointSettings {
	key?: string | null;
}

/** Data collected by the widget loader before it instantiates a widget. */
export interface WidgetSettings<Component = unknown, View = unknown>
	extends WidgetEndpointSettings {
	component: Component;
	view: View;
	name: string;
	target?: HTMLElement;
	kind?: string;
	route?: string;
	visible: boolean;
	modified: boolean;
	persistent?: boolean;
	loaded?: boolean;
	attributes?: Record<string, unknown>;
	schema?: FormSchema | null;
	submission?: FormSubmission | null;
}

/** Lifecycle installed by the loader and hooks implemented by individual widgets. */
export type LoadedWidget = WidgetLifecycle & (SyncWidget | { syncId?: null });

interface WidgetLifecycle {
	name: string;
	component?: {
		key?: string | null;
		visible?: boolean;
		elt?: HTMLElement | null;
		formData?: FormData | null;
	} | null;
	key?: string | null;
	target?: HTMLElement;
	route?: string;
	readonly?: boolean;
	visible?: boolean;
	modified?: boolean;
	persistent?: boolean;
	loaded?: boolean;
	loading?: boolean;
	initialized?: boolean;
	DEFAULT?: boolean;
	ifEmpty?: string | false | null;
	refreshScope?: "collection";
	unsavedState?: boolean;
	form?: FormController | null;
	formData?: FormData | null;
	schema?: FormSchema | null;
	offline?: FormWidget["offline"];
	handleOfflineQueue?: FormWidget["handleOfflineQueue"];
	init?(): void | Promise<void>;
	enable(): void;
	disable(force?: boolean): void;
	prepareReconcile(silent?: boolean): Promise<void>;
	prepareSubmit?: FormWidget["prepareSubmit"];
	reconcile(silent?: boolean): void;
	prereconcile?(): unknown;
	postreconcile?(): unknown;
	updated?(
		response: RequestResult,
	): void | HTMLElement | null | Promise<void> | Promise<HTMLElement | null>;
	created?(response: RequestResult): unknown;
	opened?(): unknown;
	refresh?(response: RequestResult | undefined): unknown;
	prepareRefresh?(
		response: RequestResult,
	): Promise<(() => void) | null | undefined>;
	showError?(message: string): void;
	success?(): void;
	syncPollingSubscription?(): unknown;
	destroy?(): void;
}
