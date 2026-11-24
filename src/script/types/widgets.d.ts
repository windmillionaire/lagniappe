import type { FormSchema, FormSubmission } from "./forms";

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
